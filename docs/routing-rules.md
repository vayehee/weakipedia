# Weakipedia Routing Rules

These rules define how a submitted or selected search value is represented in the next page URL.

## Wikipedia Article

Route:

```text
/dashboard/{lang}/{Wikipedia_Title_Slug}
```

Example:

```text
https://en.wikipedia.org/wiki/Elad_Ratson
/dashboard/en/Elad_Ratson
```

Use the source Wikipedia language from the selected URL. Preserve Wikipedia title slug style, including underscores, special characters, and accents.

## Wikipedia User Page

Route:

```text
/dashboard/{lang}/User:{User_Name}
```

Example:

```text
https://en.wikipedia.org/wiki/User:Edittttor
/dashboard/en/User:Edittttor
```

## Wikidata Item

If the Wikidata item has a Wikipedia sitelink, route to the Wikipedia article dashboard:

```text
/dashboard/{lang}/{Wikipedia_Title_Slug}
```

If the Wikidata item has no Wikipedia sitelink, route to the Wikidata dashboard:

```text
/dashboard/WD:{QID}
```

Example:

```text
/dashboard/WD:Q63383258
```

When multiple Wikipedia sitelinks exist, use a deterministic language priority. Current intended priority:

```text
English, then browser language, then first available sitelink.
```

## Create Selection

Route:

```text
/create/{Wikipedia_style_title_slug}
```

Example:

```text
Create: Elad Ratso
/create/Elad_Ratso
```

Render the user query as Wikipedia would render a new page title slug.

## Wikipedia Editor Entry

Route:

```text
/editor/
```

This route is used when the visitor clicks `I am a Wikipedia editor`.

## Redirects

Resolve redirects before routing. The dashboard route must use the canonical resolved Wikipedia title.

## Disambiguation Search Results

When a suggestion is a disambiguation page:

1. Extract the disambiguation page from search suggestions.
2. Omit the disambiguation page itself from the suggestion tray.
3. Enrich the suggestion tray with candidate pages extracted from the omitted disambiguation page.

