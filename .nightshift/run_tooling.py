"""Parent-owned, metadata-only run helper observations. Never executes helper code.

All portable descriptions are bounded symbolic labels, not free-form source or
human text. Source names are private inputs relative to an explicit source root.
Only the existing owning-spec artifact index is written. Capture is advisory:
call capture_best_effort at ordinary closure, independently of terminal gates.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat

import spec_artifacts

CATEGORIES = {'closure', 'scope', 'brief', 'monitoring', 'recovery', 'fixture', 'experiment', 'other'}
DISPOSITIONS = {'generic_candidate', 'project_local', 'experiment', 'existing_supported', 'defect_adapter'}
AVAILABILITY = {'available', 'not_retained', 'inaccessible', 'not_reported'}
TOKEN = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}\Z')
SENSITIVE = re.compile(r'(?i)(secret|password|credential|bearer|api[_-]?key|token[=:]|sk-|ghp_|https?://|\$|`|@|[;|&])')


class ToolingError(ValueError):
    """Invalid observation; error messages contain no caller input."""


def _require(condition, code='invalid_metadata'):
    if not condition:
        raise ToolingError(code)


def _label(value):
    _require(isinstance(value, str) and TOKEN.fullmatch(value) and not SENSITIVE.search(value))
    return value


def _ref(value):
    _require(isinstance(value, str) and 0 < len(value) <= 240 and '\\' not in value and not re.match(r'^[A-Za-z]:', value))
    parts = value.split('/')
    _require(all(p not in {'', '.', '..'} for p in parts))
    for p in parts:
        _label(p)
    return value


def _fields(obj, required, optional=()):
    _require(isinstance(obj, dict) and set(required) <= obj.keys() and obj.keys() <= set(required) | set(optional))


def _digest(value):
    _require(isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value))
    return value


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _identity(project, spec_id, run_id):
    for value in (project, spec_id, run_id):
        _label(value)
    _require(re.fullmatch(r'(?:SPEC|BUG|NFR|QUESTIONS)-[A-Z0-9-]+', spec_id))
    return dict(project=project, spec_id=spec_id, run_id=run_id)


def _read_source(root, relative):
    """Open exactly the declared regular file, without following any symlink."""
    _require(isinstance(relative, str) and '\\' not in relative and '\x00' not in relative)
    parts = relative.split('/')
    _require(all(p not in {'', '.', '..'} for p in parts), 'unsafe_source_path')
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        child = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(child, 'rb') as source:
            info = os.fstat(source.fileno())
            _require(stat.S_ISREG(info.st_mode), 'source_not_regular')
            _require(info.st_size <= 16 * 1024 * 1024, 'source_too_large')
            data = source.read(16 * 1024 * 1024 + 1)
            _require(len(data) <= 16 * 1024 * 1024, 'source_too_large')
            return hashlib.sha256(data).hexdigest(), len(data)
    finally:
        os.close(fd)


def _validate_review(review):
    if review == {'state': 'unreviewed'}:
        return
    _fields(review, {'state', 'disposition', 'comparison', 'rationale', 'contexts'}, {'eligible', 'corrective_spec'})
    _require(review['disposition'] in DISPOSITIONS)
    _ref(review['comparison'])
    _label(review['rationale'])
    contexts = review['contexts']
    _require(isinstance(contexts, list) and len(contexts) <= 20)
    projects = set()
    for context in contexts:
        _fields(context, {'project', 'evidence'}, {'sha256'})
        if 'sha256' in context:
            _digest(context['sha256'])
        projects.add(_label(context['project']))
        _ref(context['evidence'])
    if review['disposition'] == 'defect_adapter':
        _label(review.get('corrective_spec'))
    if 'eligible' in review:
        _require(review['disposition'] == 'generic_candidate' and len(projects) >= 2, 'second_context_required')
        value = review['eligible']
        _fields(value, {'owner_project', 'owner_spec', 'boundary', 'privacy', 'checks', 'write_surface', 'unresolved_decisions'})
        _label(value['owner_project'])
        _identity(value['owner_project'], value['owner_spec'], 'review')
        _fields(value['boundary'], {'inputs', 'outputs', 'side_effects', 'dependencies', 'compatibility'})
        for entries in [*value['boundary'].values(), value['checks'], value['write_surface']]:
            _require(isinstance(entries, list) and 0 < len(entries) <= 20)
            for entry in entries:
                _ref(entry)
        _require(value['privacy'] == 'metadata_only' and value['unresolved_decisions'] == [])
        _require(review['state'] == 'eligible')
    else:
        _require(review['state'] == ('proposed' if review['disposition'] == 'generic_candidate' else 'reviewed'))


def _validate(record):
    _fields(record, {'schema_version', 'project', 'spec_id', 'run_id', 'inventory_state', 'candidates'})
    _require(record['schema_version'] == 1)
    _identity(record['project'], record['spec_id'], record['run_id'])
    _require(record['inventory_state'] in {'reported', 'not_reported', 'none_authored'})
    _require(isinstance(record['candidates'], list) and len(record['candidates']) <= 200)
    _require(record['inventory_state'] == 'reported' or not record['candidates'])
    seen = set()
    for candidate in record['candidates']:
        _fields(candidate, {'candidate_id', 'source_project', 'source_spec', 'source_run', 'locator', 'category',
                            'availability', 'sha256', 'size_bytes', 'diagnostic', 'version', 'predecessor', 'review'})
        key = _label(candidate['candidate_id'])
        _require(key not in seen)
        seen.add(key)
        _identity(candidate['source_project'], candidate['source_spec'], candidate['source_run'])
        _ref(candidate['locator'])
        _require(candidate['category'] in CATEGORIES and candidate['availability'] in AVAILABILITY)
        if candidate['sha256'] is not None:
            _digest(candidate['sha256'])
            _require(type(candidate['size_bytes']) is int and candidate['size_bytes'] >= 0)
        else:
            _require(candidate['size_bytes'] is None and candidate['availability'] != 'available')
        _require(candidate['diagnostic'] in {None, 'source_missing', 'source_inaccessible', 'source_not_reported'})
        if candidate['predecessor'] is not None:
            _digest(candidate['predecessor'])
        _digest(candidate['version'])
        _require(candidate['version'] == _hash({k: candidate[k] for k in
                 ('candidate_id', 'source_project', 'source_spec', 'source_run', 'availability', 'sha256', 'size_bytes', 'predecessor')}))
        _validate_review(candidate['review'])


def list_records(reports_root, project, spec_id, run_id):
    identity = _identity(project, spec_id, run_id)
    state, entries, _ = spec_artifacts.read_index_state(Path(reports_root), spec_id)
    _require(state in {'available', 'missing', 'empty'}, 'artifact_index_unavailable')
    result = []
    for entry in entries:
        if not entry.get('path', '').split('/')[-1].startswith('run-tooling-'):
            continue
        payload = json.loads(spec_artifacts.read_indexed_artifact(Path(reports_root), spec_id, entry['path'])['content'])
        record = payload.get('run_tooling')
        _require(isinstance(record, dict))
        _validate(record)
        _require(payload.get('record_digest') == _hash(record), 'record_digest_mismatch')
        if all(record.get(k) == v for k, v in identity.items()):
            result.append({'record': record, 'artifact': entry['path']})
    return result


def _publish(reports_root, record):
    _validate(record)
    reports_root = Path(reports_root)
    for candidate in record['candidates']:
        if candidate['review']['state'] == 'eligible':
            _verify_contexts(reports_root, candidate['review']['contexts'])
    previous = list_records(reports_root, record['project'], record['spec_id'], record['run_id'])
    if previous and previous[-1]['record'] == record:
        return previous[-1]
    digest = _hash(record)
    filename = 'run-tooling-' + digest + '.json'
    directory = spec_artifacts.artifacts_dir(reports_root, record['spec_id'])
    index = spec_artifacts.index_path(reports_root, record['spec_id'])
    # Parent is the sole writer. Preserve prior index and remove only this operation's
    # newly created file if publication fails; other evidence is never rewritten.
    _require(not spec_artifacts._symlinked_index_component(reports_root, record['spec_id']), 'unsafe_artifact_path')
    before = index.read_bytes() if index.exists() else None
    target = directory / filename
    _require(not target.exists() and not target.is_symlink(), 'unindexed_record_exists')
    try:
        entry = spec_artifacts.write_artifact(reports_root, record['spec_id'], type='decision', actor='parent',
                    summary='Run tooling metadata observation', filename=filename,
                    content={'run_tooling': record, 'record_digest': digest})
    except Exception:
        target.unlink(missing_ok=True)
        if before is None:
            index.unlink(missing_ok=True)
        elif index.read_bytes() != before:
            temporary = index.with_suffix('.restore')
            temporary.write_bytes(before)
            temporary.replace(index)
        raise
    return {'record': record, 'artifact': entry['path']}


def capture(reports_root, project, spec_id, run_id, *, candidates=None, source_root=None, inventory_state=None):
    identity = _identity(project, spec_id, run_id)
    state = inventory_state or ('not_reported' if candidates is None else 'reported')
    record = dict(schema_version=1, **identity, inventory_state=state, candidates=[])
    _require(candidates is None or isinstance(candidates, list))
    _require(state == 'reported' or not candidates)
    previous = list_records(reports_root, project, spec_id, run_id)
    old = {c['candidate_id']: c for c in previous[-1]['record']['candidates']} if previous else {}
    for raw in candidates or []:
        _fields(raw, {'candidate_id', 'locator', 'category'}, {'source', 'availability', 'sha256', 'size_bytes', 'source_project', 'source_spec', 'source_run'})
        _label(raw['candidate_id'])
        _ref(raw['locator'])
        _require(raw['category'] in CATEGORIES)
        availability = raw.get('availability', 'not_reported')
        digest, size, diagnostic = raw.get('sha256'), raw.get('size_bytes'), 'source_not_reported'
        if digest is not None:
            _digest(digest)
            _require(type(size) is int and size >= 0)
        if 'source' in raw:
            _require(source_root is not None, 'source_root_required')
            try:
                observed_digest, observed_size = _read_source(source_root, raw['source'])
                _require(digest is None or (digest, size) == (observed_digest, observed_size), 'source_digest_mismatch')
                availability, digest, size, diagnostic = 'available', observed_digest, observed_size, None
            except FileNotFoundError:
                availability, diagnostic = 'not_retained', 'source_missing'
            except PermissionError:
                availability, diagnostic = 'inaccessible', 'source_inaccessible'
            except OSError as exc:
                if exc.errno in {40, 20, 62}:  # ELOOP / ENOTDIR, including macOS symlink errno
                    raise ToolingError('unsafe_source_path') from None
                availability, diagnostic = 'inaccessible', 'source_inaccessible'
        else:
            _require(availability != 'available', 'available_source_required')
            diagnostic = {'not_retained': 'source_missing', 'inaccessible': 'source_inaccessible',
                          'not_reported': 'source_not_reported'}.get(availability)
        candidate = dict(candidate_id=raw['candidate_id'], source_project=raw.get('source_project', project),
            source_spec=raw.get('source_spec', spec_id), source_run=raw.get('source_run', run_id), locator=raw['locator'], category=raw['category'], availability=availability,
            sha256=digest, size_bytes=size, diagnostic=diagnostic)
        former = old.get(raw['candidate_id'])
        identity_fields = ('candidate_id', 'source_project', 'source_spec', 'source_run',
                           'availability', 'sha256', 'size_bytes')
        if former and all(former[k] == candidate[k] for k in identity_fields):
            _require(all(former[k] == candidate[k] for k in candidate), 'conflicting_same_version_metadata')
            candidate = copy.deepcopy(former)
        else:
            candidate['predecessor'] = former['version'] if former else None
            candidate['version'] = _hash({k: candidate[k] for k in (*identity_fields, 'predecessor')})
            candidate['review'] = {'state': 'unreviewed'}
        record['candidates'].append(candidate)
    record['candidates'].sort(key=lambda c: c['candidate_id'])
    return _publish(reports_root, record)


def capture_best_effort(*args, **kwargs):
    """No terminal result or cleanup eligibility is accepted, inspected or modified."""
    try:
        return {'ok': True, **capture(*args, **kwargs)}
    except Exception:
        return {'ok': False, 'diagnostic': 'capture_unavailable'}


def review(reports_root, project, spec_id, run_id, *, candidate_id, disposition, comparison, rationale,
           contexts, eligible=None, corrective_spec=None):
    _label(candidate_id)
    history = list_records(reports_root, project, spec_id, run_id)
    _require(bool(history), 'capture_required')
    record = copy.deepcopy(history[-1]['record'])
    candidate = next((c for c in record['candidates'] if c['candidate_id'] == candidate_id), None)
    _require(candidate is not None, 'candidate_missing')
    value = dict(state='eligible' if eligible is not None else
                 ('proposed' if disposition == 'generic_candidate' else 'reviewed'),
                 disposition=disposition, comparison=comparison, rationale=rationale, contexts=contexts)
    if eligible is not None:
        value['eligible'] = eligible
    if corrective_spec is not None:
        value['corrective_spec'] = corrective_spec
    _validate_review(value)
    candidate['review'] = value
    return _publish(reports_root, record)




def _verify_contexts(reports_root, contexts):
    for context in contexts:
        _digest(context.get('sha256'))
        try:
            digest, _ = _read_source(reports_root, context['evidence'])
        except (OSError, ToolingError):
            raise ToolingError('context_evidence_unavailable') from None
        _require(digest == context['sha256'], 'context_evidence_digest_mismatch')


def propose_draft(reports_root, project, spec_id, run_id, *, candidate_id, specs_dir, title,
                  dry_run=True, registry_path=None):
    """Recommend a separate draft; only an explicit dry_run=False authors a new spec.

    Dry runs retain the proposed Markdown and authored decision as metadata, with
    no ID reservation. Existing specs, status checkpoints and release state are
    never changed. All candidates still need ordinary implementation/release gates.
    """
    import check_followup_spec
    import lifecycle
    import yaml
    from datetime import datetime, timezone

    _require(type(dry_run) is bool)
    _label(candidate_id)
    _require(isinstance(title, str) and 0 < len(title) <= 160)
    _require(not re.match(r'(?i)^(python[0-9.]*|bash|sh|curl|wget|sudo|git|uv|pip|node|aider|lms)\b', title), 'command_not_metadata')
    for word in title.split():
        _label(word)
    history = list_records(reports_root, project, spec_id, run_id)
    _require(bool(history), 'capture_required')
    candidate = next((c for c in history[-1]['record']['candidates'] if c['candidate_id'] == candidate_id), None)
    _require(candidate is not None and candidate['review']['state'] == 'eligible', 'eligible_review_required')
    _verify_contexts(Path(reports_root), candidate['review']['contexts'])
    contract = candidate['review']['eligible']
    boundary = contract['boundary']
    requirements = ['Provide ' + name + ': ' + ', '.join(values) + '.' for name, values in boundary.items()]
    criteria = ['Verify ' + name + '.' for name in contract['checks']]
    body = '\n'.join(requirements + criteria)
    code, gate = check_followup_spec.check(title, Path(specs_dir), None, None, None, 0.5,
                        suggestion_body=body, registry_path=registry_path)
    if code == 1:
        return {'status': 'existing', 'existing_specs': sorted({c['spec_id'] for c in gate['conflicts']}),
                'source_backlink': dict(project=project, spec_id=spec_id, run_id=run_id,
                                        candidate_id=candidate_id, version=candidate['version'])}
    _require(code == 0 and gate.get('status') == 'clean', 'followup_gate_unavailable')
    proposed = _label(gate['proposed_id'])
    backlink = dict(project=project, spec_id=spec_id, run_id=run_id, candidate_id=candidate_id, version=candidate['version'])
    proposal_key = _hash(dict(source=backlink, title=title, contract=contract, proposed_id=proposed, dry_run=dry_run))
    filename = 'tooling-proposal-' + proposal_key + '.json'
    root = Path(reports_root)
    key = 'artifacts/' + filename
    if any(e.get('path') == key for e in spec_artifacts.read_index(root, spec_id)):
        data = json.loads(spec_artifacts.read_indexed_artifact(root, spec_id, key)['content'])
        return data['proposal_result']
    reason = 'Accepted metadata-only reuse recommendation; implementation and whole-kit release remain separately gated.'
    frontmatter = dict(id=proposed, template_version=12, priority=5, layer=1, type='feature', status='draft',
        after=[], requires_specs=[], touches=contract['write_surface'], scope={'write': contract['write_surface'], 'read': 'unrestricted'},
        created=datetime.now(timezone.utc).date().isoformat(), stack='python', domain='tooling', output_type='mixed',
        devkb_required=['python.md', 'testing.md', 'architecture.md'], prior_attempts=[], nfrs=[],
        real_use_evidence={'policy': 'required_before_done'})
    markdown = '---\n' + yaml.safe_dump(frontmatter, sort_keys=False) + '---\n\n# ' + title
    markdown += '\n\n## Problem\n\nBounded reusable capability proposed by ' + spec_id + ' candidate ' + candidate_id + '.'
    markdown += '\n\n## Requirements\n\n' + '\n'.join('- [ ] R%d: %s' % (i, text) for i, text in enumerate(requirements, 1))
    markdown += '\n\n## Acceptance Criteria\n\n' + '\n'.join('- [ ] AC%d: %s' % (i, text) for i, text in enumerate(criteria, 1))
    markdown += '\n\n## Live Execution Checklist\n\n- [ ] LE1: Retain one ordinary use of the bounded capability; no manufactured run.\n'
    markdown += '\n## Out of Scope\n\nExecuting or copying captured source, installation, release and changes to existing lifecycle authority.\n'
    markdown += '\n## Context\n\nSource backlink: ' + project + '/' + spec_id + '/' + run_id + '/' + candidate_id + '.\n'
    markdown += '\n## Gap Protocol\n\nReview active NFR and managed release obligations before promotion; source recommendation grants no implementation authority.\n'
    result = dict(status='draft_proposal' if dry_run else 'draft_authored', proposed_id=proposed, artifact=key)
    decision = lifecycle.decision_record(trigger='state_rationale_authoring', current_state='draft', candidates=['draft'],
                    reason=reason, findings=['eligible-candidate-review'], resolution=reason, rationale=reason, authority='parent')
    if not dry_run:
        directory = Path(specs_dir)
        _require(directory.is_dir() and not directory.is_symlink(), 'unsafe_specs_directory')
        _require(spec_artifacts.reports_root_for_spec_path(directory / 'placeholder.md').resolve() == root.resolve(), 'draft_report_root_mismatch')
        target = directory / (proposed + '-run-tooling.md')
        _require(not (root / proposed).exists(), 'draft_report_already_exists')
        with target.open('x', encoding='utf-8') as stream:
            stream.write(markdown)
        spec_artifacts.record_authoring_decision(target, status='draft', reason=reason, actor='parent',
                    reconsider_when='Owner commissions the separately reviewed capability implementation.',
                    evidence=[{'kind': 'spec', 'id': spec_id}])
    spec_artifacts.write_artifact(root, spec_id, type='decision', actor='parent',
        summary='Run tooling separate draft recommendation', filename=filename,
        content={'decision': decision, 'source_backlink': backlink, 'draft_markdown': markdown,
                 'proposal_result': result, 'gate_status': 'clean', 'id_reserved': not dry_run})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['capture', 'review', 'list'])
    parser.add_argument('--reports-root', type=Path, required=True)
    parser.add_argument('--project', required=True)
    parser.add_argument('--spec-id', required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--input', type=Path, help='Explicit JSON metadata; never helper source')
    parser.add_argument('--source-root', type=Path)
    args = parser.parse_args(argv)
    kwargs = dict(reports_root=args.reports_root, project=args.project, spec_id=args.spec_id, run_id=args.run_id)
    try:
        if args.operation == 'list':
            result = list_records(**kwargs)
        else:
            data = json.loads(args.input.read_text()) if args.input else {}
            _require(isinstance(data, dict))
            if args.operation == 'capture':
                result = capture_best_effort(**kwargs, source_root=args.source_root, **data)
            elif set(data) == {'proposal'}:
                result = propose_draft(**kwargs, **data['proposal'])
            else:
                result = review(**kwargs, **data)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({'ok': False, 'diagnostic': 'capture_unavailable' if args.operation == 'capture' else 'invalid_metadata'}))
        return 0 if args.operation == 'capture' else 2


if __name__ == '__main__':
    raise SystemExit(main())
