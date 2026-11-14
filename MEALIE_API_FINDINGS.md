# Mealie API Integration Notes

The importer uses these relative API routes:

| Purpose | Method and route |
|---|---|
| Create a recipe shell | `POST /api/recipes` |
| Update recipe details | `PATCH /api/recipes/{slug}` |
| Read a recipe for verification | `GET /api/recipes/{slug}` |
| Upload a recipe image | `PUT /api/recipes/{slug}/image` |
| List and search recipes | `GET /api/recipes` |

The API base URL and token are supplied through `MEALIE_URL` and `MEALIE_TOKEN`.
Do not put real credentials or instance addresses in source files or published
documentation.

## Recipe payload notes

The create request supplies the recipe name. The draft update then includes fields
such as `recipeIngredient`, `recipeInstructions`, `recipeServings`, `recipeYield`,
and `orgURL`.

For visible ingredient text, send both `note` and `originalText`:

```json
{
  "recipeIngredient": [
    {"note": "2 cups flour", "originalText": "2 cups flour"}
  ],
  "recipeInstructions": [
    {"text": "Mix and bake."}
  ]
}
```

Mealie computes the returned `display` value; sending only `display` does not
reliably populate the UI. The importer reads the saved recipe and verifies that
ingredient display text and instructions were persisted.

## TLS verification

TLS certificate verification is enabled by default. `MEALIE_VERIFY_SSL=false`
can be set in a private `.env` file for a Mealie instance using a self-signed
certificate. Avoid disabling verification for public or untrusted connections.
