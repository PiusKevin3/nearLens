import os
import json
import asyncio
import base64
import warnings
import time # Added for silence detection timestamps

from pathlib import Path
from dotenv import load_dotenv

from google.genai.types import (
    Part,
    Content,
    Blob,
)

from google.adk.runners import InMemoryRunner
from google.adk.agents import LiveRequestQueue # This is the official one now!
from google.adk.agents.run_config import RunConfig

from fastapi import FastAPI, WebSocket, WebSocketDisconnect # Added WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Assuming your agent is at 'google_search_agent.agent.root_agent'
# If your agent is still `aavraa_assistant.agent.root_agent`, change this import back.
from aavraa_assistant.agent import root_agent 

warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

#
# Aavraa Streaming
#

# Load Gemini API Key
load_dotenv()

APP_NAME = "Aavraa"

# Session persistence (needed for multi-user connections if you reuse the FastAPI app)
sessions = {}

# Silence detection constants (you can adjust these)
SILENCE_TIMEOUT_SECONDS = 1.0 # How long to wait for silence (in seconds)
SILENCE_THRESHOLD = 500     # Max amplitude for 16-bit PCM to be considered silent (tune this)
MIN_AUDIO_CHUNK_SIZE = 100  # Minimum bytes in an audio chunk to perform VAD check

# --- Agent Session Setup (minor change: added user_id to session storage) ---
async def start_agent_session(user_id: str, is_audio: bool = False): # Type hint user_id as str
    """Starts an agent session"""
    runner = InMemoryRunner(
        app_name=APP_NAME,
        agent=root_agent,
    )
    session = await runner.session_service.create_session(
        app_name=APP_NAME,
        user_id=user_id,
    )
    modality = "AUDIO" if is_audio else "TEXT"
    run_config = RunConfig(response_modalities=[modality])
    live_request_queue = LiveRequestQueue()
    live_events = runner.run_live(
        session=session,
        live_request_queue=live_request_queue,
        run_config=run_config,
    )
    return live_events, live_request_queue


# --- Agent to Client Messaging (no change needed in its core logic) ---
# This part is fine. It correctly sends both audio/pcm and text/plain.
async def agent_to_client_messaging(websocket: WebSocket, live_events):
    """Agent to client communication"""
    try: # Added try-except for robust error handling
        async for event in live_events:
            if event.turn_complete or event.interrupted:
                message = {
                    "turn_complete": event.turn_complete,
                    "interrupted": event.interrupted,
                }
                await websocket.send_text(json.dumps(message))
                # print(f"[AGENT TO CLIENT]: {message}") # Debug print
                continue

            part: Part = (
                event.content and event.content.parts and event.content.parts[0]
            )
            if not part:
                continue

            is_audio = part.inline_data and part.inline_data.mime_type.startswith("audio/pcm")
            if is_audio:
                audio_data = part.inline_data and part.inline_data.data
                if audio_data:
                    message = {
                        "mime_type": "audio/pcm",
                        "data": base64.b64encode(audio_data).decode("ascii")
                    }
                    await websocket.send_text(json.dumps(message))
                    print(f"[AGENT TO CLIENT]: audio/pcm: {len(audio_data)} bytes.")
                    continue

            if part.text and event.partial:
                message = {
                    "mime_type": "text/plain",
                    "data": part.text
                }
                await websocket.send_text(json.dumps(message))
                print(f"[AGENT TO CLIENT]: text/plain: {message}")
    except Exception as e:
        print(f"[AGENT ERROR] Error in agent_to_client_messaging: {e}")


# --- Background Task for Silence Detection (using state and end_realtime()) ---
async def silence_detector_task(user_id: str, live_request_queue: LiveRequestQueue, state: dict):
    """
    Monitors incoming audio for silence and calls live_request_queue.end_realtime().
    """
    print(f"[SILENCE DETECTOR] (User #{user_id}): Task started.")
    await asyncio.sleep(0.5) # Give some time for initial setup before starting detection
    while True:
        try:
            # Only detect silence if an audio turn is considered active (i.e., non-silent audio has been received)
            if state.get("current_audio_turn_active", False):
                last_audio_time = state.get("last_audio_time")
                if last_audio_time and (time.time() - last_audio_time > SILENCE_TIMEOUT_SECONDS):
                    print(f"[SILENCE DETECTOR] (User #{user_id}): Silence detected ({time.time() - last_audio_time:.2f}s). Ending current audio turn with end_realtime().")
                    state["current_audio_turn_active"] = False # Mark turn as inactive
                    state["last_audio_time"] = 0 # Reset last audio time to prevent immediate re-trigger

                    # This is the correct, explicit signal to the ADK to end the current real-time stream.
                    live_request_queue.end_realtime() 
                    
            await asyncio.sleep(0.1)  # Check every 100ms for silence
        except asyncio.CancelledError:
            print(f"[SILENCE DETECTOR] (User #{user_id}): Task cancelled.")
            break
        except Exception as e:
            print(f"[SILENCE DETECTOR ERROR] (User #{user_id}): {e}")
            await asyncio.sleep(0.5) # Prevent tight loop on error


# --- Client to Agent Messaging (now feeds into silence detector) ---
async def client_to_agent_messaging(websocket: WebSocket, live_request_queue: LiveRequestQueue, state: dict, user_id: str):
    """Client to agent communication"""
    try: # Added try-except for robust error handling
        while True:
            message_json = await websocket.receive_text()
            
            # Keepalive ping/pong handling (ADK examples usually have this)
            if message_json.strip() == "__pong__":
                state["last_pong"] = time.time() # Update last pong time
                # print(f"[KEEPALIVE] Pong received from client #{user_id}") # Debug print
                continue

            try:
                message = json.loads(message_json)
            except json.JSONDecodeError:
                print(f"[CLIENT ERROR] Invalid JSON message received from #{user_id}: {message_json}")
                continue

            mime_type = message.get("mime_type") # Use .get for safety
            data = message.get("data") # Use .get for safety

            if mime_type == "text/plain":
                # If a text input comes, it implicitly ends any ongoing audio turn.
                if state.get("current_audio_turn_active", False):
                    print(f"[CLIENT TO AGENT] (User #{user_id}): Text input received, force-ending current audio turn.")
                    state["current_audio_turn_active"] = False
                    state["last_audio_time"] = 0 # Reset timer so silence detector doesn't fire for new text turn
                    live_request_queue.end_realtime() # Explicitly end previous audio stream if text interrupts it.
                
                content = Content(role="user", parts=[Part.from_text(text=data)])
                live_request_queue.send_content(content=content)
                print(f"[CLIENT TO AGENT]: Text received: '{data}' -> Sent to ADK.")

            elif mime_type == "audio/pcm":
                # Ensure websocket is still connected
                # This check might be redundant if the outer loop handles WebSocketDisconnect
                # but good for safety if errors can occur on receive/send.
                if websocket.client_state.name != "CONNECTED": 
                    print(f"[CLIENT ERROR] Skipping audio: client disconnected.")
                    break
                
                decoded_data = base64.b64decode(data)
                
                # Basic silence detection for incoming chunks before sending to ADK
                is_silent_chunk = True
                if len(decoded_data) >= MIN_AUDIO_CHUNK_SIZE:
                    # Convert PCM to 16-bit signed integers for amplitude check
                    samples = [int.from_bytes(decoded_data[i:i+2], byteorder='little', signed=True) for i in range(0, len(decoded_data), 2)]
                    for sample in samples:
                        if abs(sample) > SILENCE_THRESHOLD:
                            is_silent_chunk = False
                            break
                
                if not is_silent_chunk:
                    state["last_audio_time"] = time.time() # Update timestamp only for non-silent audio
                    state["current_audio_turn_active"] = True # Mark that an audio turn is active
                    live_request_queue.send_realtime(Blob(data=decoded_data, mime_type=mime_type))
                    # print(f"[CLIENT TO AGENT]: Audio: {len(decoded_data)} bytes. Last active: {state['last_audio_time']:.2f}")
                # else:
                    # print(f"[CLIENT TO AGENT]: Silent audio chunk ({len(decoded_data)} bytes) ignored.")
                    # Do not update last_audio_time for silent chunks, let the timer expire naturally

            # The 'endOfAudio' command from frontend should now be removed from frontend.
            # Backend silence detection or text input will manage turn ends.
            # No `elif message.get("command") == "endOfAudio":` block here.
            
            else:
                print(f"[CLIENT ERROR] Unsupported message from #{user_id}: {message}")

    except WebSocketDisconnect: # Catch specific disconnect exception
        print(f"[CLIENT] WebSocket disconnected gracefully for client #{user_id}.")
    except Exception as e:
        print(f"[CLIENT ERROR] Error in client_to_agent_messaging for client #{user_id}: {e}")


#
# FastAPI web app
#

app = FastAPI()

# Make sure your static files path is correct.
# This assumes you have a 'static' folder next to your main.py
# If your frontend is served by Next.js, this might not be strictly necessary for production,
# but it's part of the official example.
STATIC_DIR = Path("static") 
if not STATIC_DIR.exists():
    # If 'static' doesn't exist, try looking relative to the script's directory
    # or wherever your HTML/JS assets are built.
    STATIC_DIR = Path(__file__).parent / "static"
    if not STATIC_DIR.exists():
        warnings.warn("Static directory not found. Ensure 'static' folder exists with index.html")
# Removed app.mount if Next.js handles static serving, or ensure it points correctly.
# If you are using this as a standalone server for the frontend, keep it.
# app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# CORS setup (already correct)
from fastapi.middleware.cors import CORSMiddleware
origins = [
    "http://localhost:3000",  # Dev frontend
    "https://aavraa.com",  # Production frontend domain
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    """Serves the index.html"""
    # If Next.js is serving your frontend, this endpoint might not be used.
    # Otherwise, ensure STATIC_DIR is correct.
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int, is_audio: str):
    """Client websocket endpoint"""

    await websocket.accept()
    
    # Cast user_id to string for consistent dictionary key and logging
    user_id_str = str(user_id)
    is_audio_bool = (is_audio.lower() == "true") # Convert string 'is_audio' to boolean

    print(f"Client #{user_id_str} connected, audio mode: {is_audio_bool}")

    # --- Session Management: Reuse or Create New ---
    # The `sessions` dict is a simple way to keep ADK session alive across reconnects
    # within the same backend process.
    if user_id_str in sessions:
        live_events, live_request_queue = sessions[user_id_str]
        print(f"[SESSION] Reusing existing session for user #{user_id_str}.")
        # IMPORTANT: Do NOT send initial prompt again if reusing a session.
    else:
        live_events, live_request_queue = await start_agent_session(user_id_str, is_audio=is_audio_bool)
        sessions[user_id_str] = (live_events, live_request_queue)
        print(f"[SESSION] Created NEW session for user #{user_id_str}.")

        # Send an initial prompt only for NEW sessions
        initial_prompt = "What are you?"
        content = Content(role="user", parts=[Part.from_text(text=initial_prompt)])
        live_request_queue.send_content(content=content)
        print(f"[SERVER] Sent initial prompt: {initial_prompt}.")

    # State for all tasks for this WebSocket connection
    state = {
        "last_pong": time.time(),
        "missed_pongs": 0,
        "max_missed_pongs": 4,
        "last_audio_time": 0, # Timestamp of last non-silent audio chunk
        "current_audio_turn_active": False, # Is user currently "speaking" an audio turn?
    }

    # Keepalive Ping Task (moved inside endpoint to use its `state`)
    async def keepalive_ping_task():
        try:
            while True:
                await websocket.send_text("__ping__")
                # print(f"[KEEPALIVE] Sent ping to client #{user_id_str}") # Reduced logging
                await asyncio.sleep(10)

                now = time.time()
                if now - state["last_pong"] > 10:
                    state["missed_pongs"] += 1
                    print(f"[KEEPALIVE] Missed pong #{state['missed_pongs']} from client #{user_id_str}")

                    if state["missed_pongs"] >= state["max_missed_pongs"]:
                        warning_message = {
                            "type": "disconnect_warning",
                            "reason": "No pong response, closing connection."
                        }
                        await websocket.send_text(json.dumps(warning_message))
                        print(f"[KEEPALIVE] Disconnecting client #{user_id_str} due to missed pongs.")
                        await websocket.close(code=1001)
                        break
        except Exception as e:
            print(f"[KEEPALIVE ERROR] Error in keepalive_ping_task for client #{user_id_str}: {e}")

    # Start all concurrent tasks for this WebSocket connection
    agent_to_client_task = asyncio.create_task(agent_to_client_messaging(websocket, live_events))
    client_to_agent_task = asyncio.create_task(client_to_agent_messaging(websocket, live_request_queue, state, user_id_str))
    ping_task = asyncio.create_task(keepalive_ping_task())
    silence_detector_task_instance = asyncio.create_task(silence_detector_task(user_id_str, live_request_queue, state))

    # Wait until one of the tasks completes or an exception occurs
    tasks = [agent_to_client_task, client_to_agent_task, ping_task, silence_detector_task_instance]
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

    # Clean up pending tasks if one finishes prematurely
    for task in pending:
        task.cancel()
        try:
            await task  # Await cancellation to avoid runtime warnings
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[TASK CLEANUP ERROR] Error cancelling task for client #{user_id_str}: {e}")

    # Clean up resources associated with this WebSocket connection
    # Note: live_request_queue.close() might need to be called conditionally if
    # the runner's session service manages this lifecycle for reused sessions.
    # For now, let's keep it here as per the original structure.
    live_request_queue.close() 

    # If the session is no longer active (e.g., all tasks done, or a disconnect)
    # and the ADK runner also manages session lifecycle, this might be redundant.
    # But it's good practice for this simple global dict.
    if user_id_str in sessions:
        del sessions[user_id_str]

    print(f"Client #{user_id_str} disconnected")