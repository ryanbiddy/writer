# Recount

Recount is a local-first drafting product for prose and video scripts in the
user's voice. Start from a blank page or attach a bounded source snapshot from
Uoink. Manual editing, save, Voice DNA scan, critique history, and file export
work when Uoink and Zing are stopped.

This is a candidate display-name change, not a technical rename. The installed
package, Python module, CLI, data locations, environment variables, MCP and
HTTP identities, and cross-product contracts remain `writer` / `Writer` until
Ryan confirms the final name and the suite contract is re-ratified. See
[the rename plan](docs/RECOUNT-RENAME-PLAN.md).

This repository contains pre-release migration work. Recount has not been
released or distributed.

## Run locally

```powershell
python -m pip install -e .[dev]
writer serve
```

`writer serve` starts the editor and authenticated HTTP API on loopback port
5181. It prints the local editor URL and the credential source (the local
credential file, or `WRITER_TOKEN` when explicitly configured), but never
prints the credential or places it in a URL. Open the editor, copy the value
from that source, and paste it into the editor's Credential field.

Connect an AI directly to Recount's MCP server through the existing `writer`
command:

```powershell
writer serve-mcp --print-config
writer serve-mcp
```

The MCP flow is two-phase. Call `prepare_draft` or `prepare_script`, write with
the AI client already in use, then call `save_piece` or `save_script`. Recount
does not choose a hidden provider.

## Optional Uoink sources

Set these only when Recount should read the local Uoink corpus:

```powershell
$env:WRITER_UOINK_URL = "http://127.0.0.1:5179"
$env:WRITER_UOINK_TOKEN = "<Uoink local token>"
writer serve
```

Recount accepts only the versioned `uoink.corpus.read` v1 contract. It never
opens Uoink's database or token file. Saved source snapshots contain an opaque
`uoink://item/<id>` reference plus bounded display and credit fields, so a
draft reopens without Uoink. A snapshot source URL is either null or an
absolute HTTP(S) URL; Recount rejects file URLs, filesystem paths, and other
schemes at both the Uoink response boundary and its own storage schema.

## Ownership

- Recount owns drafts, prose versions, scripts, critiques, voice samples, Voice
  DNA, and shot-list files.
- Uoink owns capture, corpus search, facets, taste, engagement, and assembly
  ranking.
- Zing receives a versioned Markdown shot list only when the user chooses an
  output file. Recount makes no live Zing call.
- Recount has no account, scheduling, delivery, or social action surface.

## Development gate

```powershell
python -m compileall -q src tests
python -m pytest -q
writer doctor
writer doctor --json
python packaging/clean_host_check.py --report clean-host-local.json
```

The clean-host gate builds a wheel, installs `ryan-writer[mcp]` into a bare
temporary venv, leaves the repository off the tested import path, verifies the
human and JSON doctor surfaces, and drives all 17 MCP tools through a real
stdio handshake. CI repeats that gate on Ubuntu, Windows, and macOS.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for contracts, ports, and
rollback boundaries.
