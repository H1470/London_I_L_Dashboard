# London I&L Dashboard — project contents

This document is a **table of contents** for the repository: where files live and what they are for.  
Run the app from **`backend/`** (see `requirements.txt`); the FastAPI app can mount the **`frontend/`** static site in development.

---

## Top-level layout

| Path | Purpose |
|------|---------|
| `backend/` | Python **FastAPI** API, jobs, and SQLite-backed services. |
| `frontend/` | Static **HTML / CSS / JS** shell (served by FastAPI or any static host). |
| `docs/` | Project documentation (this file). |

Runtime data (often **gitignored**): SQLite files under `backend/data/` (e.g. `newmark_combined.db`, `news.db`).

---

## Backend (`backend/`)

### Config & dependencies

| File | Purpose |
|------|---------|
| `requirements.txt` | Python package pins for the API and jobs. |
| `.env` / `.env.example` | Local secrets and toggles (not committed vs template). **Never commit real secrets.** |

### Application package (`backend/app/`)

#### Entry

| File | Purpose |
|------|---------|
| `main.py` | **FastAPI app**: CORS, mounts `/api/*` routers, mounts **`frontend/`** at `/` when present so one process serves UI + API. |

#### HTTP routes (`backend/app/api/routes/`)

| File | Purpose |
|------|---------|
| `health.py` | **`GET /api/health`** — liveness for monitors. |
| `summary.py` | **`GET /api/summary`** — dashboard summary JSON (currently backed by fake data + optional `q` filter). |
| `indices.py` | **`GET /api/indices`** — FTSE placeholders + **Chatham** SONIA/gilts rows + **yfinance** ticker rows; no-store headers. |
| `news_feed.py` | **`GET /api/news`** list; **`POST /api/news/sync`** IMAP pull with optional `X-News-Sync-Secret`. |
| `newmark.py` | **`GET /api/newmark/geojson`**, **`/schema`**, **`/preview`** — merged Newmark map + table preview. |

#### Data access (`backend/app/data/`)

| File | Purpose |
|------|---------|
| `newmark_store.py` | Reads **`newmark_combined.db`** (`master_all`): GeoJSON points, **region + GE** filters, preview rows, schema. Env vars for DB path, table, column indices, column names. |
| `news_store.py` | **`news.db`**: rolling news stories (max 10), keyed by `message_id`. |
| `fake_data.py` | Placeholder payload for **`/api/summary`** until real pipelines exist. |
| `fake_indices.py` | Placeholder FTSE numbers for **`/api/indices`** until wired to a live feed. |

#### Services (`backend/app/services/`)

| File | Purpose |
|------|---------|
| `excel_to_sqlite.py` | **Excel → SQLite**: read `.xlsm`/`.xlsx` sheets, skip rows, select columns by 1-based indices, dedupe column names, `to_sql`. Used by Newmark sync and any other ingest. |
| `chatham_rates.py` | **Chatham Direct** session login + SONIA / swaps / gilt historical JSON for the dashboard table. |
| `yfinance_market.py` | **yfinance** rows for configured tickers (FX, commodities, BTC) for `/api/indices`. |
| `email_inbound_news.py` | **IMAP** fetch, parse subject + first URL, upsert into `news_store`. |
| `data_sources.py` | Stub / design notes for future batch ingestion (not used by routes yet). |

#### Jobs (`backend/app/jobs/`)

| File | Purpose |
|------|---------|
| `newmark_excel_sync.py` | **CLI**: read configured Newmark workbooks → per-file SQLite + **`newmark_combined.db`** `master_all` (+ copies). Edit `NEWMARK_SOURCES` at top. Run: `python -m app.jobs.newmark_excel_sync` from `backend/`. |
| `news_sync.py` | **CLI**: one-shot IMAP → news DB. Run: `python -m app.jobs.news_sync`. |
| `daily_refresh.py` | **Stub** for future scheduled refresh (cron / Task Scheduler). |

---

## Frontend (`frontend/`)

### Pages & shell

| File | Purpose |
|------|---------|
| `index.html` | **SPA-style shell**: sidebar nav, sections per “page” (dashboard default, bought-sold, deals-tracker, …), EY Calculator iframe, script tags for ES modules. |
| `css/app.css` | Global layout (sidebar + main), cards, tables, **Deals Power BI** stack, **Newmark** / EY embed tweaks, news list, responsive rules. |
| `css/embed.css` | Styles for **standalone** map HTML pages (minimal). |

### Newmark map (embeddable)

| File | Purpose |
|------|---------|
| `map.html` | Full-page Leaflet map host (dev). |
| `map-embed.html` | **Thin wrapper** iframe target: loads `map.js` + OSM for **Bought & Sold** embed in `index.html`. |
| `map-dev-embed.html` | Same for **Development** page — uses `map-dev.js` (no Newmark layer). |
| `js/map.js` | Fetches **`/api/newmark/geojson`**, draws circle markers, UK default view, tooltips/popups. |
| `js/map-dev.js` | Base map only for development embed. |

### Dashboard & platform JS

| File | Purpose |
|------|---------|
| `js/app.js` | **Nav**: `showPage`, `pageMeta`, wires dashboard/news loads, exposes `refreshNewmarkPreview` on `window`, initial `showPage` for active section. |
| `js/api.js` | Thin **`fetch`** helpers: `/api/summary`, `/api/indices`, `/api/news` (same-origin). |
| `js/dashboard.js` | Renders KPIs + **Chatham** / **yfinance** tables on the dashboard from `/api/indices` + summary. |
| `js/deals-tabs.js` | **Genesis / Map** tab switcher for Power BI iframes on Deals tracker. |
| `js/news-page.js` | Loads **`/api/news`** into the News section list + status line. |
| `js/newmark-preview.js` | **Newmark table preview** on Bought & Sold: `/api/newmark/preview` (map filters vs raw). |
| `js/newmark-preview-bootstrap.js` | Exposes preview functions on **`window`** before `app.js` so buttons work if a later import fails. |

### Other front artefacts

| File | Purpose |
|------|---------|
| `report.html` / `report-embed.html` | Separate report / embed pages (if used outside main shell). |

---

## How pieces connect (quick reference)

1. **Newmark pipeline**: Edit `jobs/newmark_excel_sync.py` → run job → **`backend/data/newmark_combined.db`**. Map + preview read via **`newmark_store.py`** and **`/api/newmark/*`**.  
2. **Dashboard market table**: **`/api/indices`** aggregates **`fake_indices`**, **`chatham_rates`**, **`yfinance_market`**.  
3. **News**: Configure IMAP in `.env` → **`POST /api/news/sync`** or **`news_sync`** job → **`news_store`** → **`GET /api/news`**.  
4. **Serving UI**: `uvicorn app.main:app` from **`backend/`** loads static **`frontend/`** at `/` when the folder exists.

---

## For new developers

- Start with **`backend/app/main.py`** and **`docs/CONTENTS.md`** (this file).  
- Follow **`frontend/js/app.js`** for how HTML sections map to behaviour.  
- Newmark behaviour is concentrated in **`backend/app/data/newmark_store.py`** and **`backend/app/jobs/newmark_excel_sync.py`**.  
- Module docstrings and short comments in code mark non-obvious behaviour (filters, env vars, iframe quirks).

If you add a new route, register it in **`main.py`** and document it here in the routes table.
