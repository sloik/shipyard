Load when: following run-3.md for worker local config and owner approval waits.
Covers: the complete continuation section relocated from run-3.md.
Not here: parent workflow and gates (see run-3.md).
Requires: read run-3.md first; all its gates remain in force.

## Local config and approval waits (SPEC-NS-KIT-231)

After ownership verify and before worker launch, the copy command above mirrors
only the configured exact untracked local files, default `.claude/settings.local.json`.
It preserves bytes/mode, never follows symlinks or overwrites tracked/existing
files, and refuses denied paths or secret-scanner findings. It grants no new
permission and adds no `additionalDirectories` or rule. Retain its JSON list of
`path`, `action`, `reason` in the run report; no file contents are logged. Ordinary
copy failures are warnings; nonzero required/config failure stops before launch.
Missing source remains `absent` and is not an error. For a harness-managed
`isolation: "worktree"` creation the kit cannot hook that creation: the parent
must call the same helper against the returned, owner-verified worktree.

Include this declaration instruction in every worker brief:

**Owner approval wait (SPEC-NS-KIT-231).** Before any command that may prompt,
write `waiting_on: owner_approval`, `waiting_command: <one-line command or reason>`
and `waiting_since: <ISO-8601 UTC>` in the same heartbeat file; keep
`heartbeat_state: worker-started`. If a prompt is unexpected, declare the wait
at once. Remove these fields when you resume. Never include environment values;
command text has control characters removed and is limited to 200 characters.
A valid non-terminal declaration is `waiting_on_approval` at any age: show the
sanitized command and wait age (unknown for an absent/invalid timestamp), and
report "owner needed". Do not kill, restart or retry the worker because of this
wait; ask the worker and the owner before any stall action. Terminal states still
win. Without a valid wait declaration, the existing phase/20/40-minute ladder
and silent-worker stall behavior remain unchanged.
