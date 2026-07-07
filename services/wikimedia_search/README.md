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
```
