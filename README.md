# Hofftown Ballers — Weekly Kid-Friendly Report

Automated weekly fantasy football report for the Sleeper league **Hofftown Ballers**
(12 teams, 2026 season). Every Tuesday the pipeline scrapes the league from the
Sleeper API, writes a playful report with the DeepSeek LLM, runs it through a
safety gate (blocklist + LLM review), renders a kid-friendly HTML site, and
deploys it to GitHub Pages.

**Live site:** https://dustinfelderhoff.github.io/hofftown-ballers/

## Pipeline

```
scrape.py  →  writer.py  →  reviewer.py  →  build_site.py  →  GitHub Pages deploy
(Sleeper)     (DeepSeek)     (safety gate)     (HTML render)
```

| Step | Script | What it does |
|---|---|---|
| 1 | `scrape.py` | Pulls league / users / rosters / drafts / picks / matchups from the Sleeper API into `data/` |
| 2 | `writer.py` | Asks DeepSeek to write the report into `report.json` |
| 3 | `reviewer.py` | Blocklist + LLM safety review → `report.reviewed.json` |
| 4 | `build_site.py` | Renders `site/` (index.html + archive) |
| 5 | GitHub Actions | Deploys `site/` to GitHub Pages |

## Run locally

Everything is Python 3 stdlib — no dependencies to install.

```bash
python scrape.py
python writer.py      # needs DEEPSEEK_API_KEY in the environment
python reviewer.py
python build_site.py
```

Or all in one shot:

```bash
python scrape.py && python writer.py && python reviewer.py && python build_site.py
```

The writer and reviewer steps require `DEEPSEEK_API_KEY` to be set in the
environment (it lives in `C:/Users/dusti/AppData/Local/hermes/.env` locally and
as a GitHub Actions secret in CI).

## Weekly automation

`.github/workflows/weekly-report.yml` runs the full pipeline every Tuesday at
14:00 UTC (8:00 AM MT) and deploys the result to GitHub Pages. If the LLM step
fails, the run fails and the last good site stays live.

## Manual trigger

1. Open the repo on GitHub → **Actions** tab.
2. Select the **Weekly Report** workflow.
3. Click **Run workflow** → **Run workflow**.
