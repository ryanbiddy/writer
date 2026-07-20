# CX-2 / WR-1: Writer code review

Reviewed 2026-07-19 against Writer `9b76a9a` and the ratified suite
integration contract. The review covered production code, tests, packaging,
the 17-tool MCP surface, Uoink boundaries, and the open FF-8 source-URL fix.

## Verdict

Writer's product boundary is sound after the fixes in this review. All 17 MCP
tools are Writer-owned, their descriptions match their successful behavior,
and the clean-host smoke calls every tool through an installed wheel. Five
correctness defects were reproducible: malformed nested MCP data escaped the
tool-data contract; `writer_status` undercounted records above 500; malformed
HTTP list queries could drop the connection or be silently clamped; an invalid
`active_only` value silently meant false; and a valid-looking success envelope
could hide an HTTP failure from Uoink. Each now has a regression.

The source-URL enforcement in Writer PR #5 is also the implementation I would
choose. It centralizes one validator, rejects non-HTTP(S) values at both
boundaries, preserves the contract's null representation, and normalizes the
pre-launch empty-string form on read. I found no code change to request there.
Its six jobs did not execute because the repository owner's GitHub account had
a billing or spending-limit block; that is an external gate, not a test result.

## Boundary proof

Uoink content enters through one client and one version:

- `UoinkClient.search`, `get`, `facets`, `taste`, and `assemble` call only
  `/api/corpus/v1/*` and exact-validate `uoink.corpus.read` version 1.
- Attached items become bounded `SourceSnapshot` records. The stored reference
  is an opaque `uoink://item/<id>` value, not a corpus row, database path, or
  token.
- Writer imports no Uoink or legacy Uoink module. The repository-boundary test
  scans every production Python file for foreign import roots, foreign storage
  markers, and SQLite connections outside Writer's storage module.
- The only other Uoink interactions are separately ratified boundaries:
  outbound `uoink.engagement.ingest` version 1 cite events, plus suite manifest,
  health, and runtime-lease discovery. They do not expose corpus content.
- Writer has no Zing import or live call. `export_shot_list` writes only the
  caller's explicit Markdown path.

`docs/ARCHITECTURE.md` now states the content, engagement, and operational
boundaries separately. The old wording named only corpus reads even though the
ratified cite-event path was present in code.

## Findings and fixes

### CX2-1 — nested MCP failures escaped as protocol errors (P2)

`save_piece`, `save_script`, `save_draft`, and `add_voice_sample` accept nested
JSON objects. Unknown fields and wrong nested types raised `TypeError` or
`AttributeError` outside the handler's error-as-data boundary. A real MCP call
therefore returned `isError: true` instead of Writer's documented
`{"ok": false, ...}` result.

The handler now converts request-shape exceptions to an explicit invalid-request
tool result. Five regressions cover unknown piece and script fields, a non-object
beat, a malformed Uoink snapshot, and an unknown voice-sample field.

### CX2-2 — `writer_status` reported page size as total count (P2)

The status tool counted list results capped at 500. A database with 501 drafts
reported 500 while the tool description promised record counts.

`WriterStore.entity_counts()` now uses exact `COUNT(*)` subqueries under the
store lock. The regression inserts 501 drafts and requires 501.

### CX2-3 — list-query failures were not stable JSON (P2)

`limit=nope` raised inside `do_GET` and dropped the HTTP connection. Values such
as 0 or 501 were silently clamped by storage and returned 200. All three list
routes now require an integer from 1 through 500 and return the same
`invalid_request` envelope otherwise.

### CX2-4 — invalid boolean query silently changed meaning (P3)

`active_only=maybe` was treated as false. The route now accepts only `0` or `1`
and returns a stable 400 response for any other value.

### CX2-5 — HTTP failure could masquerade as Uoink success (P2)

Both Uoink response validators accepted an `ok: true` body even when the
transport status was 500 or 503. That made a failed dependency look successful
and could feed stale or intermediary-generated data into Writer.

Corpus and engagement validators now reject success envelopes on non-2xx
statuses as `contract_mismatch` while preserving the actual status. Regressions
cover both contracts.

## MCP tool audit

| Tool | Description claim checked | Result |
|---|---|---|
| `prepare_draft` | Prepares model-neutral prose context; sources optional | Pass: blank-page and manual-source paths remain standalone |
| `save_draft` | Saves or updates an editable local draft | Pass: create and ID-based update round-trip locally |
| `get_draft` | Reads one draft by integer ID | Pass: hit returns the draft; miss is tool data |
| `save_piece` | Saves an immutable prose version | Pass: storage versions records; malformed nested data is now tool data |
| `list_pieces` | Lists immutable prose versions | Pass: kind filter and bounded list return stored versions |
| `validate_composition` | Computes local length and credit-footer checks without sending | Pass: deterministic local calculation; no network or browser path |
| `prepare_script` | Prepares script context; Uoink assembly is optional | Pass: source-free path is local; requested assembly uses corpus v1 |
| `save_script` | Saves an immutable structured script version | Pass: structured fields and parent version persist locally |
| `critique_script` | Prepares context without findings; persists with findings | Pass: both modes are covered |
| `revise_script` | Prepares context without a revision; saves a child with one | Pass: both modes are covered |
| `derive_shot_list` | Creates a child script with format-based cues | Pass: beat-derived scenes use the format cue table |
| `export_shot_list` | Writes versioned Markdown only to the chosen path; never calls Zing | Pass: installed smoke verifies the file and no Zing call exists |
| `add_voice_sample` | Adds a local voice sample | Pass: record persists in Writer's database |
| `list_voice_samples` | Lists local voice samples | Pass: active filter and full list work |
| `remove_voice_sample` | Deletes one local voice sample | Pass: existing record deletes; miss is tool data |
| `scan_voice` | Runs local Voice DNA warnings without a model | Pass: packaged rules return deterministic warnings |
| `writer_status` | Reports path-free health, peer state, and counts | Pass after CX2-2: counts are exact and no path is returned |

The clean-host MCP probe performs `initialize`, `tools/list`, and a successful
`tools/call` for every row in this table. The focused semantic tests cover the
two-phase tools, persistence, failure results, source-free operation, derived
shots, file export, and exact status counts.

## Test evidence

Red-before-green evidence:

- MCP/HTTP batch: 9 failed and 15 passed before CX2-1 through CX2-3.
- Uoink status batch: 2 failed before CX2-5.
- Boolean query: 1 failed before CX2-4.

Final local evidence:

- `python -m pytest -q`: 101 passed.
- `packaging/clean_host_check.py`: 7 steps passed, 0 failed on Python 3.12.
- Installed-wheel MCP result: all 17 tools listed and called successfully.
- Repository boundary test: no foreign imports, foreign storage markers, or
  non-Writer SQLite connection.

## Residual risk

The nested tool payloads are intentionally generic JSON objects at the MCP
schema layer. The reviewed failure classes now stay inside Writer's result
contract, but negative-value coverage is example-based rather than generated
across every dataclass field. A future schema-hardening pass should derive
nested JSON schemas or add property-based tests; this is not a contradiction
of any current tool description.

Writer PR #5 remains required before the suite can claim complete source-URL
enforcement. Its code review passed, but GitHub has not run the jobs.
