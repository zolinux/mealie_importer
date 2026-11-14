# Project Summary

The importer supports multiple input sources:

1. Recipe pages from multiple sites using Schema.org JSON-LD or common Hungarian
   and German recipe page conventions.
2. Netscape/Opera bookmark HTML exports, restricted to the `Receptek` folder
   and all nested folders.
3. Locally configured MHTML files saved from a browser.

The command-line interface accepts one optional positional URL. When provided,
only that recipe is imported. With no URL, the script runs its configurable
batch workflow.

## Implementation

- Parses recipe names, ingredient text, instructions, and image links.
- Creates or updates recipes through the Mealie API.
- Uses Mealie's ingredient `note` field with `originalText` so ingredient text is
  visible in the UI.
- Verifies persisted ingredient display values and instruction text.
- Writes a CSV outcome report for each bookmark URL, including failures.
- Reads the Mealie base URL, token, optional MHTML path, and optional batch URLs
  from environment configuration.

## Private configuration

Copy `.env.example` to `.env` and set values for your own environment. The
`.gitignore` excludes `.env`, local MHTML snapshots, and workspace-specific
editor settings.

For installation, configuration, commands, and limitations, see
[README.md](./README.md) and [QUICK_START.md](./QUICK_START.md).
