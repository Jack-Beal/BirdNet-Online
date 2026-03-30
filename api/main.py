import os
import re
from datetime import datetime, timezone

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client

app = FastAPI(title="BirdNET-Online API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

SUPABASE_URL = "https://werxbsrtvkjmumxuxsrd.supabase.co"
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
LAT = 55.9335
LON = -3.254

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# BirdNET-Pi body: "A $comname ($sciname) was just detected with a confidence of $confidence ($reason)"
DETECTION_RE = re.compile(
    r"A (.+?) \((.+?)\) was just detected with a confidence of ([0-9.]+)",
    re.IGNORECASE,
)


@app.get("/")
def health():
    return {"status": "ok"}


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

    return {"inserted": len(result.data), "detection": result.data[0] if result.data else None}
