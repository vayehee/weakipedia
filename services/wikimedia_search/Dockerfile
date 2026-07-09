FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .
RUN playwright install --with-deps chromium

CMD exec uvicorn wikimedia_search.api:app --host 0.0.0.0 --port ${PORT:-8080}
