import os, json, requests
from pydantic import BaseModel, Field
from typing import List, Optional, Dict

class NearbyPlaceRequest(BaseModel):
    image_label: str
    latitude: float
    longitude: float
    included_types: List[str]
    radius: Optional[float] = 500.0
    max_result_count: Optional[int] = 10


def find_nearby_places(req: NearbyPlaceRequest) -> Dict:
    """Tool: Find nearby places using Google Places API (New)"""
    if isinstance(req, dict):
        req = NearbyPlaceRequest(**req)

    api_key = os.environ.get("GOOGLE_PLACES_API_KEY")
    if not api_key:
        raise ValueError("Missing GOOGLE_PLACES_API_KEY in environment variables")

    endpoint = "https://places.googleapis.com/v1/places:searchNearby"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "places.displayName,places.formattedAddress,"
            "places.location,places.rating,places.types"
        ),
    }

    body = {
        "includedTypes": req.included_types,
        "maxResultCount": req.max_result_count,
        "locationRestriction": {
            "circle": {
                "center": {"latitude": req.latitude, "longitude": req.longitude},
                "radius": req.radius,
            }
        },
    }

    try:
        res = requests.post(endpoint, headers=headers, data=json.dumps(body))
        res.raise_for_status()
        data = res.json()

        places = data.get("places", [])
        results = [
            {
                "name": p.get("displayName", {}).get("text", "N/A"),
                "address": p.get("formattedAddress", "N/A"),
                "rating": p.get("rating", "N/A"),
                "types": ", ".join(t.replace("_", " ").title() for t in p.get("types", [])),
            }
            for p in places[:8]
        ]
        return {"places": results} if results else {"message": "No places found."}

    except Exception as e:
        return {"error": f"Places API call failed: {e}"}
