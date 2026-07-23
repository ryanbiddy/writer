# Recount architecture

Recount is one product with two work modes: prose and script. Both use the
same source snapshots, voice rules, revision model, and local persistence.
The candidate display name does not alter the existing `writer` technical
identity; [the rename plan](RECOUNT-RENAME-PLAN.md) lists every frozen
compatibility surface and the separate re-ratification work.

## Ownership

Recount owns:

- mutable drafts;
- saved/versioned pieces;
- scripts, critique records, and shot-list exports;
- user voice samples (the Uoink feature formerly called style anchors);
- Voice DNA scanning and prompt guidance;
- its own SQLite database, loopback token, HTTP API, and MCP server.

Recount does not own:

- capture, the browser extension, the corpus, facets, taste, or engagement;
- Uoink's SQLite database or token;
- video measurement or rendering;
- publishing accounts, scheduling, posting, or delivery receipts.

## Product calls

The optional Uoink connection is loopback HTTP on port 5179 with Uoink's
per-install token supplied by the user or process environment. Uoink content
enters Recount only through `uoink.corpus.read` v1 envelopes for search, get,
facets, taste, and assemble. Recount can send its own durable `cite` events
through the separately ratified `uoink.engagement.ingest` v1 contract. Suite
manifest, health, and runtime-lease reads are operational discovery, not
corpus access.

Recount's loopback server uses port 5181 and the existing Writer-owned token
contract. AI clients register the `writer` stdio MCP server directly. There
is no suite MCP proxy and no shared token.

## Persistence

Recount data continues to use Writer's operating-system application-data
directory. Source references are Recount-owned display snapshots. An attached
Uoink item stores an opaque `uoink://item/<id>` reference and the minimum
title, creator, URL, credit, and excerpt needed to reopen the draft while
Uoink is stopped. No Uoink filesystem path crosses the boundary.

The first migration creates Recount-owned tables under the existing Writer
technical identity. Uoink's old writing tables stay untouched for the
compatibility window and are never read by Recount.

## Migration gates

1. Contract and repository scaffold.
2. A strict Uoink v1 client with a passing black-box contract fixture.
3. Recount-owned persistence and Voice DNA.
4. Prose, script, critique, and export surfaces.
5. HTTP, MCP, and standalone editor.
6. Uoink compatibility stays green until Recount passes its own full gate.

Every numbered stage is a rollback commit:

| Stage | Commit | Gate |
|---|---|---|
| Scaffold | `e599b0a` | schemas, migration, 8 tests |
| Uoink contract client | `db6e513` | strict v1 fixture, 14 tests |
| Persistence and Voice DNA | `b7b86dc` | Recount-only SQLite, 26 tests |
| Prose, scripts, and critique | `86b2fe8` | standalone domains, 37 tests |

The HTTP, MCP, editor, compatibility, and final dual-repository gates are
recorded when their commits land.
