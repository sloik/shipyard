Load when: using ranked search, declared snapshots or board load diagnostics.
Covers: query/filter semantics, API/CLI/export scope and existing load diagnostic boundaries.
Not here: benchmark commissioning/acceptance (use the versioned BUG-NS-KIT-225 protocol).
Requires: installed board/search helpers; a running board for online search.

# Board search and diagnostic boundaries

Graph **Load diagnostics**: invocation→first draw+next frame; fetch/decode,
preparation/paint. Diagnostic budget: 2,000ms; warn above it; aggregate p95 needs
five successes. Exclude hidden windows; errors/cancellations separate.
128 successes/key reset on process restart; server time separate.
Exports: local timing; server aggregates unavailable; no POST.


### Ranked search and declared snapshot scope (BUG-NS-KIT-225)

Trimmed case-insensitive canonical IDs, kind+numeric-tail abbreviations and numeric
child tails match structured identities in the selected namespace plus legacy IDs.
Root224 excludes1224 and224-001; ID queries do not match prose digits. Exact
canonical identity ranks first; an exact legacy abbreviation precedes its qualified
alias. Text uses a literal title/body phrase, title matches first, then canonical
ID order. Empty search restores the filtered board; API/CLI payload may be empty.

`GET /api/search` keeps its default list and original hit fields. Add
`metadata=true`, JSON `filters` (statuses/types/tags arrays or `all`, version
`all`/`unassigned`/exact label, include_archived boolean), `offset` and positive
`limit` for scope/count/excluded-count/continuation metadata. Tags use ANY semantics;
independent facets intersect. `v:<label>`/`t:<tag>` disambiguate reserved labels;
`untagged` selects absent tags. The server owns project scope. Omitted facets mean
All, never saved browser state. UI search sends its active facets; hidden status
columns exclude, collapsed columns include; clear-filters retains the query.

CLI `search` supports repeated `--status`, `--type`, `--tag`, `--version`,
`--hide-archived`, `--offset`, `--limit` and explicit `--offline`. Only offline mode
accepts `--archive-observed-at <finite UTC epoch seconds>` for a declared archive
snapshot; using it without `--offline` is a typed refusal. Defaults use the real
observation clock. Search metadata reports that archive observation separately;
this never changes performance timers or global clocks. The online API rejects a
query-supplied archive clock; only a fixture-owned cache may declare a fixed one. Static export retains
complete searchable bodies, metadata policy and one archive observation, so its
facets and ordered results describe that snapshot. Pagination reports total and
continuation instead of silently truncating. Out-of-order or failed UI responses
cannot replace the latest correct query/filter state; errors remain visible.
