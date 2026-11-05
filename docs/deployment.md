# Deployment

## How it runs

`.github/workflows/build.yml` runs on every push to `main` and daily at 11:41 UTC (4:41 a.m. in Calgary):

1. **test**: `python -m pytest -q`. A failing test stops everything.
2. **build**: builds each city into `site/data`, compares row counts with the last build (from the `data` branch),
   pushes the output to the `data` branch (`latest/` and `snapshots/<city>/<date>/`), and uploads the site.
3. **deploy**: publishes to GitHub Pages.

If a data quality check fails, the build stops and the site keeps its last good version.

## One-time setup

1. Repository is public (free GitHub Pages).
2. Settings → Pages → Source: **GitHub Actions**.
3. Optional: a free Socrata app token as the secret `SOCRATA_APP_TOKEN` (fewer throttled requests).

## Custom domain

1. Buy the domain from any registrar.
2. Settings → Pages → Custom domain: enter it (for example `canadainsight.ca`) and save.
3. At the registrar, add DNS records:
   - apex domain: four `A` records to GitHub Pages' addresses listed in GitHub's documentation
     ("Managing a custom domain for your GitHub Pages site");
   - `www`: a `CNAME` to `hassanaliarshad110.github.io`.
4. When the check passes, tick **Enforce HTTPS**.

## Run locally

```
pip install -r requirements.txt pytest
python -m pytest -q
python -m insight build --city calgary --out site/data
python -m http.server -d site 8000
```

## Research assistant (Ask the data)

The assistant runs as a small Cloudflare Worker (`worker/genie.js`) that holds the Claude key; the website only
sends questions to it. It answers from the published files and the City's open data portal, cites every figure,
and has daily limits per visitor and overall.

One-time setup:
1. Create a free Cloudflare account. In **My Profile → API Tokens**, create a token from the **Edit Cloudflare
   Workers** template. Note your **Account ID** (Workers & Pages overview page).
2. In this repository: **Settings → Secrets and variables → Actions**, add `CLOUDFLARE_API_TOKEN`,
   `CLOUDFLARE_ACCOUNT_ID` and `ANTHROPIC_API_KEY` (give the key a monthly spend limit in the Claude Console).
   Optional: `GENIE_ACCESS_CODE` if only people with the code should use it.
3. **Actions → Research assistant → Run workflow.** It deploys the worker, puts the key in Cloudflare's secret
   store, and writes the assistant's address to `site/genie.json`, which rebuilds the site.

Limits: 30 questions per visitor per day, 600 in all (`worker/wrangler.toml`).
