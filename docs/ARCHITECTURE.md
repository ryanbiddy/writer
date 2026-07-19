# Writer architecture

Writer is one product with two work modes: prose and script. Both use the
same source snapshots, voice rules, revision model, and local persistence.

## Ownership

Writer owns:

- mutable drafts;
- saved/versioned pieces;
- scripts, critique records, and shot-list exports;
- user voice samples (the Uoink feature formerly called style anchors);
- Voice DNA scanning and prompt guidance;
- its own SQLite database, loopback token, HTTP API, and MCP server.

Writer does not own:

- capture, the browser extension, the corpus, facets, taste, or engagement;
- Uoink's SQLite database or token;
- video measurement or rendering;
- publishing accounts, scheduling, posting, or delivery receipts.

## Product calls

The optional Uoink connection is loopback HTTP on port 5179 with Uoink's
per-install token supplied by the user or process environment. Writer accepts
only the `uoink.corpus.read` v1 envelopes for search, get, facets, taste, and
assemble.

Writer's future loopback server uses port 5181 and a Writer-owned token. AI
clients register Writer's stdio MCP server directly. There is no suite MCP
proxy and no shared token.

## Persistence

Writer data defaults to the operating system's local application-data
directory. Source references are Writer-owned display snapshots. An attached
Uoink item stores an opaque `uoink://item/<id>` reference and the minimum
title, creator, URL, credit, and excerpt needed to reopen the draft while
Uoink is stopped. No Uoink filesystem path crosses the boundary.

The first migration creates Writer tables only. Uoink's old writing tables
stay untouched for the compatibility window and are never read by Writer.

## Migration gates

1. Contract and repository scaffold.
2. A strict Uoink v1 client with a passing black-box contract fixture.
3. Writer-owned persistence and Voice DNA.
4. Prose, script, critique, and export surfaces.
5. HTTP, MCP, and standalone editor.
6. Uoink compatibility stays green until Writer passes its own full gate.

Every numbered stage is a rollback commit.

