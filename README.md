# BirdNET-Online

A full-stack dashboard for live bird detections from a [BirdNET-Pi](https://github.com/mcguirepr89/BirdNET-Pi) installation in Edinburgh (55.93°N, 3.25°W).

```
/api   — FastAPI backend (deployed on Render)
/web   — Static frontend (deployed on GitHub Pages)
```

---

## Dashboard Features

### Global Filter Bar
A sticky filter bar at the top of the page affects every chart and stat on the dashboard:
- **Date range** with presets: Today, Last 7 days, Last 30 days, Last 90 days, All time
- **Species multi-select** — searchable dropdown showing all detected species
- **Hour range slider** — filter to a specific window of the day (e.g. 04:00–20:00)
- **Confidence threshold** — minimum detection confidence (default 70%)
- **Month checkboxes** — include/exclude specific calendar months
- **Reset** button to restore all defaults
- Active filter badges so you always know what's applied

### Summary Stat Cards
Six cards updated in real time with the filtered dataset:
- Total detections · Unique species · Top species today
- Best confidence detection ever · Earliest detection today vs sunrise
- Total recording days

### Live Feed
- Last 20 detections, auto-refreshed every 60 seconds
- Confidence badge colour-coded: green ≥85%, amber 70–85%, red <70%
- Migration status badge per detection
- ✨ icon on species not seen in 30+ days
- Smooth fade-in animation on new rows

### Charts

| Chart | Description |
|---|---|
| Detections over time | Daily bar chart, bars coloured by month, 7-day rolling average overlaid |
| Activity heatmap | Grid: rows = day of week, columns = hour 00–23, cell intensity = count |
| Hourly activity | Bar chart with sunrise/sunset vertical lines from SunCalc |
| Top 20 species | Horizontal bar, colour-coded by migration status, clickable → species sidebar |
| Species by hour | Doughnut chart with a 0–23 slider updating in real time |
| Species diversity | Unique species/week line chart with spring equinox annotation |
| Day of week | Bar chart showing which days have most activity |
| Confidence distribution | Histogram of scores in 5% buckets (50–100%) |
| Monthly comparison | Grouped bars for top 6 species across all months |
| Sunrise vs detections | Scatter plot: sunrise line, sunset line, first/last detection dots per day |
| Dawn chorus timing | Minutes between first detection and sunrise, plotted over time |
| Species accumulation | Running total of unique species ever detected, all-time |

### Species Sidebar
Click any species name (feed, chart, migration panel) to open a detail panel:
- Common name + scientific name + migration badge
- Total, best confidence, average confidence, first seen, last seen
- "Not seen for X days" warning if absent ≥7 days
- Monthly detections bar chart
- Wikipedia summary (fetched live from Wikipedia REST API)

### Weather Panel
- Current temperature, wind, rainfall, humidity from [Open-Meteo](https://open-meteo.com/) (no API key)
- WMO weather code mapped to emoji + description
- Today's sunrise and sunset times from SunCalc
- Moon phase emoji, name, and % illuminated
- 24-hour forecast chart (temperature line + precipitation probability bars)

### New Species Banner
If any species detected today has not been seen in the last 30 days, a banner appears at the top of the page listing those species as clickable links.

### Migration Highlights Panel
All detected species grouped into three columns:
- **Summer Migrants** — with first detection date this year
- **Winter Visitors** — with last detection date
- **Residents** — with consecutive-day detection streak

---

## Screenshots

<!-- Add screenshots here after deployment -->

---

## Architecture

```
BirdNET-Pi ──POST──► Render (FastAPI) ──insert──► Supabase (Postgres)
                                                         │
GitHub Pages (index.html) ◄──── Supabase JS client ─────┘
```

---

## Setup Instructions

### 1. Supabase

Run this in the **Supabase SQL editor**:

```sql
create table if not exists detections (
  id              bigint generated always as identity primary key,
  detected_at     timestamptz not null,
  common_name     text        not null,
  scientific_name text        not null,
  confidence      numeric(5,4) not null,
  lat             numeric(9,6),
  lon             numeric(9,6)
);

alter table detections enable row level security;

create policy "Public read"
  on detections for select using (true);
```

The anon key in `web/index.html` is safe to commit — RLS prevents any writes from the frontend.

### 2. Backend (API on Render)

```bash
cd api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env
# Set SUPABASE_KEY to your Supabase service role key
uvicorn main:app --reload
```

**Deploy to Render:**
1. Push this repo to GitHub
2. Go to [render.com](https://render.com) → New → Blueprint → connect repo
3. Add environment variable `SUPABASE_KEY` = your Supabase service role key
4. Copy the Deploy Hook URL and add it as GitHub Actions secret `RENDER_DEPLOY_HOOK`

### 3. Configure BirdNET-Pi

SSH into your Pi and edit the notification script at `~/BirdNET-Pi/scripts/custom_notification.sh`:

```bash
#!/bin/bash
COMNAME="$1"
SCINAME="$2"
CONFIDENCE="$3"
REASON="$4"

curl -s -X POST "https://your-service.onrender.com/detection" \
  -H "Content-Type: text/plain" \
  --data "A ${COMNAME} (${SCINAME}) was just detected with a confidence of ${CONFIDENCE} (${REASON})"
```

```bash
chmod +x ~/BirdNET-Pi/scripts/custom_notification.sh
```

### 4. Frontend

The Supabase anon key is already embedded in `web/index.html`. To change it:

```js
const SUPABASE_ANON_KEY = window.SUPABASE_ANON_KEY || "YOUR_ANON_KEY_HERE";
```

**Deploy to GitHub Pages:**
1. Go to repo Settings → Pages → Source: GitHub Actions
2. Push to `main` — the `deploy-web.yml` workflow publishes `web/` automatically

**Local preview:**
```bash
cd web && python -m http.server 8080
# open http://localhost:8080
```

---

## Adding Species Badges Manually

Migration status is inferred automatically from which calendar months a species appears in the dataset:
- Detected **only** in Apr–Sep → Summer Migrant ☀️
- Detected **only** in Oct–Mar → Winter Visitor ❄️
- Detected in **both** summer and winter months → Resident 🌿

This updates automatically as more data accumulates. If a species is mis-classified (e.g. because it was first detected mid-season), it will correct itself over time. No manual intervention is needed.

---

## Environment Variables

| Variable | Where used | Description |
|---|---|---|
| `SUPABASE_KEY` | Render (API) | Supabase **service role** key — write access |
| `RENDER_DEPLOY_HOOK` | GitHub Actions secret | Render deploy hook URL |
| `SUPABASE_ANON_KEY` | `web/index.html` (hardcoded) | Supabase **anon** key — read-only |

---

## Troubleshooting

### Render cold starts (free tier)
Render's free tier spins down services after 15 minutes of inactivity. The first detection after a period of quiet may fail with a timeout while the service wakes up. BirdNET-Pi will usually retry. You can avoid this by upgrading to a paid Render tier or by setting up an uptime monitor (e.g. UptimeRobot) to ping your API every 10 minutes.

### CORS errors
If the browser console shows CORS errors when calling your Render API, ensure your FastAPI app includes the `CORSMiddleware` allowing the GitHub Pages origin. Check `api/main.py` for the `origins` list.

### Supabase RLS issues
If the dashboard shows no data but the API is inserting successfully:
1. Check that the `Public read` policy exists in Supabase → Authentication → Policies
2. Verify the anon key in `web/index.html` matches **Settings → API → anon public** in your Supabase project
3. Open the browser console and look for PostgREST error messages

### BirdNET-Pi not sending detections
1. SSH into the Pi: `tail -f ~/BirdNET-Pi/scripts/custom_notification.sh` to check it's being called
2. Test manually: `curl -X POST https://your-service.onrender.com/detection -H "Content-Type: text/plain" -d "A Robin (Erithacus rubecula) was just detected with a confidence of 0.85 (birdnet)"`
3. Check Render logs for any 422/500 errors — the POST body format must match exactly what the FastAPI parser expects

---

## Roadmap

Ideas for future development:

- **Mobile app** — React Native or PWA wrapper with push notifications for rare species
- **Email / SMS alerts** — notify when a flagged species is detected (e.g. first swallow of spring)
- **Year-on-year comparison** — overlay current year vs previous year on the detections-over-time chart
- **Weather correlation analysis** — scatter plot of detection count vs temperature, wind, and barometric pressure
- **Audio playback** — store and serve the `.wav` clip from each detection; play in the species sidebar
- **Species richness map** — if multiple sensors are deployed, show a leaflet map with per-sensor counts
- **eBird / BTO integration** — cross-reference detections against local species lists and rarity alerts
- **Confidence calibration** — per-species confidence thresholds based on historical false-positive rates
- **Automated weekly digest** — emailed summary of species count, new arrivals, and notable detections
