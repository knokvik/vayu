# Tree Loss Receipt

A local-first web app. Tell it how many trees are being cut and roughly how big
they are. In under a minute it produces a transparent **Tree Loss Receipt**: what
the neighbourhood loses every year (cooling, rainwater, air cleaning, carbon) and
how many years the promised replacement trees will really take to recover under
realistic survival rates.

Pure local development. No cloud services, no AWS.

## Design principles

- Always return **ranges** `(low, high)`, never a single precise number.
- Always show **"As promised"** and **"Realistic"** scenarios side by side.
- Every number on the receipt lists its **source** and a verification status.
- Anything not verified against a primary source is labelled
  *"indicative, to be verified"*.
- Any generated objection letter (later step) is a draft, not legal advice.

## Repository layout

```
backend/    FastAPI service (Python 3.13)
frontend/   React + Vite + Tailwind CSS
data/       Local JSON data (city profiles, per-tree service ranges)
```

## Tech stack

| Layer    | Choice                                   |
|----------|------------------------------------------|
| Frontend | React 18, Vite, Tailwind CSS 4           |
| Backend  | Python FastAPI, pydantic                 |
| Data     | Local JSON files (SQLite optional later) |
| Tests    | pytest (backend)                         |

## Running locally

Backend:

```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# health check: http://127.0.0.1:8000/health
```

Run the backend tests:

```bash
cd backend && . .venv/bin/activate
python -m pytest -q
```

API (interactive docs at http://127.0.0.1:8000/docs):

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Liveness check |
| `GET /city-profiles` | Pune and Mumbai profiles, survival presets (`mumbai_like` 0.37, `chennai_like` 0.63), growth classes, size classes |
| `POST /calculate` | Annual loss ranges plus the 40-year replacement-gap simulation |

Example:

```bash
curl -s -X POST http://127.0.0.1:8000/calculate \
  -H 'content-type: application/json' \
  -d '{"city":"pune","tree_counts":{"small":100,"medium":250,"large":179},"promised_ratio":4}'
```

Request fields: `city`; either `tree_counts` or `total_trees` + `size_mix`;
optional `promised_ratio`, `promised_survival`, `realistic_survival` (number or
`{low, high}`), `survival_preset`, `growth_class` (`fast|moderate|slow`),
`horizon_years`. Every result group carries its `sources` and
`verification_status`.

Frontend:

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173 (proxies /api/* to the backend on :8000)
npm run build    # production build into frontend/dist
```

## Data sources

These are the sources the project draws on. Each one is used as *context or as a
range anchor*, never as a source of false precision. Where a specific figure has
not been checked against the primary document, the data files say so in a
`verification_status` field.

| Data | Source | Use in the project |
|------|--------|--------------------|
| High-resolution canopy height | Meta + World Resources Institute (WRI) Canopy Height Maps (1 m) | Estimate existing canopy and tree-size mix from a map (planned, optional) |
| Urban tree species | Urban Trees of India (UTI) database | Species groups and growth curves |
| Forest and tree cover | Forest Survey of India, India State of Forest Report (ISFR) 2023 | City-level tree-cover context |
| Per-tree ecosystem services | i-Tree Eco studies for Delhi, Bhubaneswar and Thiruvananthapuram (published papers) | Cooling, runoff, air-cleaning and carbon ranges |
| Rainfall and temperature | India Meteorological Department (IMD) climatological normals; India WRIS | Rainwater and heat context |
| Air quality | CPCB / data.gov.in | Nearby pollution context |
| Legal and survival context | Maharashtra (Urban Areas) Protection and Preservation of Trees Act, 1975, plus NGT / Supreme Court reports | Realistic survival presets and compensatory planting rules |

Other literature used as range anchors is cited per entry in
`data/services_ranges.json`. Figures that could not be verified against a primary
source are labelled `indicative_to_be_verified` there.

## Status

Work is delivered in small commits, one per step. See `git log`.
