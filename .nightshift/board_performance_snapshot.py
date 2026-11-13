#!/usr/bin/env python3
"""Opt-in, finite graph observations and strictly qualified offline comparisons."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import platform
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

ATTEMPT_SECONDS = 30
INVOCATION_SECONDS = 240
PHASES = ('total_ms', 'fetch_ms', 'json_decode_ms', 'prepare_ms', 'first_paint_ms')
OUTCOMES = ('success', 'error', 'cancelled', 'timeout')
IDENTITY_KEYS = ('schema_version', 'boundary_version', 'target_kind', 'source', 'corpus', 'runtime', 'scenario')
REASONS = (None, 'observer_error', 'attempt_limit', 'invocation_limit', 'setup_error', 'corpus_changed')
HASH = re.compile(r'[0-9a-f]{64}')
VERSION = re.compile(r'[0-9]+(?:\.[0-9]+){1,4}')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def seal(value):
    result = copy.deepcopy(value)
    result.pop('digest', None)
    result['digest'] = digest(result)
    return result


def empty_identity(kind, scenario, viewport=None):
    return dict(schema_version=1, boundary_version=1, target_kind=kind,
                source=dict(revision=None, digest=None, inputs=[], served_digest=None),
                corpus=dict(digest=None, dependency_digest=None, nodes=None, edges=None),
                runtime=dict(browser=None, playwright=None, python=None, platform=None, architecture=None,
                             viewport=viewport or dict(width=1200, height=900)), scenario=copy.deepcopy(scenario))


def _require(condition, code='invalid_schema'):
    if not condition:
        raise ValueError(code)


def _keys(value, keys):
    _require(type(value) is dict and set(value) == set(keys))


def _hash(value, nullable=True):
    _require((nullable and value is None) or (type(value) is str and HASH.fullmatch(value) is not None))


def _count(value, nullable=True):
    _require((nullable and value is None) or (type(value) is int and value >= 0))


def validate(artifact):
    """Strict portable schema: reject extra fields, free prose and modified evidence."""
    _keys(artifact, (*IDENTITY_KEYS, 'attempts', 'partial_reason', 'digest'))
    _require(artifact['schema_version'] == 1 and type(artifact['schema_version']) is int)
    _require(type(artifact['boundary_version']) is int and artifact['boundary_version'] >= 1)
    _require(artifact['target_kind'] in ('live', 'fixture', 'export'))
    source = artifact['source']
    _keys(source, ('revision', 'digest', 'inputs', 'served_digest'))
    _require(source['revision'] is None or (type(source['revision']) is str and re.fullmatch('[0-9a-f]{40,64}', source['revision']) is not None))
    _require(type(source['inputs']) is list and len(source['inputs']) <= 64)
    for value in source['inputs']:
        _hash(value, False)
    _hash(source['digest']); _hash(source['served_digest'])
    if source['digest'] is not None:
        _require(source['digest'] == digest(source['inputs']), 'source_digest_mismatch')
    corpus = artifact['corpus']
    _keys(corpus, ('digest', 'dependency_digest', 'nodes', 'edges'))
    _hash(corpus['digest']); _hash(corpus['dependency_digest'])
    _count(corpus['nodes']); _count(corpus['edges'])
    runtime = artifact['runtime']
    _keys(runtime, ('browser', 'playwright', 'python', 'platform', 'architecture', 'viewport'))
    for field in ('browser', 'playwright', 'python'):
        _require(runtime[field] is None or (type(runtime[field]) is str and VERSION.fullmatch(runtime[field]) is not None))
    _require(runtime['platform'] in (None, 'Darwin', 'Linux', 'Windows', 'other'))
    _require(runtime['architecture'] in (None, 'arm64', 'x86_64', 'other'))
    _keys(runtime['viewport'], ('width', 'height'))
    for value in runtime['viewport'].values():
        _require(type(value) is int and 1 <= value <= 16384)
    _keys(artifact['scenario'], ('requested', 'show_all_dependencies', 'controlled'))
    _require(all(type(value) is bool for value in artifact['scenario'].values()))
    attempts = artifact['attempts']
    _require(type(attempts) is list and len(attempts) <= 6)
    for sequence, sample in enumerate(attempts, 1):
        _keys(sample, ('sequence', 'stage', 'outcome', 'visible', 'requested', 'nodes', 'edges', 'timings', 'reason'))
        _require(type(sample['sequence']) is int and sample['sequence'] == sequence)
        _require(sample['stage'] == ('first' if sequence == 1 else 'warm'))
        _require(sample['outcome'] in OUTCOMES and sample['reason'] in REASONS)
        _require(type(sample['visible']) is bool and type(sample['requested']) is bool)
        _count(sample['nodes']); _count(sample['edges'])
        _keys(sample['timings'], PHASES)
        for value in sample['timings'].values():
            _require(value is None or (type(value) in (int, float) and math.isfinite(value) and value >= 0))
    _require(artifact['partial_reason'] in REASONS)
    _require(len(attempts) == 6 or artifact['partial_reason'] is not None)
    _hash(artifact['digest'], False)
    unsigned = {k:v for k,v in artifact.items() if k != 'digest'}
    _require(artifact['digest'] == digest(unsigned), 'artifact_digest_mismatch')
    return artifact


def failed_sample(reason, outcome='error'):
    return dict(outcome=outcome, visible=False, requested=False, nodes=None, edges=None,
                timings={key:None for key in PHASES}, reason=reason)


def collect(identity, observe, *, clock=time.monotonic, started=None, checkpoint=None):
    """Observer receives a remaining per-attempt budget; never replace an attempt."""
    start = clock() if started is None else started
    result = copy.deepcopy(identity)
    result.update(attempts=[], partial_reason=None)
    for sequence in range(1, 7):
        remaining = INVOCATION_SECONDS - (clock() - start)
        if remaining <= 0:
            result['partial_reason'] = 'invocation_limit'
            break
        budget = min(ATTEMPT_SECONDS, remaining)
        before = clock()
        try:
            sample = observe(sequence, max(1, int(budget * 1000)))
        except TimeoutError:
            sample = failed_sample('attempt_limit', 'timeout')
        except Exception:
            sample = failed_sample('observer_error')
        if clock() - before >= budget:
            sample = failed_sample('attempt_limit', 'timeout')
        if sample.get('reason') is not None and sample['timings']['total_ms'] is None:
            sample['requested'] = bool(identity['scenario']['requested'] and identity['target_kind'] != 'export')
        # Observer cannot set sequence/stage or sneak raw data into the artifact.
        sample = {key:sample[key] for key in ('outcome','visible','requested','nodes','edges','timings','reason')}
        sample.update(sequence=sequence, stage='first' if sequence == 1 else 'warm')
        result['attempts'].append(sample)
        # Browser observer enriches the same origin-only identity after its first draw.
        for key in IDENTITY_KEYS:
            result[key] = copy.deepcopy(identity[key])
        if checkpoint:
            partial = dict(result, partial_reason='invocation_limit' if sequence < 6 else None)
            checkpoint(seal(partial))
    return validate(seal(result))


def _stats(values):
    ordered = sorted(values)
    return dict(count=len(values), median_ms=statistics.median(values),
                p95_ms=ordered[math.ceil(.95 * len(values))-1], min_ms=ordered[0], max_ms=ordered[-1])


def _denominators(artifact):
    rows = artifact['attempts']
    return dict(attempted=len(rows), unattempted=6-len(rows),
                outcomes={state:sum(s['outcome']==state for s in rows) for state in OUTCOMES},
                hidden=sum(not s['visible'] for s in rows), partial_reason=artifact['partial_reason'])


def compare(baseline, candidate):
    result = dict(schema_version=1, state='incomparable', reasons=[],
                  qualification='Finite samples vary; advisory is neither statistical nor causal proof and is not a wall-clock CI gate.')
    for name, artifact in (('baseline',baseline), ('candidate',candidate)):
        try:
            validate(artifact)
        except (ValueError, TypeError, KeyError, OverflowError):
            result['reasons'].append(dict(code='invalid_artifact',field=name))
    if result['reasons']:
        return seal(result)
    result.update(baseline_digest=baseline['digest'], candidate_digest=candidate['digest'],
                  arm_identities={name:{key:arm[key] for key in IDENTITY_KEYS}
                                  for name,arm in (('baseline',baseline),('candidate',candidate))},
                  source_changes={name:arm['source'] for name,arm in (('baseline',baseline),('candidate',candidate))})
    for name, arm in (('baseline',baseline),('candidate',candidate)):
        for section in ('source','corpus','runtime'):
            for field,value in arm[section].items():
                if value is None or (section=='source' and field=='inputs' and not value):
                    result['reasons'].append(dict(code='missing_identity',field=name+'.'+section+'.'+field))
    for key in ('boundary_version','target_kind'):
        if baseline[key] != candidate[key]: result['reasons'].append(dict(code='identity_mismatch',field=key))
    for section in ('corpus','runtime','scenario'):
        for field in baseline[section]:
            if baseline[section][field] != candidate[section][field]:
                result['reasons'].append(dict(code='identity_mismatch',field=section+'.'+field))
    modes = [{s['requested'] for s in arm['attempts'] if s['stage']=='warm'} for arm in (baseline,candidate)]
    if (modes[0] and modes[1] and modes[0] != modes[1]) or any(len(mode)>1 for mode in modes):
        result['reasons'].append(dict(code='identity_mismatch',field='warm.requested'))
    if result['reasons']:
        return seal(result)
    result.update(state='comparable', identities={key:baseline[key] for key in ('target_kind','boundary_version','corpus','runtime','scenario')},
                  denominators={name:_denominators(arm) for name,arm in (('baseline',baseline),('candidate',candidate))},
                  first={name:(arm['attempts'][0] if arm['attempts'] else None) for name,arm in (('baseline',baseline),('candidate',candidate))})
    result['budget_breaches'] = {name:[dict(sequence=s['sequence'],stage=s['stage'],total_ms=s['timings']['total_ms'])
        for s in arm['attempts'] if s['outcome']=='success' and s['visible'] and s['timings']['total_ms'] is not None and s['timings']['total_ms']>2000]
        for name,arm in (('baseline',baseline),('candidate',candidate))}
    qualified = [[s['timings']['total_ms'] for s in arm['attempts'] if s['stage']=='warm' and s['outcome']=='success'
                  and s['visible'] and s['timings']['total_ms'] is not None] for arm in (baseline,candidate)]
    warm = dict(state='insufficient_evidence', baseline_count=len(qualified[0]), candidate_count=len(qualified[1]))
    if all(len(values)==5 for values in qualified):
        b,c = map(_stats,qualified);delta=c['median_ms']-b['median_ms']
        percent=100*delta/b['median_ms'] if b['median_ms'] else None
        warm.update(state='qualified',baseline=b,candidate=c,delta_ms=delta,delta_percent=percent,
                    suspected_degradation=delta>100 and percent is not None and percent>20,
                    baseline_p95_budget_breach=b['p95_ms']>2000,candidate_p95_budget_breach=c['p95_ms']>2000)
    result['warm'] = warm
    return seal(result)


def _write_exclusive(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')


def _origin_identity(root, kind, scenario):
    root = Path(root).resolve()
    revision = subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True,timeout=10).strip()
    inputs = [hashlib.sha256((root/name).read_bytes()).hexdigest() for name in ('board.py','dependency_graph_view.py','board_performance_snapshot.py')]
    identity = empty_identity(kind,scenario)
    identity['source'].update(revision=revision,inputs=inputs,digest=digest(inputs))
    identity['runtime'].update(python=platform.python_version(), platform=platform.system() if platform.system() in ('Darwin','Linux','Windows') else 'other',
                               architecture=platform.machine() if platform.machine() in ('arm64','x86_64') else 'other')
    return identity


async def bounded_observation(observation, timeout_ms):
    # Playwright evaluate has no per-call timeout; bound the whole async attempt.
    import asyncio
    return await asyncio.wait_for(observation, timeout=timeout_ms / 1000)


def capture(args):
    """The only browser/network entrypoint. Not imported or called by comparison."""
    from importlib.metadata import version
    from urllib.parse import urlparse
    import asyncio
    from playwright.async_api import async_playwright, TimeoutError as BrowserTimeout
    start = time.monotonic()
    scenario = dict(requested=args.requested, show_all_dependencies=args.all_dependencies, controlled=args.controlled_fixture)
    kind = 'export' if args.export else ('fixture' if args.controlled_fixture else 'live')
    if args.url:
        parsed = urlparse(args.url)
        _require(parsed.scheme=='http' and parsed.hostname in ('127.0.0.1','localhost','::1') and not parsed.username and not parsed.password, 'local_target_required')
    target = Path(args.export).resolve().as_uri() if args.export else args.url
    identity = _origin_identity(args.source_root,kind,scenario)
    identity['runtime']['playwright'] = version('playwright')
    result = None
    # Exclusive reservation prevents replacing evidence, including a baseline.
    output = Path(args.output)
    initial = seal(dict(identity,attempts=[],partial_reason='setup_error'))
    _write_exclusive(output, initial)
    last_checkpoint = initial
    def checkpoint(value):
        nonlocal last_checkpoint
        _replace_checkpoint(output, value)
        last_checkpoint = copy.deepcopy(value)
    try:
        with asyncio.Runner() as runner:
            driver = runner.run(async_playwright().start())
            browser = runner.run(driver.chromium.launch(headless=True, timeout=min(30000,max(1,int((INVOCATION_SECONDS-(time.monotonic()-start))*1000)))))
            try:
                identity['runtime']['browser'] = browser.version
                page = runner.run(browser.new_page(viewport=identity['runtime']['viewport']))
                page.set_default_timeout(30000)
                async def observe_async(sequence, timeout):
                    attempt_start=time.monotonic()
                    def remaining():
                        left=timeout-int((time.monotonic()-attempt_start)*1000)
                        if left<=0: raise TimeoutError()
                        return left
                    try:
                        if sequence==1:
                            await page.goto(target,wait_until='domcontentloaded',timeout=remaining())
                            await page.wait_for_function('() => typeof vis !== "undefined" && typeof showGraph === "function" && document.querySelector("#board-view .card")',timeout=remaining())
                            # Only a digest of served inline code leaves this origin.
                            identity['source']['served_digest']=digest(await page.locator('script:not([src])').all_text_contents())
                        sequence_before=await page.evaluate('() => graphLoadSequence')
                        await page.evaluate('flags => {showAllDependencies=flags.all; void showGraph(undefined,{refresh:flags.requested});}',dict(all=scenario['show_all_dependencies'],requested=scenario['requested']))
                        await page.wait_for_function('(before) => graphLoadSequence>before && graphLatestLoad && graphLatestLoad.state!=="loading"',arg=sequence_before,timeout=remaining())
                        observed=await page.evaluate('() => ({latest:graphLatestLoad, visible:!document.hidden, corpus:graphData})')
                        latest=observed['latest'];corpus=observed['corpus']
                        if corpus:
                            current=dict(digest=digest(corpus),dependency_digest=digest({k:corpus.get(k,[]) for k in ('edges','parent_edges')}),
                                         nodes=len(corpus.get('nodes',[])),edges=len(corpus.get('edges',[])))
                            if identity['corpus']['digest'] is None: identity['corpus'].update(current)
                            elif current!=identity['corpus']: return failed_sample('corpus_changed')
                        timings=dict(total_ms=latest.get('total_ms'),**{key+'_ms':latest.get('phases',{}).get(key) for key in ('fetch','json_decode','prepare','first_paint')})
                        return dict(outcome=latest['state'] if latest['state'] in OUTCOMES else 'error',visible=observed['visible'] and bool(latest.get('qualified')),
                                    requested=bool(latest.get('requested')),nodes=latest.get('nodes'),edges=latest.get('edges'),timings=timings,reason=None)
                    except BrowserTimeout:
                        raise TimeoutError() from None
                def observe(sequence, timeout):
                    return runner.run(bounded_observation(observe_async(sequence, timeout), timeout))
                result=collect(identity,observe,started=start,checkpoint=checkpoint)
            finally:
                runner.run(browser.close())
                runner.run(driver.stop())
    except Exception:
        # Preserve already completed attempts and controlled partial disposition.
        if result is None:
            result = seal(dict(last_checkpoint, partial_reason='setup_error'))
    if result is not None: checkpoint(result)
    return result


def _replace_checkpoint(output, value):
    """Keep the previous valid artifact if a process is killed during a write."""
    import os
    import tempfile
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=Path(output).parent, delete=False, encoding='utf-8') as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, sort_keys=True, allow_nan=False)
            stream.write('\n')
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _capture_worker(argv, output, *, popen=subprocess.Popen, clock=time.monotonic, limit=INVOCATION_SECONDS):
    """External watchdog also bounds browser shutdown and preserves interrupted evidence."""
    import os
    import signal
    _require(not Path(output).exists(), 'output_exists')
    started = clock()
    process = popen([sys.executable, str(Path(__file__).resolve()), *argv, '--worker'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        # Leave bounded termination time inside the 240-second invocation budget.
        return process.wait(timeout=max(.001, limit - 3 - (clock()-started)))
    except subprocess.TimeoutExpired:
        if os.name == 'posix':
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=max(.001, limit-(clock()-started)))
        try:
            partial = validate(json.loads(Path(output).read_text()))
            if len(partial['attempts']) < 6:
                sequence = len(partial['attempts']) + 1
                sample = failed_sample('invocation_limit', 'timeout')
                sample['requested'] = bool(partial['scenario']['requested'] and partial['target_kind'] != 'export')
                sample.update(sequence=sequence, stage='first' if sequence==1 else 'warm')
                partial['attempts'].append(sample)
            partial['partial_reason'] = 'invocation_limit'
            _replace_checkpoint(output, validate(seal(partial)))
        except (OSError, ValueError, KeyError, TypeError):
            # Missing or invalid output never becomes fabricated success evidence.
            return 2
        return 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    compare_parser=sub.add_parser('compare')
    for name in ('baseline','candidate','output'):compare_parser.add_argument('--'+name,required=True)
    capture_parser=sub.add_parser('capture')
    target=capture_parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--url');target.add_argument('--export')
    capture_parser.add_argument('--source-root',required=True)
    capture_parser.add_argument('--output',required=True)
    capture_parser.add_argument('--scenario',choices=('requested','no-request'),required=True)
    capture_parser.add_argument('--all-dependencies',action='store_true')
    capture_parser.add_argument('--controlled-fixture',action='store_true')
    capture_parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args=parser.parse_args(argv)
    try:
        if args.command=='compare':
            out=Path(args.output).resolve()
            _require(out not in (Path(args.baseline).resolve(),Path(args.candidate).resolve()),'input_overwrite_refused')
            result=compare(json.loads(Path(args.baseline).read_text()),json.loads(Path(args.candidate).read_text()))
            _write_exclusive(out,result)
            return 0 if result['state']=='comparable' else 1
        args.requested=args.scenario=='requested'
        if not args.worker:
            from importlib.util import find_spec
            if find_spec('playwright') is None:
                print('capture_runtime_unavailable: optional Playwright/Chromium required', file=sys.stderr)
                return 2
            code = _capture_worker(argv, args.output)
            if code:
                print('capture_incomplete' if code == 1 else 'capture_refused_or_optional_runtime_unavailable', file=sys.stderr)
            return code
        result=capture(args)
        complete = len(result['attempts']) == 6 and result['partial_reason'] is None
        qualified = all(s['outcome']=='success' and s['visible'] and s['timings']['total_ms'] is not None for s in result['attempts'])
        return 0 if complete and qualified else 1
    except (ValueError,OSError,KeyError,ImportError,subprocess.SubprocessError):
        print('snapshot_command_refused',file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
