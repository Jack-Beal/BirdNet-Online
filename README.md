# BirdNET-Online

A full-stack dashboard for live bird detections from a [BirdNET-Pi](https://github.com/mcguirepr89/BirdNET-Pi) installation in Edinburgh (55.93°N, 3.25°W).

```
/api   — FastAPI backend (deployed on Render)
/web   — Static frontend (deployed on GitHub Pages)
```

---

## Architecture

```
BirdNET-Pi ──POST──► Render (FastAPI) ──insert──► Supabase (Postgres)
                                                         │
GitHub Pages (index.html) ◄──── Supabase JS client ─────┘
```

---

## 1. Supabase setup

### Create the table

Run this in the **Supabase SQL editor**:

```sql
create table if not exists detections (
  id           bigint generated always as identity primary key,
  detected_at  timestamptz not null,
  common_name  text        not null,
  scientific_name text     not null,
  confidence   numeric(5,4) not null,
  lat          numeric(9,6),
  lon          numeric(9,6)
);
```

### Enable Row Level Security

```sql
-- Enable RLS
alter table detections enable row level security;

-- Public read (anyone with the anon key can SELECT)
create policy "Public read"
  on detections
  for select
  using (true);

-- No public insert/update/delete — only the service role key can write
-- (The API backend uses the service role key via SUPABASE_KEY env var)
```

---

## 2. Backend (API)

### Local development

```bash
cd api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env
# Edit .env — set SUPABASE_KEY to your Supabase service role key
uvicorn main:app --reload
```

The endpoint is `POST /detection`.

### Deploy to Render

1. Push this repo to GitHub.
2. Go to [render.com](https://render.com) → **New → Blueprint** → connect your repo.
   Render will detect `render.yaml` automatically.
3. In the Render dashboard for the service, add the environment variable:
   - `SUPABASE_KEY` = your Supabase **service role** key (Settings → API in Supabase).
4. Copy the **Deploy Hook URL** from Render (Settings → Deploy Hook).
5. Add it as a GitHub Actions secret named `RENDER_DEPLOY_HOOK`.

---

## 3. Configure BirdNET-Pi to POST detections

SSH into your Pi and edit `/etc/birdnet/birdnet.conf` (or wherever BirdNET-Pi stores it — typically `~/BirdNET-Pi/scripts/birdnet.conf`):

Find or add these lines:

```ini
# Enable the custom notification script
CUSTOM_NOTIFICATION=true

# URL of your Render API endpoint
CUSTOM_NOTIFICATION_URL=https://your-service.onrender.com/detection

# Body template — must match exactly
CUSTOM_NOTIFICATION_BODY=A $comname ($sciname) was just detected with a confidence of $confidence ($reason)
```

If BirdNET-Pi uses a shell-script notification hook instead, add or edit `~/BirdNET-Pi/scripts/custom_notification.sh`:

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

Make it executable: `chmod +x ~/BirdNET-Pi/scripts/custom_notification.sh`

---

## 4. Frontend

### Set your Supabase anon key

Open `web/index.html` and replace the placeholder near the top of the `<script>` block:

```js
const SUPABASE_ANON_KEY = window.SUPABASE_ANON_KEY || "YOUR_ANON_KEY_HERE";
```

Replace `YOUR_ANON_KEY_HERE` with your Supabase **anon** (public) key
(Supabase dashboard → Settings → API → `anon public`).

The anon key is safe to commit — RLS ensures anonymous users can only read.

### Deploy to GitHub Pages

1. In your GitHub repo → **Settings → Pages** → Source: **GitHub Actions**.
2. Push to `main` — the `deploy-web.yml` workflow will publish `web/` automatically.

### Local preview

```bash
cd web
python -m http.server 8080
# open http://localhost:8080
```

---

## 5. Environment variables summary

| Variable | Where used | Description |
|---|---|---|
| `SUPABASE_KEY` | Render (API) | Supabase **service role** key — write access |
| `RENDER_DEPLOY_HOOK` | GitHub Actions secret | Render deploy hook URL |
| `SUPABASE_ANON_KEY` | `web/index.html` (hardcoded) | Supabase **anon** key — read-only |

See `.env.example` for the API server template.
