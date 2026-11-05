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
