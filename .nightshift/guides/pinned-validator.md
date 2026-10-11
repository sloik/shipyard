Load when: you validate a verifier verdict (Step 5c d) or run `assemble-verdict`; `verification_report.py` reads the validator here at run time.
Covers: the verdict validator script and the `GATE: reject` rule that follows it, byte-for-byte.
Not here: the briefs and template (`pinned-briefs.md`), the brief check and scope gate (`pinned-checks.md`), the run step that calls the validator (`run-6.md`).
Requires: nothing read first; code finds the block by its marker name, so never move it to another guide or retype it.

# Pinned verifier block: verdict validator

These blocks are read from this guide at run time by `verification_report.py` and by tests, so they stay here byte-for-byte; the run guides refer to them by marker name. Edit one only through a spec that changes what it checks.

**Verdict validator (Step 5c d).**

```python
# NIGHTSHIFT-VERDICT-VALIDATOR-BEGIN
# usage: python3 validate_verdict.py <verdict.json> [spec-file] [surface-repo] [main-root [main-branch]]
#   -> prints report, exit 0 = auditable
# [spec-file] also gates the AC-ID coverage check (below); [surface-repo] --
# the standalone verifier surface containing `verifier-baseline`/`verifier-head`
# -- additionally gates full scope.out_of_scope/.amended recomputation
# (SPEC-300-002 R6) and requires [spec-file] to be supplied too.
# SPEC-413: the scope recomputation and `## Scope Amendments` globs read the
# spec as COMMITTED on main (`git show <main-branch>:<spec-relpath>` from
# [main-root], default branch `main`), like check 6 -- never [spec-file]'s
# working copy, which in practice is the head arm's copy and predates a
# mid-run approved amendment. [spec-file] still locates the kit (scope_guard.py)
# and the AC list. The surface has no `main` branch, so pass the project root
# as [main-root]; without it the recomputation falls back to [spec-file].
import json, re, subprocess, sys
from pathlib import Path

def die(msg): print("SCHEMA:     reject: " + msg); print("GATE:       reject"); sys.exit(1)

v = json.load(open(sys.argv[1]))
for k in ("spec_id","branch","baseline_commit","head_commit","identity_schema_version","implementation_head_digest","verdict","acs","suites","git_footprint","scope","contamination"):
    if k not in v: die("missing top-level key '%s'" % k)
if v["identity_schema_version"] != "1.0.0": die("unsupported verifier identity schema")
if not re.fullmatch(r"[0-9a-f]{64}", v["implementation_head_digest"]): die("invalid implementation_head_digest")
if v["verdict"] not in ("pass","fail","disputes_premise"): die("verdict not in enum: %r" % v["verdict"])
_cx = v["contamination"]  # SPEC-NS-KIT-002-005 R2: null, or closed {class, timing} exposure object(s)
for _c in (_cx if isinstance(_cx, list) else [] if _cx is None else [_cx]):
    if not (isinstance(_c, dict) and _c.get("class") in ("spec_bookkeeping","author_artifact_name","required_deliverable","author_conclusion") and _c.get("timing") in ("before_derivation","after_derivation")): die("contamination must be null or {class, timing} exposure objects")

# R5 — disputes_premise must carry its evidence, or it is just an opinion.
# R2 (SPEC-ARGO-049) — and must state explicitly whether the dispute names a
# spec defect, since Step 5c(e) routes on that field, not on the claim text.
if v["verdict"] == "disputes_premise":
    d = v.get("premise_dispute") or {}
    if not d.get("claim") or not d.get("evidence"): die("disputes_premise without premise_dispute.claim + .evidence")
    if not isinstance(d.get("spec_defect"), bool): die("disputes_premise without premise_dispute.spec_defect (bool)")

# R4/R6 — read-only, asserted by hash, over BOTH assigned arm surfaces
# (SPEC-282). A clean baseline arm never masks a dirty head arm or vice versa.
# SPEC-284: the working-tree half is recomputed here as a set comparison of the
# verdict's own porcelain_before against its porcelain_after, never an emptiness
# test on porcelain_after. A worktree that was already dirty at dispatch is not
# the verifier's footprint; an entry only in after (added) or only in before
# (removed) is. That retires the single generated-artifact exclusion this block
# used to carry — pre-existing generated output now cancels in every project,
# with no project's tooling named here. Both fields are REQUIRED: a verdict
# carrying only the old flat `porcelain` key has no before-set to compare
# against, and is rejected rather than read as two empty sets, which would
# accept real dirt.
gf = v["git_footprint"]
if not isinstance(gf, dict) or not {"baseline","head"}.issubset(gf): die("git_footprint must report both baseline and head arms")
for arm_label in ("baseline","head"):
    g = gf.get(arm_label) or {}
    if g.get("tree_before") != g.get("tree_after"): die("%s: verifier mutated the repo (tree %s -> %s)" % (arm_label, g.get("tree_before"), g.get("tree_after")))
    if "porcelain_before" not in g or "porcelain_after" not in g: die("%s: footprint must record porcelain_before and porcelain_after" % arm_label)
    _before = {l for l in (g.get("porcelain_before") or "").splitlines() if l.strip()}
    _after = {l for l in (g.get("porcelain_after") or "").splitlines() if l.strip()}
    _added, _removed = sorted(_after - _before), sorted(_before - _after)
    if _added: die("%s: verifier added to the working tree: %s" % (arm_label, "; ".join(_added)))
    if _removed: die("%s: verifier removed pre-existing working-tree state: %s" % (arm_label, "; ".join(_removed)))

# SPEC-300-002 R6 -- scope schema is always required; full recomputation
# against the verifier-baseline..verifier-head diff runs only when the
# standalone surface repo is supplied as argv[3] (requires argv[2] too).
sc = v["scope"]
if not isinstance(sc, dict) or not {"checked","out_of_scope","amended"}.issubset(sc):
    die("scope must be a dict with checked/out_of_scope/amended")
for _sk in ("checked","out_of_scope","amended"):
    if not isinstance(sc.get(_sk), list) or not all(isinstance(p, str) for p in sc[_sk]):
        die("scope.%s must be a list of path strings" % _sk)
if len(sys.argv) > 3:
    if len(sys.argv) <= 2: die("scope recomputation requires the spec-file argument (argv[2])")
    surface_repo, spec_file_for_scope = sys.argv[3], sys.argv[2]
    kit_dir = Path(spec_file_for_scope).resolve().parent.parent
    sys.path.insert(0, str(kit_dir))
    import scope_guard  # noqa: E402
    spec_text = open(spec_file_for_scope).read()
    scope = scope_guard.resolve_scope(spec_text)
    main_root = Path(sys.argv[4]).resolve() if len(sys.argv) > 4 else None
    main_branch = sys.argv[5] if len(sys.argv) > 5 else "main"
    diff = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACDMR", "verifier-baseline", "verifier-head", "--"],
        cwd=surface_repo, capture_output=True, text=True,
    )
    diff_paths = sorted(p for p in diff.stdout.splitlines() if p.strip())
    project_root = Path(surface_repo)
    # BUG-336 R2: spec_relpath must be project_root-relative to match the diff paths.
    try:
        spec_relpath = str(Path(spec_file_for_scope).resolve().relative_to(project_root.resolve()))
    except ValueError:
        spec_relpath = spec_file_for_scope
    if main_root is not None:
        # SPEC-413 R2: main's committed spec, not the working copy above.
        main_relpath = None
        for base in (main_root, project_root.resolve()):
            try:
                rel = Path(spec_file_for_scope).resolve().relative_to(base)
            except ValueError:
                continue
            if rel.parts and rel.parts[0] in ("verifier-baseline", "verifier-head"):
                rel = Path(*rel.parts[1:])
            main_relpath = str(rel)
            break
        if main_relpath is None:
            main_relpath = spec_relpath
        shown = subprocess.run(
            ["git", "show", main_branch + ":" + main_relpath],
            cwd=main_root, capture_output=True, text=True,
        )
        if shown.returncode != 0:
            die("cannot read %s:%s from %s for scope recomputation" % (main_branch, main_relpath, main_root))
        spec_text = shown.stdout
        scope = scope_guard.scope_from_main(main_root, main_relpath, main_branch)
    amend_globs = []
    heading = re.search(r"^## Scope Amendments\s*$([\s\S]*?)(?=^## |\Z)", spec_text, re.M)
    if heading:
        for line in heading.group(1).split("\n"):
            s = line.strip()
            if not s.startswith("|") or re.match(r"^\|[\s:|-]*\|?$", s):
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if not any(cells) or cells[0] == "Date" or len(cells) < 5 or not cells[1]:
                continue
            amend_globs.append(cells[1])
    computed_out, computed_amended = [], []
    for p in diff_paths:
        d = scope_guard.classify_write(p, scope, project_root, kit_dir, spec_relpath)
        if d.allowed:
            continue
        if any(scope_guard._glob_match(g, p) for g in amend_globs):
            computed_amended.append(p)
        else:
            computed_out.append(p)
    if sorted(sc["checked"]) != diff_paths:
        die("scope.checked disagrees with the verifier-baseline..verifier-head diff")
    if sorted(sc["out_of_scope"]) != sorted(computed_out):
        die("scope.out_of_scope disagrees with recomputed classification")
    if sorted(sc["amended"]) != sorted(computed_amended):
        die("scope.amended disagrees with recomputed classification")

# R3 — per-AC status, and every AC in the spec covered.
if not v["acs"]: die("no per-AC statuses")
for a in v["acs"]:
    if a.get("status") not in ("pass","fail","unverifiable"): die("%s: bad status %r" % (a.get("id"), a.get("status")))
    if not isinstance(a.get("evidence"), str) or not a["evidence"].strip(): die("%s: evidence must be a non-empty string" % a.get("id"))
if len(sys.argv) > 2:
    # Scope the AC-ID scan to the "## Acceptance Criteria" section only. A
    # whole-file scan false-positives on prose that mentions another spec's
    # AC (e.g. a child spec discussing its parent's "AC6") as if it were an
    # uncovered AC of the spec under verification. Falls back to whole-file
    # if the heading isn't found, so specs without this exact heading still
    # get a check rather than none.
    spec_text = open(sys.argv[2]).read()
    ac_section = re.search(r"^##\s+Acceptance Criteria\s*$(.*?)(?=^##\s|\Z)", spec_text, re.M | re.S)
    want = set(re.findall(r"\bAC\d+\b", ac_section.group(1) if ac_section else spec_text))
    missing = sorted(want - {a.get("id") for a in v["acs"]})
    if missing: die("ACs not covered: %s" % ",".join(missing))

# SPEC-392: first-scaffold unavailability is not a passing baseline. Only the
# standalone, exact-ref surface can substantiate it; ordinary arms stay strict.
def first_scaffold_unavailable(s):
    import hashlib, shlex
    from pathlib import PurePosixPath
    proof = s.get("baseline_unavailable")
    if not isinstance(proof, dict) or proof.get("schema_version") != "1.0.0" or proof.get("reason") != "first_scaffold_absent":
        die("baseline_unavailable: unsupported or missing first-scaffold proof")
    if len(sys.argv) <= 3:
        die("baseline_unavailable requires the assigned standalone surface")
    root = Path(sys.argv[3]).resolve()
    def git(*args, cwd=root):
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, timeout=30)
        if result.returncode: die("baseline_unavailable: Git proof unavailable")
        return result.stdout
    def safe_path(value):
        if not isinstance(value, str) or not value or "\\" in value:
            die("baseline_unavailable: unsafe relative path")
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or str(path) != value or value == ".":
            die("baseline_unavailable: unsafe relative path")
        return value
    for arm in ("baseline", "head"):
        revision = git("rev-parse", "verifier-" + arm).decode().strip()
        if proof.get(arm + "_commit") != revision or v[arm + "_commit"] != revision:
            die("baseline_unavailable: assigned revision mismatch")
        directory = root / ("verifier-" + arm)
        if not directory.is_dir() or git("rev-parse", "HEAD", cwd=directory).decode().strip() != revision:
            die("baseline_unavailable: assigned arm mismatch")
    paths = proof.get("scaffold_paths")
    if not isinstance(paths, list) or not paths or len(set(paths)) != len(paths):
        die("baseline_unavailable: missing or duplicate scaffold paths")
    for path in paths:
        path = safe_path(path)
        for arm, expected in (("baseline", False), ("head", True)):
            result = subprocess.run(["git", "cat-file", "-e", "verifier-" + arm + ":" + path], cwd=root, capture_output=True, timeout=30)
            if (result.returncode == 0) != expected:
                die("baseline_unavailable: scaffold must be absent at baseline and present at head")
    guard = proof.get("guard") or {}
    guard_path = safe_path(guard.get("path"))
    blob = git("show", "verifier-baseline:" + guard_path)
    if guard.get("sha256") != hashlib.sha256(blob).hexdigest():
        die("baseline_unavailable: tracked guard hash mismatch")
    try:
        argv = shlex.split(s.get("command", ""))
    except ValueError:
        die("baseline_unavailable: invalid command")
    if len(argv) < 2 or argv[0] not in ("bash", "sh", "python3") or argv[1] != guard_path or proof.get("command") != s.get("command"):
        die("baseline_unavailable: command must directly invoke the tracked guard")
    guard_file = root / "verifier-baseline" / guard_path
    if not guard_file.is_file() or guard_file.is_symlink() or not guard_file.resolve().is_relative_to(root / "verifier-baseline") or guard_file.read_bytes() != blob:
        die("baseline_unavailable: assigned guard differs from tracked baseline")
    config_path = safe_path(proof.get("config_path"))
    import yaml
    for arm in ("baseline", "head"):
        try:
            config = {}
            for doc in yaml.safe_load_all(git("show", "verifier-" + arm + ":" + config_path).decode()):
                if isinstance(doc, dict): config.update(doc)
        except (yaml.YAMLError, UnicodeError):
            die("baseline_unavailable: invalid tracked configuration")
        if (config.get("commands") or {}).get("test") != s.get("command"):
            die("baseline_unavailable: command disagrees with configured test command")
    samples = s.get("samples") or {}
    if not all(isinstance(samples.get(a), list) and len(samples[a]) == 3 for a in ("baseline", "head")):
        die("baseline_unavailable requires three actual attempts per arm")
    for sample in samples["baseline"]:
        if sample.get("executed") is not True or any(type(sample.get(k)) is not int or sample[k] != value for k, value in (("exit_code",78),("discovered",0),("passed",0),("failed",0),("skipped",0))) or sample.get("failing") != []:
            die("baseline_unavailable: baseline must report executed exit78 with zero discovery")
        if not re.fullmatch(r"[0-9a-f]{64}", str(sample.get("output_sha256", ""))):
            die("baseline_unavailable: missing attempt output digest")
    for sample in samples["head"]:
        if sample.get("executed") is not True or any(type(sample.get(k)) is not int or sample[k] != value for k, value in (("exit_code",0),("failed",0),("skipped",0))) or sample.get("failing") != [] or type(sample.get("passed")) is not int or sample["passed"] <= 0 or type(sample.get("discovered")) is not int or sample["discovered"] != sample["passed"]:
            die("baseline_unavailable: head requires actual nonzero discovery, no failure or skip")
    classification = s.get("classification") or {}
    if set(classification) != {"regressed","newly_flaky","flaky_observed","fixed","flake_resolved"} or any(value != [] for value in classification.values()):
        die("baseline_unavailable cannot claim regression or fix comparison")
    baseline = root / "verifier-baseline"
    def footprint():
        return (git("rev-parse", "HEAD^{tree}", cwd=baseline), git("status", "--porcelain=v1", "--untracked-files=all", cwd=baseline))
    before = footprint()
    for sample in samples["baseline"]:
        try:
            observed = subprocess.run(argv, cwd=baseline, capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            die("baseline_unavailable: bounded guard reproduction unavailable")
        if footprint() != before:
            die("baseline_unavailable: guard reproduction mutated its assigned arm")
        if observed.returncode != 78 or hashlib.sha256(observed.stdout + observed.stderr).hexdigest() != sample["output_sha256"]:
            die("baseline_unavailable: actual guard result disagrees with attempt")

lines, match = [], True
for s in v["suites"]:
    if "baseline_unavailable" in s:
        first_scaffold_unavailable(s)
        lines.append("  %-24s baseline=unavailable (first_scaffold_absent; comparison unavailable); head=executed" % s.get("name"))
        continue
    arms = {}
    for arm in ("baseline","head"):
        smp = (s.get("samples") or {}).get(arm)
        if not smp: die("%s: no %s samples" % (s.get("name"), arm))
        for i, one in enumerate(smp):
            # R3 (SPEC-282) — a sample is evidence of an actual run, never a
            # placeholder. Reject an explicit non-execution marker...
            if one.get("executed") is False: die("%s/%s[%d]: declared executed:false — controlled evidence gap, not a passing sample" % (s.get("name"), arm, i))
            # R3 — names, not totals.
            if not isinstance(one.get("failing"), list): die("%s/%s[%d]: totals-only verdict, no failing-name list" % (s.get("name"), arm, i))
            # SPEC-NS-KIT-002-002 R7 — a reused sample (ledger projection) is valid only on the
            # baseline arm, only with `reused: true` and a lowercase 64-hex `ledger_digest`, and
            # (when the surface is supplied) only if that digest and the failing names match the
            # ledger record projected into the baseline arm. Never an independent run.
            if "reused" in one or "ledger_digest" in one:
                if arm != "baseline": die("%s/%s[%d]: reused sample on the head arm is not allowed; head needs an independent run" % (s.get("name"), arm, i))
                if one.get("reused") is not True or not re.fullmatch(r"[0-9a-f]{64}", str(one.get("ledger_digest", ""))): die("%s/%s[%d]: reused sample needs reused: true and a lowercase 64-hex ledger_digest" % (s.get("name"), arm, i))
                if len(sys.argv) > 3:
                    import hashlib
                    try:
                        _led = json.load(open(Path(sys.argv[3]) / "verifier-baseline" / ".nightshift-ledger" / "baseline.json"))
                        _body = json.dumps({k: x for k, x in _led.items() if k != "receipt_digest"}, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
                        _ok = _led.get("receipt_digest") == one["ledger_digest"] == hashlib.sha256(_body).hexdigest()
                        _names = sorted(t for t, e in (_led.get("tests") or {}).items() if isinstance(e, dict) and e.get("status") == "fail")
                    except (OSError, ValueError, AttributeError):
                        _ok, _names = False, None
                    if not _ok: die("%s/%s[%d]: reused sample ledger_digest does not match the projected ledger" % (s.get("name"), arm, i))
                    if sorted(one["failing"]) != _names: die("%s/%s[%d]: reused sample failing names disagree with the projected ledger" % (s.get("name"), arm, i))
            if "failed" in one and one["failed"] != len(one["failing"]): die("%s/%s[%d]: failed=%s but %d names" % (s.get("name"), arm, i, one["failed"], len(one["failing"])))
            # ...and a synthetic zero-count placeholder: zero passed, zero
            # failed, no failing names is indistinguishable from a suite that
            # never ran.
            if one.get("passed", 0) == 0 and one.get("failed", 0) == 0 and not one["failing"]:
                die("%s/%s[%d]: zero-count placeholder — no evidence the suite actually ran" % (s.get("name"), arm, i))
        sets = [set(o["failing"]) for o in smp]
        arms[arm] = (set().union(*sets) if sets else set(), set.intersection(*sets) if sets else set(), len(sets), sum(1 for o in smp if not o.get("reused")))
    (b_any,b_all,b_n,b_real), (h_any,h_all,h_n,h_real) = arms["baseline"], arms["head"]
    # R4 — a single draw per arm may never be reported as a difference.
    # SPEC-NS-KIT-002-003: unsupported launch failure = disagreement.
    for lf in s.get("launch_failures") or []:
        if not isinstance(lf, dict) or not str(lf.get("failed_run", "")).strip(): die("%s: launch failure: failed run dropped" % s.get("name"))
        if lf.get("counts_as_pass") is not False: die("%s: launch failure: counted as a pass" % s.get("name"))
    launch_unsupported = any(lf.get("classification") != "launch_infrastructure_supported" or not isinstance(lf.get("control_probe"), dict) or not str(lf["control_probe"].get("run", "")).strip() for lf in (s.get("launch_failures") or []))
    need = 3 if (s.get("flaky_suspected") or launch_unsupported or b_any != h_any or b_any != b_all or h_any != h_all) else 1
    _p = globals().get("_nightshift_dispatch_plan")
    _c = globals().get("_nightshift_sampling_checker")
    if _c is not None and isinstance(_p, dict) and (_p.get("sampling") or {}).get("expected_baseline_fix") is not None:
        try: _f = _c(s, plan=_p, footprint=gf, verdict=v)
        except ValueError as e: die(str(e))
        lines.append("  SAMPLING: eligible=%s reason=%s; observed correction only, determinism and future flakes unestablished" % (_f["eligible"], _f["reason"]))
        if _f["eligible"]: need = 1  # operational eligibility proves every ordered suite through separate trusted context
    # SPEC-NS-KIT-002-002 R7 — a reused sample may stand in as the single baseline draw but never
    # counts toward the 3-sample rule; the head arm always needs a real, independent run.
    b_have = b_n if need == 1 else b_real
    if min(b_have,h_real) < need: die("%s: %d/%d samples but %d per arm required (single-draw comparison is not a valid verdict)" % (s.get("name"), b_have, h_real, need))
    # BUG-024: `fixed` (baseline_all - head_any) requires a 100%-baseline-failure
    # precondition a genuinely intermittent flake almost never satisfies. `fixed`
    # and `flake_resolved` partition baseline_any - head_any ("failed at least
    # once in baseline, never in head") by whether the baseline failure was
    # total (`fixed`) or partial (`flake_resolved`) -- disjoint by construction,
    # since baseline_all and (baseline_any - baseline_all) already partition
    # baseline_any. flaky_observed's second term is narrowed to intersect with
    # head_any so a partial baseline flake that stops reproducing at head moves
    # to flake_resolved instead of staying silently absorbed in flaky_observed;
    # it stays disjoint from (head_any - head_all) since flake_resolved requires
    # head_any empty for that name while (head_any - head_all) requires it
    # present in head_any.
    rec = {"regressed": sorted(h_all - b_any), "newly_flaky": sorted((h_any - h_all) - b_any),
           "flaky_observed": sorted((h_any - h_all) | ((b_any - b_all) & h_any)),
           "fixed": sorted(b_all - h_any), "flake_resolved": sorted((b_any - b_all) - h_any)}
    dec = {k: sorted(s.get("classification", {}).get(k, [])) for k in rec}
    if dec != rec: match = False
    lines.append("  %-24s regressed=%s newly_flaky=%s flaky_observed=%s fixed=%s flake_resolved=%s" % (s.get("name"), rec["regressed"], rec["newly_flaky"], rec["flaky_observed"], rec["fixed"], rec["flake_resolved"]))

print("SCHEMA:     ok")
print("RECOMPUTED:")
for l in lines: print(l)
print("DECLARED_MATCH: " + ("yes" if match else "no"))
print("VERDICT:    " + v["verdict"])
print("GATE:       " + ("accept" if match else "reject"))
sys.exit(0 if match else 1)
# NIGHTSHIFT-VERDICT-VALIDATOR-END
```

`GATE: reject` means the verdict is **not auditable** — the verifier's own numbers
contradict its own samples. Treat it exactly like a missing verdict: do not merge,
and route to the controller-backed unblock path with
`Nightshift-Blocker-Class: evidence_gap`.
