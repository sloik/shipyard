#!/bin/sh
# install-write-scope-guard.sh (SPEC-300-003)
# Wire the protect-write-scope guard into THIS repo's pre-commit hook:
#   * pre-commit -> rejects a commit that stages a path outside the active
#                   spec's declared write scope (see protect-write-scope.sh)
# Idempotent. Chains onto an existing pre-commit hook (branch guard, kit
# lint/secrets, canonical-copy parity) rather than overwriting it, inserting
# above a trailing `exit 0` the same way install-canonical-copy-guard.sh does.
# Run once per repo.
#
# The pre-commit hook must be one of our recognised, tracked shims — either
# already carrying a known Nightshift/Argo marker, or a plain hand-authored
# hook that still ends in a bare `exit 0` we can chain above. A hook that is
# neither (no recognised marker AND no trailing `exit 0`) is refused rather
# than silently altered; doctor.py's D7 remedy text points back at this
# refusal so a human merges it by hand.
set -eu

hooks="$(cd "$(git rev-parse --git-common-dir)" && pwd)/hooks"
mkdir -p "$hooks"

# Resolves the guard from either the Argo Home layout or a synced project's
# .nightshift/ layout, so the same installer works across repos.
# BUG-322: the single quotes are load-bearing. This snippet is written as
# literal text into the target hook, so `$(git rev-parse ...)` and `$g` must
# expand when that hook RUNS, never when this installer runs -- double quotes
# would bake the installing repository's paths into every installed hook.
# shellcheck disable=SC2016
SNIPPET='g=$(git rev-parse --show-toplevel 2>/dev/null); for c in "$g/ManagedProjects/Nightshift/canonical/hooks/protect-write-scope.sh" "$g/canonical/hooks/protect-write-scope.sh" "$g/.nightshift/hooks/protect-write-scope.sh"; do [ -x "$c" ] && { "$c"; s=$?; [ "$s" -eq 96 ] && exit 96; break; }; done'
MARK="# SPEC-300-003 protect-write-scope"

is_recognised_hook() {
  hook=$1
  # Known markers from the existing guard family, plus the managed
  # Nightshift pre-commit hook's own identifying comment.
  grep -qE '# SPEC-118 protect-primary-branch|# SPEC-158 secret-pii-scan|# SPEC-CTX-CORE-036 canonical-copy-parity|Nightshift Kit — Pre-commit hook' "$hook" 2>/dev/null && return 0
  # A plain hand-authored hook that still ends in a bare `exit 0` is a known,
  # chainable shape (SPEC-160's insert-before-exit-0 pattern).
  grep -qE '^exit 0[[:space:]]*$' "$hook" 2>/dev/null && return 0
  return 1
}

insert_before_trailing_exit() {
  hook=$1 mark=$2 snippet=$3 tmp="$hook.tmp.$$"
  if awk -v mark="$mark" -v snip="$snippet" '
      { lines[NR] = $0; if ($0 !~ /^[[:space:]]*$/) last = NR }
      END {
        if (!last || lines[last] !~ /^[[:space:]]*exit 0[[:space:]]*$/) exit 1
        for (i = 1; i <= NR; i++) {
          if (i == last) { print ""; print mark; print snip; print "" }
          print lines[i]
        }
      }
    ' "$hook" > "$tmp"; then
    cat "$tmp" > "$hook"
  else
    printf '\n%s\n%s\n' "$mark" "$snippet" >> "$hook"
  fi
  rm -f "$tmp"
}

hook="$hooks/pre-commit"

if [ -f "$hook" ] && grep -qF "$MARK" "$hook"; then
  echo "  pre-commit: write-scope guard already installed"
  exit 0
fi

if [ -f "$hook" ] && ! is_recognised_hook "$hook"; then
  echo "  pre-commit: unrecognised foreign hook; refusing to chain the write-scope guard into: $hook" >&2
  echo "  Merge by hand: add the marker '$MARK' and this snippet before the hook exits:" >&2
  echo "    $SNIPPET" >&2
  exit 1
fi

if [ ! -f "$hook" ]; then
  printf '#!/bin/sh\n%s\n%s\nexit 0\n' "$MARK" "$SNIPPET" > "$hook"
  chmod +x "$hook"
  echo "  pre-commit: created with write-scope guard"
else
  insert_before_trailing_exit "$hook" "$MARK" "$SNIPPET"
  echo "  pre-commit: chained write-scope guard into existing hook"
fi
