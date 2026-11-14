# Mealie Recipe Importer

This project contains a multi-site recipe importer for Mealie, including batch
imports from the `Receptek` folder in Netscape/Opera bookmark exports.

## Project files

- `mealie_importer.py` — scraping, parsing, and Mealie API integration.
- `test_mealie_importer.py` — offline tests for extraction and bookmark parsing.
- `requirements.txt` — Python dependencies, including OS certificate-store
  support on Python 3.10+.
- `verify_setup.py` — checks dependencies and local configuration without
  displaying secret values.
- `.env.example` — safe configuration template. Copy it to `.env` and provide
  private values locally.
- `.gitignore` — excludes environment files, local recipe snapshots, and editor
  state from publication.
- `README.md` — full usage and configuration guide.
- `QUICK_START.md` — concise setup and command reference.
- `MEALIE_API_FINDINGS.md` — generic notes on the Mealie API workflow.

## Quick commands

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Import one recipe:

```powershell
python mealie_importer.py "https://example.com/recipe"
```

Import the `Receptek` bookmark subtree and record each outcome in a CSV:

```powershell
python mealie_importer.py --bookmarks "C:\path\to\opera_bookmarks.html"
```

Run the configured batch import:

```powershell
python mealie_importer.py
```

See [README.md](./README.md) for configuration details.
