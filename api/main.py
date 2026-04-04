# VAPID key generation: npx web-push generate-vapid-keys
# Set VAPID_PRIVATE_KEY and VAPID_PUBLIC_KEY as environment variables.

import asyncio
import json
import os
import re
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import Client, create_client

try:
    from pywebpush import WebPushException, webpush
except ImportError:
    webpush = None
    WebPushException = Exception

app = FastAPI(title="BirdNET-Online API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

SUPABASE_URL = "https://werxbsrtvkjmumxuxsrd.supabase.co"
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY  = os.environ.get("VAPID_PUBLIC_KEY", "")
LAT = 55.7983
LON = -2.2041

# Optional bearer token — if set, /detection requires Authorization: Bearer <token>
DETECTION_TOKEN = os.environ.get("DETECTION_TOKEN")

# Optional email config for weekly digest
SMTP_HOST    = os.environ.get("SMTP_HOST")
SMTP_PORT    = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER    = os.environ.get("SMTP_USER")
SMTP_PASS    = os.environ.get("SMTP_PASS")
DIGEST_EMAIL = os.environ.get("DIGEST_EMAIL")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# BirdNET-Pi body: "A $comname ($sciname) was just detected with a confidence of $confidence ($reason)"
DETECTION_RE = re.compile(
    r"A (.+?) \((.+?)\) was just detected with a confidence of ([0-9.]+)",
    re.IGNORECASE,
)

BURST_WINDOW_SECONDS = 30

# Regionally scarce / notable Scottish species
SCOTTISH_RARITIES: set[str] = {
    "Osprey", "White-tailed Eagle", "Red Kite", "Hen Harrier", "Peregrine Falcon",
    "Merlin", "Corncrake", "Red-necked Phalarope", "Black-throated Diver",
    "Red-throated Diver", "Slavonian Grebe", "Black Grouse", "Capercaillie",
    "Scottish Crossbill", "Crested Tit", "Snow Bunting", "Dotterel",
    "Purple Sandpiper", "Whimbrel", "Greenshank", "Twite", "Yellowhammer",
    "Corn Bunting", "Tree Sparrow", "Turtle Dove", "Nightjar", "Swift",
    "Cuckoo", "Yellow Wagtail", "Grasshopper Warbler", "Sedge Warbler",
    "Lesser Whitethroat", "Wood Warbler", "Pied Flycatcher", "Ring Ouzel",
    "Redstart", "Wheatear", "Wryneck", "Hoopoe", "Bee-eater", "Golden Oriole",
    "Short-eared Owl", "Barn Owl", "Little Egret", "Great Egret", "Spoonbill",
    "Avocet", "Stone-curlew",
}


# ─── Auth ─────────────────────────────────────────────────────────────────────

def _check_token(request: Request) -> None:
    if not DETECTION_TOKEN:
        return
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[7:] != DETECTION_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")


# ─── Confidence calibration ───────────────────────────────────────────────────

async def _get_species_threshold(common_name: str) -> float:
    """Return per-species minimum confidence threshold from species_thresholds table."""
    try:
        result = (
            supabase.table("species_thresholds")
            .select("min_confidence")
            .eq("common_name", common_name)
            .maybe_single()
            .execute()
        )
        if result.data:
            return float(result.data["min_confidence"])
    except Exception:
        pass
    return 0.0


# ─── Burst / duplicate detection ──────────────────────────────────────────────

async def _is_duplicate(common_name: str) -> bool:
    """Return True if same species was detected within the burst window."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(seconds=BURST_WINDOW_SECONDS)
    ).isoformat()
    try:
        result = (
            supabase.table("detections")
            .select("id")
            .eq("common_name", common_name)
            .gte("detected_at", cutoff)
            .limit(1)
            .execute()
        )
        return bool(result.data)
    except Exception:
        return False


# ─── Push notifications ───────────────────────────────────────────────────────

def _send_push_sync(title: str, body: str, common_name: str, confidence: float) -> None:
    """Send push notification to all subscribers (synchronous, run in thread)."""
    if not webpush or not VAPID_PRIVATE_KEY:
        return
    try:
        subs = supabase.table("push_subscriptions").select("*").execute()
        payload = json.dumps({
            "title": title,
            "body": body,
            "common_name": common_name,
            "confidence": confidence,
        })
        for sub in subs.data or []:
            try:
                webpush(
                    subscription_info={
                        "endpoint": sub["endpoint"],
                        "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
                    },
                    data=payload,
                    vapid_private_key=VAPID_PRIVATE_KEY,
                    vapid_claims={"sub": "mailto:birdnet@example.com"},
                )
            except WebPushException:
                pass
    except Exception:
        pass


async def _send_push_to_all(title: str, body: str, common_name: str = "", confidence: float = 0) -> None:
    """Async wrapper — runs sync webpush in a thread pool."""
    await asyncio.to_thread(_send_push_sync, title, body, common_name, confidence)


# ─── Thumbnail caching ────────────────────────────────────────────────────────

async def _cache_thumbnail(common_name: str, scientific_name: str) -> None:
    """Fetch and cache Wikipedia thumbnail for a species on first detection."""
    try:
        existing = (
            supabase.table("species_cache")
            .select("common_name")
            .eq("common_name", common_name)
            .maybe_single()
            .execute()
        )
        if existing.data:
            return
        async with httpx.AsyncClient(timeout=10) as client:
            for query in [scientific_name, common_name]:
                q = query.replace(" ", "_")
                resp = await client.get(
                    f"https://en.wikipedia.org/api/rest_v1/page/summary/{q}"
                )
                if resp.status_code == 200:
                    thumb = resp.json().get("thumbnail", {}).get("source")
                    if thumb:
                        supabase.table("species_cache").upsert({
                            "common_name": common_name,
                            "scientific_name": scientific_name,
                            "thumbnail_url": thumb,
                        }).execute()
                        return
    except Exception:
        pass


# ─── Absence alerts (daily cron) ──────────────────────────────────────────────

async def check_absence_alerts() -> None:
    """Notify if a species seen every day for 7+ days went absent yesterday."""
    try:
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        result = (
            supabase.table("detections")
            .select("common_name,detected_at")
            .gte("detected_at", (today - timedelta(days=8)).isoformat())
            .lt("detected_at", today.isoformat())
            .execute()
        )
        species_days: dict[str, set[str]] = {}
        for r in result.data or []:
            species_days.setdefault(r["common_name"], set()).add(r["detected_at"][:10])

        required = {(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, 8)}
        yest = (today - timedelta(days=1)).strftime("%Y-%m-%d")
        for sp, days in species_days.items():
            if required.issubset(days) and yest not in days:
                asyncio.create_task(
                    _send_push_to_all(
                        title=f"🔕 {sp} absent",
                        body=f"{sp} was seen every day for 7+ days but missed yesterday.",
                    )
                )
    except Exception as e:
        print(f"[absence-check] {e}")


# ─── Weekly digest ────────────────────────────────────────────────────────────

async def send_weekly_digest() -> None:
    """Email a weekly summary of detections (requires SMTP env vars)."""
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASS, DIGEST_EMAIL]):
        return
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        week = (
            supabase.table("detections")
            .select("common_name")
            .gte("detected_at", cutoff)
            .execute()
        ).data or []
        historic = (
            supabase.table("detections")
            .select("common_name")
            .lt("detected_at", cutoff)
            .execute()
        ).data or []

        counts: dict[str, int] = {}
        for r in week:
            counts[r["common_name"]] = counts.get(r["common_name"], 0) + 1
        top = sorted(counts.items(), key=lambda x: -x[1])[:10]
        seen_before = {r["common_name"] for r in historic}
        new_arrivals = [sp for sp in counts if sp not in seen_before]

        lines = [
            "BirdNET-Online Weekly Digest",
            "=" * 40,
            f"Week total: {len(week)} detections",
            f"Unique species: {len(counts)}",
            f"New arrivals: {', '.join(new_arrivals) or 'none'}",
            "",
            "Top 10 species:",
            *[f"  {i}. {sp} — {n}" for i, (sp, n) in enumerate(top, 1)],
        ]
        msg = MIMEText("\n".join(lines))
        msg["Subject"] = "BirdNET-Online Weekly Digest"
        msg["From"] = SMTP_USER
        msg["To"] = DIGEST_EMAIL
        await asyncio.to_thread(_smtp_send, msg)
    except Exception as e:
        print(f"[digest] {e}")


def _smtp_send(msg: MIMEText) -> None:
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as srv:
        srv.starttls()
        srv.login(SMTP_USER, SMTP_PASS)
        srv.send_message(msg)


# ─── Scheduler ────────────────────────────────────────────────────────────────

scheduler = AsyncIOScheduler()


@app.on_event("startup")
async def start_scheduler() -> None:
    scheduler.add_job(send_weekly_digest, "cron", day_of_week="mon", hour=8)
    scheduler.add_job(check_absence_alerts, "cron", hour=9, minute=0)
    scheduler.start()


@app.on_event("shutdown")
async def stop_scheduler() -> None:
    scheduler.shutdown()


# ─── Models ───────────────────────────────────────────────────────────────────

class PushSubscription(BaseModel):
    endpoint: str
    p256dh: str
    auth: str


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/subscribe")
async def subscribe(sub: PushSubscription):
    """Register or update a push subscription."""
    supabase.table("push_subscriptions").upsert(
        {"endpoint": sub.endpoint, "p256dh": sub.p256dh, "auth": sub.auth},
        on_conflict="endpoint",
    ).execute()
    return {"subscribed": True}


@app.delete("/subscribe")
async def unsubscribe(request: Request):
    """Remove a push subscription."""
    data = await request.json()
    try:
        supabase.table("push_subscriptions").delete().eq("endpoint", data["endpoint"]).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "unsubscribed"}


@app.post("/detection")
async def receive_detection(request: Request, background_tasks: BackgroundTasks):
    _check_token(request)

    body = await request.body()
    text = body.decode("utf-8").strip()

    match = DETECTION_RE.search(text)
    if not match:
        raise HTTPException(status_code=422, detail=f"Could not parse body: {text!r}")

    common_name = match.group(1).strip()
    scientific_name = match.group(2).strip()
    try:
        confidence = float(match.group(3))
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid confidence value")

    # Per-species confidence threshold
    min_conf = await _get_species_threshold(common_name)
    if confidence < min_conf:
        return {"skipped": True, "reason": "below_threshold", "threshold": min_conf}

    # Burst / duplicate suppression
    if await _is_duplicate(common_name):
        return {"skipped": True, "reason": "duplicate", "window_seconds": BURST_WINDOW_SECONDS}

    # Rarity: named rarity list takes priority; also compute fraction-based rarity
    is_rare_named = common_name in SCOTTISH_RARITIES
    is_rare = is_rare_named
    detected_at = datetime.now(timezone.utc).isoformat()

    result = supabase.table("detections").insert({
        "detected_at": detected_at,
        "common_name": common_name,
        "scientific_name": scientific_name,
        "confidence": confidence,
        "lat": LAT,
        "lon": LON,
        "is_rare": is_rare,
    }).execute()

    # Background: cache thumbnail
    background_tasks.add_task(_cache_thumbnail, common_name, scientific_name)

    # Background: push notification for rare species OR high confidence
    if is_rare:
        background_tasks.add_task(
            _send_push_to_all,
            f"🦅 Rare: {common_name}",
            f"{common_name} detected at {confidence*100:.0f}% confidence.",
            common_name,
            confidence,
        )
    elif confidence >= 0.85:
        background_tasks.add_task(
            _send_push_to_all,
            f"🐦 {common_name}",
            f"Detected at {confidence*100:.0f}% confidence.",
            common_name,
            confidence,
        )

    return {
        "inserted": len(result.data),
        "detection": result.data[0] if result.data else None,
        "is_rare": is_rare,
    }


@app.get("/digest")
async def trigger_digest():
    """Manually trigger the weekly digest email."""
    await send_weekly_digest()
    return {"status": "digest triggered"}
