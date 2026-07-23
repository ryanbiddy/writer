# Recount rename plan

Status: draft for Ryan's decision. `Recount` is a candidate name, not a
ratified product or protocol identity.

## What this draft changes

The cosmetic tier changes only the name people see in this repository's
README, architecture guide, and local editor. It does not add a `recount`
command, package, module, data migration, alias, protocol, or release.
Reverting the draft restores the old label without touching user data.

## Compatibility surfaces that stay frozen

The following identifiers remain unchanged in this tier:

| Surface | Current identity |
|---|---|
| Distribution and Python package | `ryan-writer`, `writer` |
| CLI and direct MCP server | `writer`, MCP server id `writer` |
| Suite service | id/name `writer` / `Writer`, port 5181 |
| HTTP API and credential header | `writer.api`, `/api/writer/v1`, `X-Writer-Token` |
| Local configuration | `WRITER_TOKEN`, `WRITER_DATA_DIR`, `WRITER_UOINK_URL`, `WRITER_UOINK_TOKEN` |
| Uoink's peer configuration | `UOINK_WRITER_URL`, `UOINK_WRITER_TOKEN` |
| Stable references and events | `writer://script/<id>`, `source_product: "writer"` |
| Shot-list wire format | `writer.shot-list` and `writer.shot-list/1` |
| Local storage | existing Writer application-data directory and `writer.token` |

These are live compatibility surfaces, not stale copy. Writer defines them in
`pyproject.toml`, `src/writer/suite_service.py`,
`src/writer/http_api.py`, `src/writer/schemas.py`,
`src/writer/storage.py`, and `src/writer/auth.py`. Uoink consumes the API,
header, capabilities, and peer variables in `writer_peer.py`. Zing consumes
the shot-list and stable-reference formats in `src/myzing/shot_list.py` and
`tools/eval/suite_contracts.py`.

At Writer `1d2ce1a`, Uoink `720b05b`, and Zing `8775c43`, a tracked-file grep
for those technical identities finds 77 matches in 23 Writer files, 57 in 9
Uoink files, and 78 in 19 Zing files. That is 212 matches across 51 tracked
files, before counting handoff documents or duplicate worktrees.

## Contract rename: separate decision and coordinated change

A technical rename requires all of the following before implementation:

1. Ryan confirms the final product name. If it is not Recount, this cosmetic
   draft closes without creating an alias to unwind.
2. The suite's ratified integration contract is revised and explicitly
   re-ratified. The current contract does not permit silent changes to
   `writer://`, `writer.api`, `writer.shot-list`, or `source_product`.
3. Ryan chooses a compatibility policy: a time-bounded dual-name migration or
   a coordinated hard cutover. That choice must cover existing shot-list
   files, stored outbox events, MCP configurations, environment variables,
   token/data paths, and stable references.
4. Writer, Uoink, and Zing change on coordinated branches. Uoink's pinned
   Writer provider fixture must be regenerated, LF-normalized, re-hashed, and
   pinned to the new Writer commit.
5. The three product suites, clean-install matrix, direct MCP handshakes, and
   family suite-smoke pass on the exact coordinated heads. The family gate
   must still execute all 11 steps and 18 assertions.

Until those decisions and gates exist, changing a technical identifier would
create two incompatible suites that happen to share a display name. This
draft intentionally stops before that boundary.
