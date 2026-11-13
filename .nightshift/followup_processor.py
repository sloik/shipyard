#!/usr/bin/env python3
"""Executable official terminal follow-up processor (SPEC-236)."""
from __future__ import annotations
import argparse, hashlib, json, tempfile
from pathlib import Path
from check_followup_spec import check
from followup_metrics import build_record, process_decision, zero_suggestion_record, discover_specs

def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument('--root', type=Path, required=True); p.add_argument('--specs-dir', type=Path, required=True)
    p.add_argument('--source-spec', required=True); p.add_argument('--run-id', required=True)
    p.add_argument('--terminal-context', required=True); p.add_argument('--evidence-ref', required=True)
    p.add_argument('--project-id', default='nightshift'); p.add_argument('--title'); p.add_argument('--outcome')
    p.add_argument('--cause-class', default='legacy_unclassified'); p.add_argument('--detail-reason', default='insufficient_structured_evidence')
    p.add_argument('--discovery-phase', default='verification'); p.add_argument('--planned', action='store_true')
    p.add_argument('--child-markdown', type=Path); p.add_argument('--recorded-at', default='1970-01-01T00:00:00Z'); a=p.parse_args()
    if a.terminal_context not in {'done','noop','partial','blocked','unblock','verifier_warning','material_scope','integration_failure','post_release'}: p.error('unknown terminal context')
    specs=a.specs_dir; corpus=discover_specs(specs); source=corpus.get(a.source_spec)
    if source is None: p.error('source spec does not resolve')
    source_hash=hashlib.sha256(source.read_bytes()).hexdigest(); store=a.root/'metrics/_wip/followup-lineage.json'
    if store.is_symlink():
        raise ValueError('lineage store may not be a symlink')
    if not a.title:
        row=zero_suggestion_record(project_id=a.project_id,run_id=a.run_id,source_spec_id=a.source_spec,source_hash=source_hash,terminal_outcome=a.terminal_context,evidence_ref=a.evidence_ref,created_at=a.recorded_at)
    else:
        existing_rows = json.loads(store.read_text()) if store.exists() else []
        if not isinstance(existing_rows, list) or any(not isinstance(row, dict) or not isinstance(row.get("operation_key"), str) or not row["operation_key"] for row in existing_rows):
            raise ValueError('lineage store must be a JSON array of records')
        replay = next((row for row in existing_rows if
            row.get('project_id') == a.project_id and row.get('run_id') == a.run_id and
            row.get('source_spec_id') == a.source_spec and row.get('discovery_phase') == a.discovery_phase and
            row.get('cause_class') == a.cause_class and row.get('detail_reason') == a.detail_reason and
            row.get('planned_at_source_authoring') is a.planned and row.get('outcome') == (a.outcome or 'accepted_pending') and
            row.get('evidence_refs') == [a.evidence_ref] and row.get('created_at') == a.recorded_at), None)
        suggestion_hash = hashlib.sha256(a.title.encode()).hexdigest()
        if replay is not None:
            if 'suggestion_hash' in replay and replay['suggestion_hash'] != suggestion_hash:
                raise ValueError('operation proof disagrees with recorded suggestion')
            if replay.get('source_hash') != source_hash:
                raise ValueError('source_hash disagrees with current source')
            child = replay.get('child_spec_id')
            child_path = corpus.get(child) if child else None
            if child and child_path is None:
                raise ValueError('child_spec_id does not resolve for recorded operation')
            process_decision(store_path=store, specs_dir=specs, record=replay,
                child_path=child_path, child_markdown=child_path.read_text() if child_path else None)
            print(json.dumps(replay, sort_keys=True)); return 0
        # The existing checker receives the same exact parsed corpus, without
        # generated notes. A sibling directory preserves project registry roots.
        with tempfile.TemporaryDirectory(prefix='.followup-corpus-', dir=specs.parent) as directory:
            check_specs = Path(directory)
            for index, path in enumerate(corpus.values()):
                # Neutral names prevent the checker's historical template filename
                # exclusion from discarding a structurally qualifying underscore spec.
                (check_specs / f'{index:06d}.md').write_bytes(path.read_bytes())
            code,result=check(
                a.title,
                check_specs,
                artifact=None,
                domain=None,
                layer=None,
                threshold=0.4,
                source_spec_id=a.source_spec,
            )
        if code == 2:
            raise ValueError('suggestion conflict check could not validate source context')
        outcome=a.outcome or ('accepted_pending' if code==0 else 'conflict_existing')
        child_id=None; child_path=None; body=None
        if outcome=='created':
            if code: p.error('cannot create conflicted suggestion')
            child_id=result['proposed_id']; child_path=specs/f'{child_id}.md'
            if not a.child_markdown: p.error('created requires --child-markdown')
            body=a.child_markdown.read_text()
        row=build_record(project_id=a.project_id,run_id=a.run_id,source_spec_id=a.source_spec,child_spec_id=child_id,discovery_phase=a.discovery_phase,cause_class=a.cause_class,detail_reason=a.detail_reason,planned_at_source_authoring=a.planned,outcome=outcome,evidence_refs=[a.evidence_ref],source_hash=source_hash,created_at=a.recorded_at)
        row['suggestion_hash'] = suggestion_hash
        if body is not None:
            row['child_hash'] = hashlib.sha256(body.encode()).hexdigest()
        process_decision(store_path=store,specs_dir=specs,record=row,child_path=child_path,child_markdown=body)
        print(json.dumps(row,sort_keys=True)); return 0
    process_decision(store_path=store,specs_dir=specs,record=row)
    print(json.dumps(row,sort_keys=True)); return 0
def run() -> int:
    try:
        return main()
    except (json.JSONDecodeError, OSError, UnicodeError):
        import sys
        print("follow-up processing refused: corpus or persistence cannot be read or written", file=sys.stderr)
        return 1
    except ValueError as error:
        import sys
        print(f"follow-up processing refused: {error}", file=sys.stderr)
        return 1



if __name__=='__main__': raise SystemExit(run())
