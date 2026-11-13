"""Bounded, owner-approved unfinished-spec replacement (SPEC-NS-KIT-184).

This is an administrative operation of the existing coordinator, never a runner.
Plans are data; an indexed owner decision grants authority over exact bytes. Drafts
remain held for a separate readiness review even after application reconciles.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

import board_ctl
import check_followup_spec
import lifecycle
import spec_artifacts
from spec_frontmatter import load_attempts_history, parse_spec_file
from status_store import StatusStore, StatusStoreError
import status_transition
import verification_report
import yaml


class ReplacementError(ValueError):
    """Refusal or a retained, reconciliation-required administrative operation."""


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, default=str).encode()).hexdigest()


def _file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _need(condition: Any, message: str) -> None:
    if not condition:
        raise ReplacementError(message)


def _path(root: Path, relative: str) -> Path:
    p = root / relative
    _need(not Path(relative).is_absolute() and '..' not in Path(relative).parts,
          'non-relative evidence or output path')
    _need(not any(q.is_symlink() for q in [p, *p.parents] if q != root.parent),
          'symlinked evidence or output path')
    _need(p.resolve().is_relative_to(root.resolve()), 'path outside project root')
    return p


def _contract(path: Path) -> str:
    parsed = parse_spec_file(path)
    fm = {k: v for k, v in parsed.frontmatter.items() if k != 'status'}
    body = re.sub(r'(?ms)^## State rationale\n.*?(?=^## |\Z)', '', parsed.body)
    return digest({'frontmatter': fm, 'body': body.strip()})


def obligations(path: Path) -> dict[str, dict]:
    """Every checkbox in the source contract, plus each bound NFR, is owned."""
    parsed = parse_spec_file(path)
    result = {}
    section = ''
    counts: dict[str, int] = {}
    for line in parsed.body.splitlines():
        if line.startswith('## '):
            section = line[3:].strip()
        match = re.match(r'^\s*- \[([ xX])\] (.+)$', line)
        if not match or section in {'State rationale', 'Scope Amendments'}:
            continue
        text = match[2]
        explicit = re.match(r'((?:R|AC|LE|M)\d+)\b', text)
        counts[section] = counts.get(section, 0) + 1
        key = explicit[1] if explicit else f'{section}:{counts[section]}'
        _need(key not in result, 'ambiguous source obligation identity')
        result[key] = {'kind': section, 'text': text, 'completed': match[1].lower() == 'x'}
    for nfr in parsed.frontmatter.get('nfrs', []):
        result['nfr:' + nfr] = {'kind': 'NFR', 'text': nfr, 'completed': False}
    _need(result, 'empty source contract')
    return result


def _pins(root: Path, paths: list[str]) -> dict[str, str]:
    return {name: _file(_path(root, name)) for name in paths}


def _cost(cost: dict, children: list[dict]) -> dict:
    components = ['implementation', 'verification', 'setup', 'overhead']
    def total(row):
        values = [row.get(k) for k in components]
        _need(all(v is None or (type(v) in (float, int) and v >= 0) for v in values),
              'cost must be nonnegative or unknown/null')
        return None if None in values else sum(values)
    old = total(cost['continue'])
    child_totals = [total(c['cost']) for c in children]
    shared = cost.get('shared_gate_saving')
    _need(shared is None or (type(shared) in (int, float) and shared >= 0), 'invalid shared gate saving')
    replacement = None if shared is None or None in child_totals else sum(child_totals) - shared
    _need(replacement is None or replacement >= 0, 'shared saving exceeds total burden')
    return {'continue': old, 'replacement': replacement,
            'benefit': 'unknown' if old is None or replacement is None else
            ('estimated' if replacement < old else 'not_established'),
            'basis': 'remaining implementation + verification + setup + per-child overhead - shared gates',
            'estimates': cost, 'child_estimates': [c['cost'] for c in children]}



def _validate_mapping(root: Path, source: dict, owned: dict, mappings: list[dict],
                      children: list[dict], pins: dict) -> None:
    keys = [m.get('obligation') for m in mappings]
    _need(len(keys) == len(set(keys)) and set(keys) == set(owned), 'omitted or double-owned obligation')
    targets = {}
    for child in children:
        identifiers = {re.match(r'([A-Z]+\d+)\b', text)[1] for text in
                       child['requirements'] + child['acceptance_criteria'] + child.get('manual', [])
                       if re.match(r'([A-Z]+\d+)\b', text)}
        targets[child['key']] = identifiers | {'nfr:' + n for n in child['nfrs']}
    _need(len(targets) == len(children), 'ambiguous replacement keys')
    for mapping in mappings:
        mode = mapping.get('disposition')
        _need(mode in {'replacement', 'completed', 'retired'}, 'unknown obligation disposition')
        obligation = mapping['obligation']
        if mode == 'replacement':
            _need(mapping.get('child') in targets and mapping.get('target') in targets[mapping['child']],
                  'missing replacement target or owner')
        elif mode == 'retired':
            _need(mapping.get('rationale') and mapping.get('owner_authorization'), 'unapproved retirement')
            record = _indexed(root, source, mapping['owner_authorization'], 'decision')
            _need(record.get('actor', '').startswith('human:') and
                  record.get('retirement') == {'obligation': obligation, 'source_sha256': source['sha256'],
                                               'rationale': mapping['rationale']}, 'unapproved retirement')
        else:
            _need(owned[obligation]['completed'], 'unsupported completed proof for unmet obligation')
            proof = mapping.get('proof', {})
            name = proof.get('path', '')
            _need(name in pins and proof.get('sha256') == pins[name], 'invented completed evidence')
            raw = json.loads(_path(root, name).read_text())
            _need(raw.get('type') in {'verifier', 'validation-evidence'}, 'unsupported completed proof type')
            record = _indexed(root, source, name, raw['type'])
            scope = proof.get('reuse_scope')
            _need(record.get('status') == 'pass' and obligation in record.get('obligations', []) and
                  record.get('contract_sha256') == source['contract_sha256'] and
                  scope and record.get('reuse_scope') == scope, 'unsupported completed proof reuse scope')
            identity = {'selection': 'full', 'contract_sha256': source['contract_sha256'], 'scope': scope}
            receipt = record.get('original_receipt')
            decision = verification_report.reuse_decision(receipt, identity, now=datetime.now(timezone.utc))
            _need(decision['reuse'] and receipt['counts'].get('pass') == len(receipt['tests']) and
                  receipt.get('native_result', {}).get('exit_code') == 0,
                  'original proof receipt cannot be reused: ' + decision['reason'])


def _gate(child: dict, specs: Path, source_id: str, registry: Path | None) -> str:
    code, result = check_followup_spec.check(child['title'], specs, None, child.get('domain'),
        child.get('layer', 1), 0.6, parent_id=source_id,
        suggestion_body='\n'.join(child['requirements'] + child['acceptance_criteria']),
        source_spec_id=source_id, registry_path=registry)
    _need(code == 0, 'ID/duplicate gate refused: ' + json.dumps(result))
    return result['proposed_id']


def _draft(child: dict, plan: dict) -> str:
    fm = {'id': child['id'], 'template_version': 12, 'type': 'feature', 'status': 'draft',
          'layer': child.get('layer', 1), 'priority': child.get('priority', 3),
          'created': plan['created'], 'after': child['after'], 'nfrs': child['nfrs'],
          'scope': {'write': child['scope']}, 'touches': child['scope'],
          'prior_attempts': plan['lineage']['attempts'],
          'replacement_source': plan['source']['id'], 'replacement_plan': plan['digest'],
          'promotion_gap': {'kind': 'awaiting_external_precondition',
                            'reason': 'Replacement plan must reconcile, then owner reviews independent draft readiness.'}}
    def section(name, lines):
        return '\n## ' + name + '\n\n' + '\n'.join('- [ ] ' + s for s in lines) + '\n'
    return ('---\n' + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True) + '---\n\n# ' +
            child['id'] + ' — ' + child['title'] + '\n' + section('Requirements', child['requirements']) +
            section('Acceptance Criteria', child['acceptance_criteria']) +
            section('Manual obligations', child.get('manual', [])) + '\n## Context\n\n' +
            child['boundary'] + '\n\nSource: ' + plan['source']['path'] + '\nPlan: ' + plan['digest'] +
            '\nRetained lineage: ' + json.dumps(plan['lineage'], ensure_ascii=False) + '\n')


def prepare(source: Path, proposal: dict, *, root: Path, store: StatusStore,
            registry_path: Path | None = None) -> dict:
    """Prepare only data; no spec, lifecycle, dependent or registry writes."""
    root = root.resolve(); source = source.resolve()
    _need(source.is_relative_to(root), 'source outside root')
    fm = parse_spec_file(source).frontmatter
    _need(fm.get('status') not in lifecycle.terminal_statuses(), 'completed source history is immutable')
    _need(proposal.get('trigger') in {'owner_request', 'ac_cost_review'}, 'replacement trigger missing')
    _need(proposal.get('reason'), 'replacement reason missing')
    owned = obligations(source)
    mappings = proposal.get('mappings', [])
    keys = [m.get('obligation') for m in mappings]
    _need(len(keys) == len(set(keys)) and set(keys) == set(owned), 'omitted or double-owned obligation')
    children = copy.deepcopy(proposal.get('children', []))
    _need(0 < len(children) <= 8, 'replacement child bound is 1..8')
    names = [c.get('key') for c in children]
    _need(len(set(names)) == len(names) and all(names), 'ambiguous replacement keys')
    pins = _pins(root, proposal.get('retained_evidence', []))
    reports = spec_artifacts.reports_root_for_spec_path(source)
    original_index = spec_artifacts.read_index(reports, fm['id'])
    for entry in original_index:
        retained = reports / fm['id'] / entry['path']
        name = retained.relative_to(root).as_posix()
        pins[name] = _file(_path(root, name))
    for nfr in fm.get('nfrs', []):
        matches = [p for p in source.parent.glob('*.md') if parse_spec_file(p).frontmatter.get('id') == nfr]
        _need(len(matches) == 1 and parse_spec_file(matches[0]).frontmatter.get('status') == 'active',
              'bound NFR missing or inactive')
        pins[matches[0].relative_to(root).as_posix()] = _file(matches[0])
    archive = source.with_suffix('.attempts-archive.json')
    if archive.exists(): pins[archive.relative_to(root).as_posix()] = _file(archive)
    for m in mappings:
        mode = m.get('disposition')
        _need(mode in {'replacement', 'completed', 'retired'}, 'unknown obligation disposition')
        if mode == 'replacement':
            _need(m.get('child') in names and m.get('target'), 'missing replacement owner')
        elif mode == 'retired':
            _need(m.get('rationale') and m.get('owner_authorization'), 'unapproved retirement')
            record = _indexed(root, {'path': source.relative_to(root).as_posix(), 'id': fm['id']},
                              m['owner_authorization'], 'decision')
            _need(record.get('type') == 'decision' and record.get('actor', '').startswith('human:') and
                  record.get('retirement', {}).get('obligation') == m['obligation'] and
                  record['retirement'].get('source_sha256') == _file(source) and
                  record['retirement'].get('rationale') == m['rationale'], 'unapproved retirement')
            pins[m['owner_authorization']] = _file(_path(root, m['owner_authorization']))
        else:
            proof = m.get('proof', {})
            _need(owned[m['obligation']]['completed'], 'unsupported completed proof for unmet obligation')
            path = proof.get('path', '')
            _need(path in pins and proof.get('sha256') == pins[path], 'invented completed evidence')
            raw_record = json.loads(_path(root, path).read_text())
            record = _indexed(root, {'path': source.relative_to(root).as_posix(), 'id': fm['id']},
                              path, raw_record.get('type'))
            _need(record.get('type') in {'verifier', 'validation-evidence'} and
                  record.get('status') == 'pass' and m['obligation'] in record.get('obligations', []) and
                  record.get('contract_sha256') == _contract(source) and
                  record.get('reuse_scope') == proof.get('reuse_scope') and proof.get('reuse_scope'),
                  'unsupported completed proof reuse scope')
    dependents = {}
    for p in source.parent.glob('*.md'):
        other = parse_spec_file(p).frontmatter
        if fm['id'] in other.get('after', []):
            dependents[other['id']] = {'path': p.relative_to(root).as_posix(), 'sha256': _file(p)}
    _need(set(proposal.get('dependents', {})) == set(dependents), 'dependent dispositions missing')
    _need(all(v.get('action') == 'retain_edge_owner_followup' and v.get('reason')
              for v in proposal.get('dependents', {}).values()), 'unsupported dependent disposition')
    _need(proposal.get('release', {}).get('action') in {'retain_source_declaration', 'explicit_owner_followup'}
          and proposal['release'].get('reason'), 'release disposition missing')
    with tempfile.TemporaryDirectory(prefix='ns-replacement-') as directory:
        virtual = Path(directory)
        for p in source.parent.glob('*.md'):
            (virtual / p.name).write_bytes(p.read_bytes())
        for child in children:
            _need(child.get('requirements') and child.get('acceptance_criteria') and
                  child.get('boundary') and child.get('scope') and isinstance(child.get('after'), list) and
                  isinstance(child.get('nfrs'), list), 'child contract or boundary incomplete')
            _need(len(child['requirements']) + len(child['acceptance_criteria']) <= 32, 'child contract unbounded')
            child['id'] = _gate(child, virtual, fm['id'], registry_path)
            targets = {re.match(r'([A-Z]+\d+)\b', x)[1] for x in
                       child['requirements'] + child['acceptance_criteria'] + child.get('manual', [])
                       if re.match(r'([A-Z]+\d+)\b', x)} | {'nfr:' + n for n in child['nfrs']}
            claimed = {m['target'] for m in mappings if m.get('child') == child['key']}
            _need(claimed <= targets and claimed, 'replacement target missing or empty source boundary')
            _need(not any(a in names for a in child['after']), 'child dependencies must use spec IDs')
            (virtual / (child['id'] + '.md')).write_text('---\n' + yaml.safe_dump(
                {'id': child['id'], 'status': 'draft'}) + '---\n# ' + child['title'] + '\n')
    state = store.get_state(fm['id'])
    _need(state is None or state['status'] == fm['status'], 'stale source/status')
    history = store.get_state_history(fm['id'])
    plan = {'schema_version': 1, 'created': proposal.get('created') or date.today().isoformat(),
            'source': {'id': fm['id'], 'path': source.relative_to(root).as_posix(),
                       'sha256': _file(source), 'contract_sha256': _contract(source),
                       'status': fm['status'], 'checkpoint': state, 'artifact_index': original_index},
            'trigger': proposal['trigger'], 'reason': proposal['reason'], 'obligations': owned,
            'mappings': mappings, 'children': children, 'retained_evidence': pins,
            'lineage': {'source': fm['id'], 'attempts': load_attempts_history(source), 'run_history': history,
                        'spend': proposal.get('cumulative_spend')},
            'dependents': dependents, 'dependent_dispositions': proposal['dependents'],
            'release_disposition': proposal['release'], 'shared_verification': proposal.get('shared_verification', []),
            'cost_comparison': _cost(proposal['cost'], children)}
    _validate_mapping(root, plan['source'], owned, mappings, children, pins)
    plan['digest'] = digest(plan)
    return plan


def _json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(value, f, indent=2, ensure_ascii=False, default=str); f.write('\n'); f.flush(); os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def _indexed(root: Path, source: dict, name: str, kind: str) -> dict:
    path = _path(root, name)
    reports = spec_artifacts.reports_root_for_spec_path(_path(root, source['path']))
    entries = spec_artifacts.read_index(reports, source['id'])
    indexed = [e for e in entries if (reports / source['id'] / e['path']).resolve() == path.resolve()
               and e['type'] == kind]
    _need(len(indexed) == 1, 'authority/closure record must be indexed exactly once')
    record = json.loads(path.read_text())
    _need(record.get('type') == kind and record.get('spec_id') == source['id'], 'authority identity mismatch')
    return record


def apply(plan: dict, *, root: Path, store: StatusStore, authorization: str,
          owner_guard: Callable[[], None] | None = None, interrupt_after: str | None = None) -> dict:
    """Run within the parent's existing sole-owner boundary, never acquire a new one.

    CLI and API run within the existing parent-owned operator/coordinator invocation.
    An optional additional owner_guard cannot replace indexed exact-plan authority.
    Internal supported-API failure leaves a pending journal for reconciliation.
    """
    root = root.resolve(); source = plan['source']; path = _path(root, source['path'])
    _need(plan.get('schema_version') == 1 and digest({k: v for k, v in plan.items() if k != 'digest'}) == plan.get('digest'),
          'changed or unsupported prepared plan')
    authority = _indexed(root, source, authorization, 'decision')
    binding = authority.get('replacement_authorization', {})
    _need(authority.get('actor', '').startswith('human:') and binding.get('plan_digest') == plan['digest'] and
          binding.get('source') == source and binding.get('retirements') ==
          [m for m in plan['mappings'] if m['disposition'] == 'retired'] and
          binding.get('dependent_dispositions') == plan['dependent_dispositions'] and
          binding.get('release_disposition') == plan['release_disposition'], 'missing/stale owner authorization')
    closure_name = binding.get('closure_record')
    _need(closure_name, 'actual owned operation closure evidence required')
    _need(binding.get('owner_run') and binding.get('closure_sha256') == _file(_path(root, closure_name)),
          'stale closure authority')
    closure = _indexed(root, source, closure_name, 'context').get('ownership', {})
    _need(closure.get('owner_run') == binding.get('owner_run') and
          closure.get('source_checkpoint') == source['checkpoint'] and
          closure.get('process_state') in {'none_running', 'confirmed_stopped'} and
          closure.get('operations_closed') is True and isinstance(closure.get('processes'), list),
          'still-active or unknown owned operations')
    for pid in closure['processes']:
        _need(type(pid) is int and pid > 0, 'invalid owned process identity')
        try: os.kill(pid, 0)
        except ProcessLookupError: pass
        else: raise ReplacementError('owned process still active')
    reports = spec_artifacts.reports_root_for_spec_path(path)
    journal_path = reports / source['id'] / 'replacement' / plan['digest'] / 'journal.json'
    sealed_path = journal_path.with_name('plan.json')
    auth_hash = _file(_path(root, authorization)); closure_hash = _file(_path(root, closure_name))
    journal = json.loads(journal_path.read_text()) if journal_path.exists() else None
    if journal:
        _need(json.loads(sealed_path.read_text()) == plan and journal['authorization_sha256'] == auth_hash and
              journal['closure_sha256'] == closure_hash, 'journal/authority drift: reconciliation required')
    run_id = 'replacement-' + plan['digest'][:20]
    def guard():
        if owner_guard is not None: owner_guard()
        _indexed(root, source, authorization, 'decision')
        _indexed(root, source, closure_name, 'context')
        retained_index = spec_artifacts.read_index(reports, source['id'])
        _need(retained_index[:len(source['artifact_index'])] == source['artifact_index'],
              'retained source artifact index changed')
        _need(_file(_path(root, authorization)) == auth_hash and _file(_path(root, closure_name)) == closure_hash,
              'authority/closure changed')
        for name, pinned in plan['retained_evidence'].items():
            _need(_file(_path(root, name)) == pinned, 'retained evidence changed')
        for value in plan['dependents'].values():
            _need(_file(_path(root, value['path'])) == value['sha256'], 'dependent revision changed')
        _need(_contract(path) == source['contract_sha256'], 'source contract changed')
        _validate_mapping(root, source, plan['obligations'], plan['mappings'], plan['children'], plan['retained_evidence'])
        current = store.get_state(source['id'])
        superseding = current and current.get('status') == 'superseded' and current.get('run_id') == run_id and \
                      current.get('payload', {}).get('replacement_plan') == plan['digest']
        _need(current == source['checkpoint'] or superseding, 'stale source/status checkpoint')
        fm = parse_spec_file(path).frontmatter
        _need(fm.get('id') == source['id'], 'source identity changed')
        _need(fm['status'] == source['status'] or (superseding and fm['status'] == 'superseded'), 'stale source status')
        if not superseding:
            _need(_file(path) == source['sha256'], 'source revision changed')
        elif _file(path) != source['sha256']:
            quality, rationale = spec_artifacts.parse_rationale_section(parse_spec_file(path).body)
            _need(quality == 'present' and rationale.get('status') == 'superseded' and
                  rationale.get('reason') == plan['reason'] and rationale.get('record'),
                  'competing source rationale revision')
            transition = _indexed(root, source,
                (reports / source['id'] / rationale['record']).relative_to(root).as_posix(), 'status-transition')
            _need(transition.get('run_id') == run_id and transition.get('from') == source['status'] and
                  transition.get('to') == 'superseded' and transition.get('reason') == plan['reason'] and
                  lifecycle.state_rationale_snapshots_equal(rationale, transition.get('state_rationale', {})),
                  'source rationale is not this attributed transition')
        return current
    current = guard()
    _need(0 < len(plan['children']) <= 8, 'replacement child bound is 1..8')
    _need(obligations(path) == plan['obligations'], 'prepared obligations no longer match source')
    _need(_cost(plan['cost_comparison']['estimates'], plan['children']) == plan['cost_comparison'],
          'prepared cost comparison changed')
    keys = [m.get('obligation') for m in plan['mappings']]
    _need(len(keys) == len(set(keys)) and set(keys) == set(plan['obligations']), 'invalid prepared mapping')
    _validate_mapping(root, source, plan['obligations'], plan['mappings'], plan['children'], plan['retained_evidence'])
    _need(lifecycle.transition_allowed(source['status'], 'superseded'), 'active source must settle before replacement')
    if journal and journal['status'] == 'applied':
        _need(current and current['status'] == 'superseded' and parse_spec_file(path).frontmatter['status'] == 'superseded',
              'applied journal no longer reconciles')
        for name, pin in journal['outputs'].items(): _need(_file(_path(root, name)) == pin, 'applied draft changed')
        return journal
    if not journal:
        _json_atomic(sealed_path, plan)
        journal = {'schema_version': 1, 'plan_digest': plan['digest'], 'status': 'pending/reconciliation-required',
                   'authorization_sha256': auth_hash, 'closure_sha256': closure_hash, 'steps': [], 'outputs': {}}
        _json_atomic(journal_path, journal)
    def checkpoint(step):
        if step not in journal['steps']: journal['steps'].append(step)
        _json_atomic(journal_path, journal)
        if interrupt_after == step: raise ReplacementError('interrupted: pending/reconciliation-required at ' + step)
    checkpoint('journal')
    guard()
    artifact_name = 'replacement-plan-' + plan['digest'] + '.json'
    artifact_path = reports / source['id'] / 'artifacts' / artifact_name
    if 'plan-artifact' not in journal['steps']:
        if artifact_path.exists():
            recorded = _indexed(root, source, artifact_path.relative_to(root).as_posix(), 'context')
            _need(recorded.get('replacement_plan') == plan, 'plan artifact drift: reconcile')
        else:
            spec_artifacts.write_artifact(reports, source['id'], type='context', actor='coordinator',
                summary='Approved replacement plan: ' + plan['reason'], filename=artifact_name,
                content={'replacement_plan': plan, 'journal': journal_path.relative_to(root).as_posix()})
        checkpoint('plan-artifact')
    for child in plan['children']:
        guard()
        child_path = path.parent / (child['id'] + '.md')
        step = 'draft:' + child['id']
        if step in journal['steps']:
            _need(_file(child_path) == journal['outputs'][child_path.relative_to(root).as_posix()], 'draft revision changed')
            continue
        if child_path.exists():
            fm = parse_spec_file(child_path).frontmatter
            _need(fm.get('replacement_plan') == plan['digest'] and fm.get('status') == 'draft', 'draft ID collision')
            _need(_contract(child_path) == journal.get('draft_contracts', {}).get(child['id']), 'unrecorded draft: reconcile')
        else:
            # Revalidate minted ID against all already authored children; no new identity.
            minted = _gate(child, path.parent, source['id'], None)
            _need(minted == child['id'], 'minted draft identity became stale')
            with child_path.open('x') as f: f.write(_draft(child, plan))
            journal.setdefault('draft_contracts', {})[child['id']] = _contract(child_path)
            _json_atomic(journal_path, journal)
        quality, rationale = spec_artifacts.parse_rationale_section(parse_spec_file(child_path).body)
        if quality == 'absent' or (quality == 'present' and not rationale.get('record')):
            spec_artifacts.record_authoring_decision(child_path, status='draft', actor=authority['actor'],
                reason='Approved replacement draft; independent readiness remains unreviewed.',
                reconsider_when='Parent reconciles this plan and owner reviews child readiness.',
                evidence=[{'kind': 'file', 'path': sealed_path.relative_to(root).as_posix()}])
        journal['outputs'][child_path.relative_to(root).as_posix()] = _file(child_path)
        checkpoint(step)
    guard()
    if 'superseded' not in journal['steps']:
        if parse_spec_file(path).frontmatter['status'] != 'superseded':
            reason = status_transition.gate_status_write(parse_spec_file(path).frontmatter, 'superseded',
                reason=plan['reason'], specs_dir=path.parent, canonical_dir=path.parent.parent)
            store.transition_commit_backed(path, 'superseded', run_id=run_id, source='coordinator',
                reason=reason, before_administrative_write=guard,
                extra_payload={'replacement_plan': plan['digest'], 'replacements': [c['id'] for c in plan['children']],
                               'dependent_dispositions': plan['dependent_dispositions'],
                               'release_disposition': plan['release_disposition'], 'lineage': plan['lineage']})
        checkpoint('superseded')
    guard()
    if 'metadata-commit' not in journal['steps']:
        paths = [path, reports / source['id']]
        for child in plan['children']: paths += [path.parent / (child['id'] + '.md'), reports / child['id']]
        relative = [p.relative_to(root).as_posix() for p in paths]
        changed = board_ctl._changed(root, relative)
        if changed:
            result = board_ctl._git(root, 'add', '--', *changed)
            _need(result.returncode == 0, 'metadata staging failed: reconciliation required')
            result = board_ctl._git(root, 'commit', '-q', '-m', '[' + source['id'] + '] chore: apply approved replacement plan',
                                    '--', *changed)
            _need(result.returncode == 0, 'metadata commit failed: reconciliation required: ' + result.stderr)
        journal['metadata_commit'] = board_ctl._git(root, 'rev-parse', 'HEAD').stdout.strip()
        checkpoint('metadata-commit')
    guard()
    for name, pin in journal['outputs'].items(): _need(_file(_path(root, name)) == pin, 'draft changed before reconciliation')
    for p in [path, *[path.parent / (c['id'] + '.md') for c in plan['children']]]:
        committed = board_ctl._git(root, 'show', journal['metadata_commit'] + ':' + p.relative_to(root).as_posix())
        _need(committed.returncode == 0 and committed.stdout == p.read_text(),
              'metadata commit identity mismatch: reconciliation required')
    journal['status'] = 'applied'
    _json_atomic(journal_path, journal)
    checkpoint('reconciled')
    return journal


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    prep = sub.add_parser('prepare'); prep.add_argument('source'); prep.add_argument('proposal'); prep.add_argument('--root', required=True)
    prep.add_argument('--output', required=True)
    applying = sub.add_parser('apply'); applying.add_argument('plan'); applying.add_argument('--root', required=True)
    applying.add_argument('--authorization', required=True)
    args = parser.parse_args(argv)
    try:
        root = Path(args.root).resolve()
        if args.operation == 'prepare':
            source = _path(root, args.source)
            plan = prepare(source, json.loads(Path(args.proposal).read_text()), root=root,
                           store=StatusStore.for_specs_dir(source.parent))
            _json_atomic(Path(args.output), plan); print(json.dumps({'plan_digest': plan['digest'], 'output': args.output}))
        else:
            plan = json.loads(Path(args.plan).read_text())
            source = _path(root, plan['source']['path'])
            result = apply(plan, root=root, store=StatusStore.for_specs_dir(source.parent),
                           authorization=args.authorization)
            print(json.dumps(result))
        return 0
    except (ReplacementError, StatusStoreError, OSError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({'status': 'refused/reconciliation-required', 'reason': str(exc)})); return 1


if __name__ == '__main__':
    raise SystemExit(main())
