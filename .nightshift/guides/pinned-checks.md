Load when: you check a composed verifier brief (Step 5c) or run the scope gate before a merge (Step 6 check 6); `verification_report.py` reads these blocks here at run time.
Covers: the forbidden-content brief check (`brief_check`) and the scope gate script, each byte-for-byte.
Not here: the briefs and verdict template (`pinned-briefs.md`), the verdict validator (`pinned-validator.md`), the run steps that call them (`run-5.md`, `run-7.md`).
Requires: nothing read first; code finds each block by its marker name, so never move a block between guides or retype it.

# Pinned verifier blocks: brief check and scope gate

These blocks are read from this guide at run time by `verification_report.py` and by tests, so they stay here byte-for-byte; the run guides refer to them by marker name. Edit one only through a spec that changes what it checks.

**Forbidden-content check on the composed brief (Step 5c).**

```bash
# NIGHTSHIFT-BRIEF-CHECK-BEGIN
# usage: brief_check <composed-brief-file> <spec-file>
#   ->  BRIEF: clean | BRIEF: contaminated (<hits>)
#
# Scope (R1/R2/AC1/AC5): text delimited by
# <!-- NIGHTSHIFT-BRIEF-SPEC-QUOTE-BEGIN --> ... <!-- NIGHTSHIFT-BRIEF-SPEC-QUOTE-END -->
# is where the brief's verbatim-from-spec quote (the acceptance_criteria_verbatim
# block in the template) belongs. The delimiters alone are NOT proof of
# provenance -- anyone can type the marker comments -- so a hit inside the block
# is only excluded once it is independently verified: the exact line must also
# appear, verbatim, in <spec-file>. A hit inside the block that is NOT found in
# <spec-file> stays contamination (a parent could otherwise smuggle a leak past
# the scan just by wrapping it in the marker comments). If <spec-file> is
# omitted or unreadable, the check FAILS CLOSED: no in-block hit is exempted,
# so the check cannot be weakened by dropping the argument.
#
# Scoping is by LINE POSITION, never by string identity: a line that duplicates
# spec-quoted text but was pasted a second time outside the delimiters is still
# in scope and still flagged (AC5) -- provenance is per-occurrence, not
# per-string, and there is no hand-maintained allowlist of "safe" phrasings
# (R2). Uses only bash/zsh-portable constructs (paired begin/end line numbers
# via `paste`, no indexed-array subscripting, whose 0- vs 1-based semantics
# differ between bash and zsh).
brief_check() {
  file="$1"
  specfile="$2"
  pattern='worker (report|conclu|claim|said|state)|the worker (found|fixed|verified|believes)|nightshift-report|run report says|according to the (worker|run|implementer)|\{worker_[a-z_]*\}|\{report_[a-z_]*\}|all (tests|ACs) (pass|passed) per|implementer (notes|reports)'

  begins=$(grep -nF 'NIGHTSHIFT-BRIEF-SPEC-QUOTE-BEGIN' "$file" | cut -d: -f1)
  ends=$(grep -nF 'NIGHTSHIFT-BRIEF-SPEC-QUOTE-END' "$file" | cut -d: -f1)
  ranges=$(paste -d' ' <(printf '%s\n' "$begins") <(printf '%s\n' "$ends"))

  all_hits=$(grep -nEi "$pattern" "$file")
  if [ -z "$all_hits" ]; then echo "BRIEF: clean"; return 0; fi

  contaminated=""
  excluded=""
  is_contaminated=0
  while IFS= read -r hit; do
    [ -z "$hit" ] && continue
    n="${hit%%:*}"
    line_text="${hit#*:}"
    in_scope=0
    while IFS=' ' read -r b e; do
      [ -z "$b" ] || [ -z "$e" ] && continue
      if [ "$n" -ge "$b" ] && [ "$n" -le "$e" ]; then
        in_scope=1
      fi
    done <<RANGES
$ranges
RANGES
    if [ "$in_scope" -eq 1 ]; then
      verified=0
      if [ -n "$specfile" ] && [ -f "$specfile" ] && grep -Fxq -- "$line_text" "$specfile"; then
        verified=1
      fi
      if [ "$verified" -eq 1 ]; then
        excluded="${excluded}${hit} [spec-quoted, verified against spec file];"
      else
        contaminated="${contaminated}${hit} [inside quote block but NOT found in spec file];"
        is_contaminated=1
      fi
    else
      contaminated="${contaminated}${hit} [not spec-traceable];"
      is_contaminated=1
    fi
  done <<HITS
$all_hits
HITS

  if [ "$is_contaminated" -eq 1 ]; then
    echo "BRIEF: contaminated ($contaminated)"
    [ -n "$excluded" ] && echo "  spec-quoted matches excluded from scope: $excluded"
    return 1
  fi
  echo "BRIEF: clean"
  [ -n "$excluded" ] && echo "  spec-quoted matches excluded from scope: $excluded"
  return 0
}
# NIGHTSHIFT-BRIEF-CHECK-END
```

**Scope gate (Step 6 check 6).**

   ```python
   # NIGHTSHIFT-SCOPE-GATE-BEGIN
   # usage: python3 scope_gate.py <project-root> <spec-relpath> <main-branch> <baseline> <branch>
   #   -> one "ALLOW|AMENDED|DENY <reason> <path>" line per changed path, then:
   #        SCOPE-CHECK: clean | amended | violated | not_run
   #        REASON: <path> (<reason>), <path> (<reason>), ...   (omitted when clean)
   #      exit 0 unless violated; not_run also exits 0 (R9 — a missing resolver
   #      never blocks the run, it only forces the recorded trailer).
   import re
   import subprocess
   import sys
   from pathlib import Path

   project_root, spec_relpath, main_branch, baseline, branch = sys.argv[1:6]
   project_root = Path(project_root).resolve()
   kit_dir = (project_root / spec_relpath).resolve().parent.parent
   sys.path.insert(0, str(kit_dir))
   try:
       import scope_guard  # noqa: E402
   except ImportError:
       print("SCOPE-CHECK: not_run")
       print(f"WARNING: scope_guard.py not found under {kit_dir} — check 6 skipped")
       sys.exit(0)

   scope = scope_guard.scope_from_main(project_root, spec_relpath, main_branch)
   spec_text_main = subprocess.run(
       ["git", "show", f"{main_branch}:{spec_relpath}"],
       cwd=project_root, capture_output=True, text=True,
   ).stdout
   diff = subprocess.run(
       ["git", "diff", "--name-only", "--diff-filter=ACDMR", f"{baseline}..{branch}"],
       cwd=project_root, capture_output=True, text=True,
   )
   paths = [p for p in diff.stdout.splitlines() if p.strip()]

   amend_globs = []
   heading = re.search(r"^## Scope Amendments\s*$([\s\S]*?)(?=^## |\Z)", spec_text_main, re.MULTILINE)
   if heading:
       for line in heading.group(1).split("\n"):
           s = line.strip()
           if not s.startswith("|") or re.match(r"^\|[\s:|-]*\|?$", s):
               continue
           cells = [c.strip() for c in s.strip("|").split("|")]
           if not any(cells) or cells[0] == "Date" or len(cells) < 5 or not cells[1]:
               continue
           amend_globs.append(cells[1])

   # AC3 — a worker branch that edits its own spec's `scope:` on the branch is
   # classified against MAIN's scope regardless (the scope resolution above
   # already only ever reads main), but `scope_guard.classify_write`'s
   # `spec_self` rule would otherwise let the spec's own file diff itself pass
   # unconditionally (SPEC-300-001's carve-out for ordinary bookkeeping edits
   # -- checklists, block_reason, etc.). Check 6 narrows that carve-out: when
   # the branch's own copy of `scope:` differs from the baseline's, the spec file
   # itself is reported as an out-of-scope write (never `spec_self`), because
   # that is exactly the self-widening SPEC-300 forbids. An ordinary edit that
   # leaves `scope:` unchanged keeps the normal `spec_self` allow.
   spec_text_branch = subprocess.run(
       ["git", "show", f"{branch}:{spec_relpath}"],
       cwd=project_root, capture_output=True, text=True,
   ).stdout
   # SPEC-302: compare against a *raw* (unreconciled) scope, not the `scope`
   # variable above — `scope_from_main` may have rolled an uncovered widening
   # back to the last-`ready` value, and a worker branch that only ticks a
   # checklist box in its own spec must not be flagged for a widening it never
   # made and cannot fix.
   # SPEC-413: the comparison point is the BASELINE the branch forked from,
   # not current main. A human-approved amendment committed on main while the
   # worker ran moves main's scope but not the branch's; comparing against
   # main would flag a branch that never touched its `scope:`. Classification
   # and amendment globs above still read main.
   spec_text_baseline = subprocess.run(
       ["git", "show", f"{baseline}:{spec_relpath}"],
       cwd=project_root, capture_output=True, text=True,
   ).stdout
   scope_self_edit = (
       spec_relpath in paths
       and scope_guard.resolve_scope(spec_text_branch) != scope_guard.resolve_scope(spec_text_baseline)
   )

   out_of_scope, amended = [], []
   for path in paths:
       if path == spec_relpath and scope_self_edit:
           decision_allowed, decision_reason = False, "scope_self_edit"
       else:
           decision = scope_guard.classify_write(path, scope, project_root, kit_dir, spec_relpath)
           decision_allowed, decision_reason = decision.allowed, decision.reason
       if decision_allowed:
           print(f"ALLOW {decision_reason} {path}")
           continue
       if any(scope_guard._glob_match(g, path) for g in amend_globs):
           print(f"AMENDED {decision_reason} {path}")
           amended.append((path, decision_reason))
       else:
           print(f"DENY {decision_reason} {path}")
           out_of_scope.append((path, decision_reason))

   status = "violated" if out_of_scope else ("amended" if amended else "clean")
   print(f"SCOPE-CHECK: {status}")
   if status != "clean":
       offenders = out_of_scope if status == "violated" else amended
       print("REASON: " + ", ".join(f"{p} ({r})" for p, r in offenders))
   sys.exit(1 if status == "violated" else 0)
   # NIGHTSHIFT-SCOPE-GATE-END
   ```
