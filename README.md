# Writer

Writer is a local-first drafting product for prose and video scripts in the
user's voice. It can work from a blank page, pasted material, local files, or
optional source references from Uoink.

Status: private migration scaffold. It is not published or distributed.

Core rules:

- Writer owns drafts, pieces, scripts, critiques, voice samples, and Voice
  DNA.
- Uoink owns the corpus, taste, engagement, capture, and assembly ranking.
- Writer reads Uoink only through the versioned `uoink.corpus.read` loopback
  contract. It never opens Uoink's database.
- Zing receives only a user-exported, versioned shot-list Markdown document.
  Writer does not send, publish, or post it.
- Manual editing, save, Voice DNA scan, and file export must work without
  Uoink or an AI client.

Development:

```powershell
python -m pip install -e .[dev]
python -m pytest -q
```

