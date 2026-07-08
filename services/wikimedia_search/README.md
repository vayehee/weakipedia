# Wikimedia Search

Python backend service for resolving user input to Wikipedia articles, Wikipedia user pages, and Wikidata records.

## Local Run

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e .
uvicorn wikimedia_search.api:app --reload --port 8080
```

## Endpoints

```text
GET /health
GET /resolve?input=Douglas%20Adams
POST /static-targets
```

Create or reuse a temporary static Wikipedia article target:

```json
{
  "selectedUrl": "https://en.wikipedia.org/wiki/Melissa_DeRosa"
}
```

Response includes canonical article metadata and the route to open:

```json
{
  "targetId": "w_en_4091d476f3c2886a",
  "route": "/static?target=w_en_4091d476f3c2886a&view=stats"
}
```
