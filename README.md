# Writer

Writer is a local-first drafting product for prose and video scripts in the
user's voice. Start from a blank page or attach a bounded source snapshot from
Uoink. Manual editing, save, Voice DNA scan, critique history, and file export
work when Uoink and Zing are stopped.

This repository is private migration work. It has not been released or
distributed.

## Run locally

```powershell
python -m pip install -e .[dev]
writer serve
```

`writer serve` starts the editor and authenticated HTTP API on loopback port
5181. It prints a local URL whose fragment carries the Writer credential into
that browser tab. The fragment is removed from the address bar after load.

Connect an AI directly to Writer's MCP server:

```powershell
writer serve-mcp --print-config
writer serve-mcp
```

The MCP flow is two-phase. Call `prepare_draft` or `prepare_script`, write with
the AI client already in use, then call `save_piece` or `save_script`. Writer
does not choose a hidden provider.

## Optional Uoink sources

Set these only when Writer should read the local Uoink corpus:

```powershell
$env:WRITER_UOINK_URL = "http://127.0.0.1:5179"
$env:WRITER_UOINK_TOKEN = "<Uoink local token>"
writer serve
```

Writer accepts only the versioned `uoink.corpus.read` v1 contract. It never
opens Uoink's database or token file. Saved source snapshots contain an opaque
`uoink://item/<id>` reference plus bounded display and credit fields, so a
draft reopens without Uoink.

## Ownership

- Writer owns drafts, prose versions, scripts, critiques, voice samples, Voice
  DNA, and shot-list files.
- Uoink owns capture, corpus search, facets, taste, engagement, and assembly
  ranking.
- Zing receives a versioned Markdown shot list only when the user chooses an
  output file. Writer makes no live Zing call.
- Writer has no account, scheduling, delivery, or social action surface.

## Development gate

```powershell
python -m compileall -q src tests
python -m pytest -q
writer doctor
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for contracts, ports, and
rollback boundaries.
