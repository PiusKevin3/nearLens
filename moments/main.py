# main.py

import os
import uuid
import asyncio
from typing import Dict, Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

import googlemaps
import google.generativeai as genai
from contextlib import asynccontextmanager
from momentLens_agent.agent import root_agent
from google.adk.sessions import DatabaseSessionService
from google.adk.runners import Runner
from google.genai import types

# ===========================================
# 1️⃣ LOAD CONFIGURATION
# ===========================================
load_dotenv()

DB_URL = "sqlite:///./sessions.db"
APP_NAME = "MomentLens"
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

gmaps = None
if GOOGLE_MAPS_API_KEY:
    try:
        gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)
        print("✅ Google Maps client initialized.")
    except Exception as e:
        print(f"❌ Google Maps client initialization failed: {str(e)}")

try:
    genai.configure(api_key=GEMINI_API_KEY)
    print("✅ Gemini API configured successfully.")
except Exception as e:
    print(f"❌ Failed to configure Gemini API: {str(e)}")

# ===========================================
# 2️⃣ FASTAPI APP SETUP
# ===========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Application starting up...")
    try:
        app.state.session_service = DatabaseSessionService(db_url=DB_URL)
        print("✅ Database session service initialized")
    except Exception as e:
        print(f"❌ Database session service initialization failed: {str(e)}")
    yield
    print("Application shutting down...")

app = FastAPI(
    title="NearLens API",
    description="AI-powered Visual Local Finder for Nearby Discovery.",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===========================================
# 3️⃣ DATA MODELS
# ===========================================
class UploadPayload(BaseModel):
    latitude: float
    longitude: float
    time: str
    weather: dict

# ===========================================
# 4️⃣ HELPER FUNCTIONS
# ===========================================
def get_location_name(lat: float, lon: float) -> str:
    """Get human-readable location name using Nominatim first, then Google Maps as fallback."""
    try:
        from geopy.geocoders import Nominatim
        geolocator = Nominatim(user_agent="nearlens", timeout=10)
        location = geolocator.reverse((lat, lon))
        if location and location.address:
            return location.address
    except Exception as e:
        print(f"⚠️ Nominatim failed: {str(e)}")

    if gmaps:
        try:
            reverse_geocode = gmaps.reverse_geocode((lat, lon))
            if reverse_geocode and len(reverse_geocode) > 0:
                return reverse_geocode[0].get('formatted_address', 'Unknown location')
        except Exception as e:
            print(f"⚠️ Google Maps reverse geocode failed: {str(e)}")

    return "Unknown location"

async def get_agent_final_output(
    session_service, user_id: str, session_id: str, input_message: types.Content
) -> Optional[dict]:
    """
    Execute agent pipeline and return final response dictionary.
    """
    runner = Runner(
        app_name=APP_NAME,
        agent=root_agent,
        session_service=session_service,
    )

    events = runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=input_message,
    )

    final_result = None
    async for event in events:
        if event.is_final_response() and event.content and event.content.parts:
            # You can extract places and text if returned by agent
            text_parts = [p.text for p in event.content.parts if p.text]
            final_text = "\n".join(text_parts) if text_parts else None
            final_result = {"text": final_text, "places": []}  # default empty places

        # Process function responses (like find_nearby_places)
        responses = event.get_function_responses()
        if responses:
            for response in responses:
                if response.name == "find_nearby_places":
                    result_dict = response.response
                    final_result = result_dict
                    print(final_result)
                    return final_result

# ===========================================
# 5️⃣ ROUTES
# ===========================================
@app.get("/")
async def home():
    return {"message": "Welcome to NearLens API 👁️", "status": "running"}

@app.post("/api/upload")
async def upload_data(payload: UploadPayload):
    """
    Handle location + weather payload and run AI agent analysis.
    """
    session_service = app.state.session_service
    user_id = f"user-{uuid.uuid4()}"
    session_id = f"session-{uuid.uuid4()}"

    try:
        await session_service.create_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id
        )
        print(f"✅ Created one-shot session: {session_id}")
    except Exception as e:
        print(f"❌ Session creation failed: {str(e)}")
        return {"error": f"Failed to initialize session: {str(e)}"}

    try:
        parts = [
            types.Part.from_text(text="Analyze user's coordinates for nearby insights."),
            types.Part.from_text(text=f"User's coordinates: lat={payload.latitude}, lon={payload.longitude}"),
        ]

        input_message = types.Content(
            role="user",
            parts=parts
        )

        final_output = await get_agent_final_output(session_service, user_id, session_id, input_message)

        return {
            "status": "success",
            "latitude_input": payload.latitude,
            "longitude_input": payload.longitude,
            "agent_response": final_output if final_output else {"text": "No response generated.", "places": []},
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": f"Processing failed: {str(e)}"}

@app.get("/api/debug")
async def debug():
    lat, lon = 0.3476, 32.5827
    location = get_location_name(lat, lon)
    return {
        "lat": lat,
        "lon": lon,
        "location": location,
        "geocoding": "OK" if location != "Unknown location" else "Failed",
    }

# ===========================================
# 6️⃣ RUN SERVER
# ===========================================
# uvicorn main:app --reload
