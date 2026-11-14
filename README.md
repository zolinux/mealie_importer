# Mealie Recipe Importer

A Python command-line tool that imports recipes from multiple websites into
Mealie. It supports Schema.org `Recipe` JSON-LD, common Hungarian and German
recipe-page layouts, Mindmegette pages, and locally saved MHTML recipe pages.

## Requirements

- Python 3.8+
- `requests`, `beautifulsoup4`, `urllib3`, and (on Python 3.10+) `truststore`

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

On Python 3.10 and later, `truststore` uses the operating system certificate
store for website requests while keeping TLS verification enabled.

## Configuration

Copy `.env.example` to `.env` and set your own values:

```env
MEALIE_URL=https://your-mealie-instance.example
MEALIE_TOKEN=your_api_token
MEALIE_VERIFY_SSL=true
MHTML_FILE=
RECIPE_URLS=
```

`.env` is ignored by Git. Keep credentials and local file paths private.

- `MEALIE_URL` and `MEALIE_TOKEN` are required.
- `MEALIE_VERIFY_SSL` defaults to `true`. Set it to `false` only if your Mealie
  instance uses a self-signed certificate.
- `MHTML_FILE` is optional. Relative paths are resolved from the script folder.
- `RECIPE_URLS` is an optional comma-separated list of recipe URLs for batch mode.

## Usage

Import a single recipe:

```powershell
python mealie_importer.py "https://example.com/recipe"
```

Import every bookmark in the `Receptek` folder and its nested folders from a
Netscape/Opera bookmark HTML export:

```powershell
python mealie_importer.py --bookmarks "C:\path\to\opera_bookmarks.html"
```

The bookmark command attempts every link without a batch cap and creates a CSV
report beside the bookmark file (or at the path passed to `--report`):

```powershell
python mealie_importer.py --bookmarks "C:\path\to\opera_bookmarks.html" `
  --report "C:\path\to\import_report.csv"
```

Each row includes the bookmark title and URL, final URL after redirects, import
status (`verified`, `failed`, or `blocked`), Mealie slug, verified
ingredient/instruction counts, and any error. The Mealie authorization check runs
before fetching recipe pages; if it fails, all URLs are recorded as blocked.
Pages with missing titles, ingredients, or instructions are recorded as failures
and are not imported as incomplete recipes. HTTP errors, changed URLs, and
non-recipe links are recorded rather than skipped. The command exits with status
1 if one or more entries fail or are blocked.

Passing one URL imports only that recipe. With no positional URL or `--bookmarks`,
the script imports the configured MHTML file if present, processes `RECIPE_URLS`,
and discovers additional recipes from Mindmegette. That legacy discovery batch
remains capped at five web recipes.

## Import behavior

- Creates or updates the recipe in Mealie using its name-derived slug.
- Preserves ingredient text using Mealie's `note` and `originalText` fields.
- Verifies saved ingredient display text and instruction text against the source.
- Prefers recipe instruction microdata over conflicting JSON-LD and rejects
  category labels mistakenly supplied as cooking steps.
- Downloads and uploads the source image when available.
- Uses the Mealie API base URL and token from environment configuration.
- Uses Schema.org recipe data when available, with generic Hungarian/German
  heading fallbacks, Street Kitchen's grouped ingredient and preparation
  layout, and the existing Mindmegette-specific parser.
- Reads labeled recipe sections from Balkonada, FromJuci, Nassolda,
  Receptneked, Cookta, Blogger, Heni Süt Neked, and Limara pages, including
  ingredient groups, `<br>`-separated lists, plain-text Blogger methods, and
  article-based preparation steps. Blog descriptions, serving notes, and
  promotional content are excluded from recipe ingredients and instructions.
- Supports article layouts used by Femina, Bidista, Valódi Hírek, and Ripost,
  including decomposed accented text and article pages with related-content
  sections. Bidista ingredients and preparation are restricted to the primary
  recipe section so linked recommendations and category tags are not imported as
  ingredients or cooking steps. Kálci's recipe page is parsed from its ingredient
  list and written method sections while embedded videos and alternative-method
  tips are ignored.

## API workflow

The importer creates a recipe with `POST /api/recipes`, updates its details with
`PATCH /api/recipes/{slug}`, and uploads its image with
`PUT /api/recipes/{slug}/image`. Ingredient `display` is computed by Mealie;
the importer sets `note` and `originalText` so the ingredient text is visible.

## Limitations

- Site layouts without usable Schema.org data or recognizable ingredient and
  instruction sections are reported as failed; the report records the reason.
- Quantities are preserved as source text rather than normalized into Mealie foods
  and units.
- Ratings and nutrition information are not imported.

## Troubleshooting

- If configuration is missing, copy `.env.example` to `.env` and set the required
  Mealie URL and token.
- `401 Unauthorized` during the bookmark preflight: create an API token in the
  same Mealie instance configured by `MEALIE_URL`, and set `MEALIE_TOKEN` to the
  raw token value (do not include the `Bearer ` prefix). The importer sends it as
  a Bearer authorization header.
- If an image upload fails, recipe details are still verified and the image error
  is reported separately.
- If an ingredient is not visible, rerun the import; the script updates the
  existing recipe and verifies the saved ingredient display.
