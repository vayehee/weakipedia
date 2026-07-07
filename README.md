# Weakipedia

Weakipedia front-end project environment.

## Local Development

```bash
npm install
npm run dev
```

## Build

```bash
npm run build
```

## Google Cloud

The intended Google Cloud project name is `Weakipedia`. The project ID is tracked separately because Google Cloud project IDs must be globally unique.

Useful commands:

```bash
gcloud config set project PROJECT_ID
gcloud projects describe PROJECT_ID
```

## GitHub Pages

This repo is configured to deploy from GitHub Actions on pushes to `main`.

After the GitHub repository exists, enable Pages:

1. Open the repository settings on GitHub.
2. Go to Pages.
3. Set Source to `GitHub Actions`.
4. Push to `main`.

The site path is configured for:

```text
https://USERNAME.github.io/weakipedia/
```
