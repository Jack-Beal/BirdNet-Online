# VAPID key generation: npx web-push generate-vapid-keys
# Set VAPID_PRIVATE_KEY and VAPID_PUBLIC_KEY as environment variables.

import os
import re
import json
from datetime import datetime, timezone

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
try:
    from pywebpush import webpush, WebPushException
except ImportError:
    webpush = None
    WebPushException = Exception

app = FastAPI(title="BirdNET-Online API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

SUPABASE_URL = "https://werxbsrtvkjmumxuxsrd.supabase.co"
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY  = os.environ.get("VAPID_PUBLIC_KEY", "")
LAT = 55.9335
LON = -3.254

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# BirdNET-Pi body: "A $comname ($sciname) was just detected with a confidence of $confidence ($reason)"
DETECTION_RE = re.compile(
    r"A (.+?) \((.+?)\) was just detected with a confidence of ([0-9.]+)",
    re.IGNORECASE,
)


class PushSubscription(BaseModel):
    endpoint: str
    p256dh: str
    auth: str


def send_push_notification(common_name: str, confidence: float) -> None:
    """Send push notification for high-confidence or rare species detections."""
    if not webpush or not VAPID_PRIVATE_KEY or not VAPID_PUBLIC_KEY:
        return

    try:
        # Get total detections count and species count for rarity check
        total_result = supabase.table("detections").select("id", count="exact").execute()
        total = total_result.count or 0

        species_result = (
            supabase.table("detections")
            .select("id", count="exact")
            .eq("common_name", common_name)
            .execute()
        )
        species_count = species_result.count or 0

        species_fraction = species_count / total if total > 0 else 1.0
        is_rare = species_fraction < 0.01

        if confidence < 0.85 and not is_rare:
            return

        # Fetch all subscriptions
        subs_result = supabase.table("push_subscriptions").select("*").execute()
        subscriptions = subs_result.data or []

        payload = json.dumps({
            "common_name": common_name,
            "species": common_name,
            "confidence": confidence,
        })

        for sub in subscriptions:
            try:
                webpush(
                    subscription_info={
                        "endpoint": sub["endpoint"],
                        "keys": {
                            "p256dh": sub["p256dh"],
                            "auth":   sub["auth"],
                        },
                    },
                    data=payload,
                    vapid_private_key=VAPID_PRIVATE_KEY,
                    vapid_claims={"sub": "mailto:admin@birdnet.local"},
                )
            except WebPushException:
                pass
    except Exception:
        pass


@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/subscribe")
async def subscribe(sub: PushSubscription):
    """Register or update a push subscription."""
    result = (
        supabase.table("push_subscriptions")
        .upsert(
            {
                "endpoint": sub.endpoint,
                "p256dh":   sub.p256dh,
                "auth":     sub.auth,
            },
            on_conflict="endpoint",
        )
        .execute()
    )
    return {"subscribed": True}


@app.post("/detection")
async def receive_detection(request: Request):
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

    detected_at = datetime.now(timezone.utc).isoformat()

    result = supabase.table("detections").insert(
        {
            "detected_at": detected_at,
            "common_name": common_name,
            "scientific_name": scientific_name,
            "confidence": confidence,
            "lat": LAT,
            "lon": LON,
        }
    ).execute()

    # Send push notification asynchronously (best-effort)
    try:
        send_push_notification(common_name, confidence)
    except Exception:
        pass

    return {"inserted": len(result.data), "detection": result.data[0] if result.data else None}
