# main.py

import os
import uuid
import asyncio
import base64
from typing import Dict, List, Optional
import mimetypes

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from google.adk.runners import Runner
from google.genai import types
from google.adk.sessions import DatabaseSessionService
from contextlib import asynccontextmanager

import googlemaps
import google.generativeai as genai

from nearLens_agent.agent import root_agent 

# ===========================================
#  1️⃣ LOAD CONFIGURATION
# ===========================================
load_dotenv()

DB_URL = "sqlite:///./sessions.db"
APP_NAME = "NearLens"
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
#  2️⃣ FASTAPI APP SETUP
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
#  4️⃣ HELPER FUNCTIONS
# ===========================================
def get_location_name(lat: float, lon: float) -> str:
    """
    Get human-readable location name using Nominatim first, then Google Maps as fallback.
    Returns "Unknown location" if neither can determine it.
    """
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
) -> Optional[str]:
    """
    Execute agent pipeline and return ONLY the final user-facing text response.
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

    final_text_response = None
    async for event in events:
        if event.is_final_response() and event.content and event.content.parts:
            text_parts = [p.text for p in event.content.parts if p.text]
            if text_parts:
                final_text_response = "\n".join(text_parts)
        # For debugging, uncomment the line below to see all intermediate events
        # print(f"DEBUG: Agent Event: {event}")

         # 🔹 Process function calls (arguments)
        calls = event.get_function_calls()
        if calls:
            for call in calls:
                if call.name == "find_nearby_places":
                    arguments = call.args
                    # print(f"\n Items arguments: {arguments}")

                  

            # 🔹 Process function responses (results)
        responses = event.get_function_responses()
        if responses:
            for response in responses:
                if response.name == "find_nearby_places":
                    result_dict = response.response
                    return result_dict

                  


# ===========================================
#  5️⃣ ROUTES
# ===========================================
@app.get("/")
async def home():
    return {"message": "Welcome to NearLens API 👁️", "status": "running"}

@app.post("/api/upload")
async def upload_image(
    file: UploadFile = File(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
):
    """
    Handle image uploads with location info and run AI-based analysis.
    Returns a single final output from the agent.
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
        os.makedirs("uploads", exist_ok=True)
        filename = f"uploads/{uuid.uuid4()}_{file.filename}"
        with open(filename, "wb") as buffer:
            buffer.write(await file.read())

        print(f"📸 Image received: {filename}")
        print(f"📍 Location: lat={latitude}, lon={longitude}")

        # Construct ADK input message with explicit parts for agent parsing
        # The prompt now includes raw lat/lon directly for the LLM to use
        parts = [
            types.Part.from_text(text="Analyze this image for nearby insights and recommend places."),
            types.Part.from_text(text=f"User's coordinates for search: Lat={latitude}, Lon={longitude}"), # Pass raw coordinates
        ]

        mime_type, _ = mimetypes.guess_type(filename)
        if not mime_type or not mime_type.startswith('image/'):
            print(f"⚠️ Could not determine image MIME type for {filename}, defaulting to image/jpeg.")
            mime_type = "image/jpeg"
        
        with open(filename, "rb") as f:
            image_bytes = f.read()
        parts.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type))

        input_message = types.Content(
            role="user",
            parts=parts
        )

        final_output = await get_agent_final_output(session_service, user_id, session_id, input_message)

        os.remove(filename)

        return {
            "status": "success",
            "latitude_input": latitude,
            "longitude_input": longitude,
            "agent_response": final_output if final_output else "No specific response generated by the agent.",
        }

    except Exception as e:
        print(f"❌ Upload failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"error": f"Image upload failed: {str(e)}"}

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
#  6️⃣ RUN SERVER
# ===========================================
# uvicorn main:app --reload