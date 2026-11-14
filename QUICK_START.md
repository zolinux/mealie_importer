# Quick Start

## Setup

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env`. Set the required `MEALIE_URL` and `MEALIE_TOKEN`;
keep `.env` private and do not publish it.

Optional settings:

- `MHTML_FILE`: path to a saved MHTML recipe file. Relative paths are based on the
  script directory.
- `RECIPE_URLS`: comma-separated recipe URLs for batch imports.
- `MEALIE_VERIFY_SSL`: defaults to `true`; disable only for an instance with a
  self-signed certificate.

## Import one recipe

```powershell
python mealie_importer.py "https://example.com/recipe"
```

This imports only the URL provided. Schema.org recipe pages on different sites
are supported, as are common Hungarian and German ingredient/instruction layouts.

## Import an Opera/Netscape bookmark folder

```powershell
python mealie_importer.py --bookmarks "C:\path\to\opera_bookmarks.html"
```

The command imports every link inside `Receptek`, including nested folders. It
does not cap the batch and writes a CSV report next to the bookmark file. To
choose the report path:

```powershell
python mealie_importer.py --bookmarks "C:\path\to\opera_bookmarks.html" `
  --report "C:\path\to\import_report.csv"
```

Every link is reported as verified, failed, or blocked. A recipe is only imported
if a title, ingredients, and instructions were extracted; saved ingredient
display text and instruction text are checked against Mealie's response. Failures
include the URL, redirect destination, and error reason. A Mealie authorization
preflight blocks the batch before downloading pages when the API token is invalid.
The command returns a nonzero exit code if any link fails or is blocked.

## Default batch mode

```powershell
python mealie_importer.py
```

Without a URL argument, the script imports the configured MHTML file (if any),
processes URLs from `RECIPE_URLS`, then discovers additional Mindmegette recipes.
That legacy discovery batch is limited to five web recipes.

## Troubleshooting

- `MEALIE_URL` or `MEALIE_TOKEN` missing: check your local `.env` file.
- Ingredient text missing: rerun the import; saved ingredients are verified using
  the display value returned by Mealie.
- Image upload error: recipe details are still saved, and the image error is
  reported separately.
