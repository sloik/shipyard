Load when: setting up or sharing optional external evidence for a spec.
Covers: manual source setup, evidence limits, provenance, consumer approval and sharing boundaries.
Not here: declaration contract or pinned verifier briefs; see `run-4.md`.
Requires: read `run-4.md` for the declaration contract and trusted dispatch prerequisites.

### Optional external asset evidence: setup and sharing

This is an opt-in **per-spec evidence declaration**, using the existing
[declaration contract](run-4.md#external-evidence-declaration-contract). There is no
configured default asset store, new configuration key or automatic acquisition.
It supplies selected reference evidence to a verifier; it does not supply app
resources or a runtime asset service.

1. **Supply the source yourself.** Make a local Git repository available on each
   dispatch host, with the selected files committed and clean. The source needs
   no Nightshift installation. An already available repository works offline;
   fresh setup is manual. Keep its HEAD stable throughout import: competing
   writers or source movement during import have no coordination guarantee.
2. **Select only necessary evidence.** Use repository-relative file paths or a
   bounded directory. One directory may contain at most **256 tracked members**;
   all selected files and directories together may project at most **8 MiB**
   (8,388,608 bytes). Listing individual files does not bypass the cumulative cap.
3. **Declare before ready promotion.** Commit the declaration in the spec's
   `context.required_inputs`, identically in baseline and candidate. For an
   illustrative operator-supplied layout:

   ```yaml
   context:
     required_inputs:
     - "external-evidence:{{HOME}}/local-evidence/project-assets#references/approved-screen.png"
   ```

   `{{HOME}}`, `{{ARGO_HOME}}` and `{{PROJECT_ROOT}}` are the supported root
   anchors. Only the repository root expands; the member path never expands.
   `{{PROJECT_ROOT}}` means the dispatch's subject worktree, not the main
   checkout. Reach an external sibling through an available HOME or ARGO_HOME
   layout, never `..`, an invented environment anchor or a literal host locator.
4. **Use normal dispatch with the spec path.** The existing coordinator supplies
   it to `verification_report.py prepare-dispatch`. A hand-written invocation
   must also supply `--spec-path` alongside its normal trusted-dispatch
   prerequisites. Omitting it imports no external inputs; do not give a verifier
   a source path directly to work around a refusal.
5. **Inspect the projected manifest.** Inside each verifier arm,
   `.nightshift-verifier-inputs/MANIFEST.json` identifies the selected copies by
   source repository identity, source commit, object ID, projected path, SHA-256
   and byte count (directory inputs list their members). It removes the source
   filesystem locator and declaration string. The copies are regular read-only
   files, separate from native subject content, with no source symlink or shared
   object database. Completed projections remain usable independently of source
   availability.
6. **Cross-check consumer approval when it matters.** Dispatch pins the source's
   then-current HEAD and records object/hash provenance. That proves which bytes
   were imported, not that a consumer approved that version. If a consumer's
   tracked approval manifest says `assets_commit: <approved-commit>` and its
   selected `files` entry records a SHA-256, require both the projected
   `source_commit == assets_commit` and the corresponding projected file's
   `sha256 == files[path].sha256`. A directory input uses its matching `members`
   entry. A commit **or** digest mismatch rejects use as approved evidence.
   This is a required consumer practice when approval-version equivalence
   matters; the generic importer does not enforce the consumer manifest.

**Which kind of sharing is supported?**

| Consumer or instance | Existing support and boundary |
| --- | --- |
| Linked worktrees | Each dispatch resolves its declared anchors. CraftJobQuote's project tooling separately follows `git-common-dir` to the main checkout's sibling store; this is not generic kit resolution. |
| Independent clones or installs | Supply an available local source and resolvable declarations for each clone. CraftJobQuote's `CRAFT_ASSETS_REPO` override affects its project manifest tooling only, not kit declarations. |
| Separate consumer projects | Each project may explicitly declare selected committed files from the same stable local Git source and owns its approval/applicability checks. This is supported mechanism, not observed multi-project adoption. |
| Verifier arms and repeated runs | Both arms receive contained copies of the same predeclared evidence. Repeated dispatches pin the HEAD available at their own import time. |
| Multiple hosts or users | Each host needs manual local setup with supported anchors. No downloader, remote distribution or cross-host writer coordination is supplied. |
| Deployed app instances | No runtime shared storage, CDN, client cache or application distribution is provided by verifier evidence projection. |

CraftJobQuote is a project-specific comparison: `assets_manifest.py verify`
checks its approved assets commit, file hashes/sizes and whole-store cleanliness.
The kit checks cleanliness of **declared paths**, not the entire source checkout.
A main-only CraftJobQuote clone may run its named missing-store integrity-test
skip, but its standalone integrity verification fails without the store; neither
establishes asset integrity. A required kit external-input declaration refuses
unavailable source/content, rather than silently skipping it.

**Owner decisions and safe boundaries.** Stable committed reads are supported.
Competing writers, consumers requiring different approved versions, publisher
coordination and backup/retention/recovery remain owner decisions. There is no
version-selection or writer-lock policy here; do not assume one source HEAD can
satisfy different approved commits. A local-only source does not establish a
backup. This guide supplies no cleanup, history-rewrite or garbage-collection
procedure.

Keep all existing [declaration refusals](run-4.md#external-evidence-declaration-contract)
in force: identical committed declarations, same-spec/report withholding,
traversal and symlink containment, missing/untracked/mutable content, supported
entry types, namespace/projection collisions and both size bounds. A declaration
never overrides these safeguards. Review the privacy, origin and rights of only
the selected evidence before exposing it. Contained, sanitized projection grants
no publication authority or rights to reuse another party's assets; examples must
contain no private locators, secrets, customer content or raw private assets.

