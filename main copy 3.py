import os
import json
import asyncio
import base64
import warnings
import time

from dotenv import load_dotenv

from google.genai.types import Part, Content, Blob
from google.adk.runners import InMemoryRunner
from google.adk.agents import LiveRequestQueue
from google.adk.agents.run_config import RunConfig
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

# Assuming aavraa_assistant.agent and root_agent exist in your project structure
from aavraa_assistant.agent import root_agent 

warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")
load_dotenv()

APP_NAME = "Aavraa"
sessions = {}

# Silence detection constants
SILENCE_TIMEOUT_SECONDS = 1.0 # How long to wait for silence before ending turn
SILENCE_THRESHOLD = 500 # Max amplitude value to consider as "silence" for 16-bit PCM
MIN_AUDIO_CHUNK_SIZE = 100 # Minimum bytes in an audio chunk to process (to avoid tiny noise spikes)

# --- Agent Session Setup (unchanged) ---
async def start_agent_session(user_id: str, is_audio: bool = False):
    runner = InMemoryRunner(app_name=APP_NAME, agent=root_agent)
    session = await runner.session_service.create_session(app_name=APP_NAME, user_id=user_id)
    modality = "AUDIO" if is_audio else "TEXT"
    run_config = RunConfig(response_modalities=[modality])
    live_request_queue = LiveRequestQueue()
    live_events = runner.run_live(session=session, live_request_queue=live_request_queue, run_config=run_config)
    return live_events, live_request_queue

# --- Agent to Client Messaging (unchanged) ---
async def agent_to_client_messaging(websocket: WebSocket, live_events, is_audio: bool):
    try:
        async for event in live_events:
            if event.turn_complete or event.interrupted:
                message = {"turn_complete": event.turn_complete, "interrupted": event.interrupted}
                await websocket.send_text(json.dumps(message))
                print(f"[AGENT TO CLIENT]: {message}")
                continue

            part: Part = event.content.parts[0] if event.content and event.content.parts else None
            if not part:
                continue

            if part.inline_data and part.inline_data.mime_type.startswith("audio/pcm"):
                audio_data = part.inline_data.data
                if audio_data:
                    await websocket.send_text(json.dumps({
                        "mime_type": "audio/pcm",
                        "data": base64.b64encode(audio_data).decode("ascii"),
                    }))
                    print(f"[AGENT TO CLIENT]: audio/pcm: {len(audio_data)} bytes.")
            elif part.text:
                await websocket.send_text(json.dumps({"mime_type": "text/plain", "data": part.text}))
                print(f"[AGENT TO CLIENT]: text/plain: {part.text}")
    except Exception as e:
        print(f"[AGENT ERROR] Error in agent_to_client_messaging: {e}")

# --- Background Task for Silence Detection ---
async def check_audio_timeout_task(user_id: int, live_request_queue: LiveRequestQueue, state: dict):
    """
    Checks if audio has stopped for SILENCE_TIMEOUT_SECONDS and sends end-of-turn signal.
    """
    await asyncio.sleep(0.5) # Give some buffer time before starting detection
    while True:
        try:
            # Only proceed if an audio turn is considered active
            if state.get("current_audio_turn_active", False):
                last_audio_time = state.get("last_audio_time")
                if last_audio_time and (time.time() - last_audio_time > SILENCE_TIMEOUT_SECONDS):
                    print(f"[SILENCE DETECTOR] (User #{user_id}): Silence detected ({time.time() - last_audio_time:.2f}s). Ending current audio turn.")
                    state["current_audio_turn_active"] = False # Mark turn as inactive
                    state["last_audio_time"] = 0 # Reset last audio time

                    # Send an empty user content to explicitly end the real-time stream for ADK
                    # This is the standard way to signal turn completion when `end_realtime()` is not available.
                    live_request_queue.send_content(Content(role="user", parts=[Part.from_text(text="")]))
                    # We don't break the loop here, as we need to keep monitoring for future turns.
                    # We simply reset the state flags.
            await asyncio.sleep(0.1)  # Check every 100ms
        except asyncio.CancelledError:
            print(f"[SILENCE DETECTOR] (User #{user_id}): Task cancelled.")
            break
        except Exception as e:
            print(f"[SILENCE DETECTOR ERROR] (User #{user_id}): {e}")
            await asyncio.sleep(0.5) # Prevent tight loop on error


# --- Client to Agent Messaging ---
async def client_to_agent_messaging(websocket: WebSocket, live_request_queue: LiveRequestQueue, state: dict, user_id: int):
    """
    Handles messages coming from the client and sends them to the agent.
    Updates last_audio_time for silence detection.
    """
    try:
        while True:
            msg_json = await websocket.receive_text()

            if not msg_json.strip():
                continue

            if msg_json.strip() == "__pong__":
                state["last_pong"] = asyncio.get_event_loop().time()
                state["missed_pongs"] = 0
                print(f"[KEEPALIVE] Pong received from client #{user_id}")
                continue

            try:
                message = json.loads(msg_json)
            except json.JSONDecodeError:
                print(f"[CLIENT ERROR] Invalid JSON message received: {msg_json}")
                continue

            mime_type = message.get("mime_type")
            data = message.get("data")
            # command = message.get("command") # Removed, as frontend no longer sends explicit 'endOfAudio' for silence

            if mime_type == "text/plain":
                # If a text input comes, it implicitly ends any ongoing audio turn.
                if state.get("current_audio_turn_active", False):
                    print(f"[CLIENT TO AGENT] (User #{user_id}): Text input received, force-ending audio turn.")
                    state["current_audio_turn_active"] = False
                    state["last_audio_time"] = 0 # Reset timer to allow new audio turn
                    # Sending new content effectively closes previous stream for ADK
                
                content = Content(role="user", parts=[Part.from_text(text=data)])
                live_request_queue.send_content(content=content)
                print(f"[CLIENT TO AGENT] (User #{user_id}): Text received: '{data}' -> Sent to ADK (content).")

            elif mime_type == "audio/pcm":
                if websocket.client_state.name != "CONNECTED":
                    print(f"[CLIENT ERROR] Skipping audio: client disconnected.")
                    break
                
                audio_bytes = base64.b64decode(data)
                
                # Simple silence detection for incoming chunks
                is_silent_chunk = True
                if len(audio_bytes) >= MIN_AUDIO_CHUNK_SIZE:
                    for i in range(0, len(audio_bytes), 2): # Assuming 16-bit signed PCM
                        # Convert bytes to a 16-bit signed integer
                        sample = int.from_bytes(audio_bytes[i:i+2], byteorder='little', signed=True)
                        if abs(sample) > SILENCE_THRESHOLD:
                            is_silent_chunk = False
                            break
                
                if not is_silent_chunk:
                    state["last_audio_time"] = time.time()
                    state["current_audio_turn_active"] = True # Mark that an audio turn is active
                    blob = Blob(data=audio_bytes, mime_type=mime_type)
                    live_request_queue.send_realtime(blob)
                    # print(f"[CLIENT TO AGENT]: Audio: {len(audio_bytes)} bytes. Last active: {state['last_audio_time']:.2f}")
                else:
                    print(f"[CLIENT TO AGENT]: Silent audio chunk ({len(audio_bytes)} bytes) ignored.")
                    # Do not update last_audio_time for silent chunks, let timer naturally expire

            else:
                print(f"[CLIENT ERROR] Unsupported message from #{user_id}: {message}")

    except WebSocketDisconnect:
        print(f"[CLIENT] WebSocket disconnected gracefully for client #{user_id}.")
    except Exception as e:
        print(f"[CLIENT ERROR] Error in client_to_agent_messaging for client #{user_id}: {e}")
    # No finally block for timeout_task here, as it's now managed as a separate background task.


# --- FastAPI App Setup ---

app = FastAPI()

origins = [
    "http://localhost:3000",
    "https://aavraa.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def health():
    return {"status": "ok", "app": "aavraa-agent"}


@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    await websocket.accept()
    
    is_audio = websocket.query_params.get("is_audio", "false").lower() == "true"
    print(f"Client #{user_id} connected, audio mode: {is_audio}")
    print(f"DEBUG: Determined is_audio from query params: {is_audio}")

    # Use a string key for sessions if user_id can be other than int (from frontend sessionId)
    user_id_str = str(user_id) # Ensure consistency for dictionary key

    if user_id_str in sessions: # Use user_id_str here
        live_events, live_request_queue = sessions[user_id_str] # Use user_id_str here
        print(f"[SESSION] Reusing existing session for user #{user_id_str}")
    else:
        live_events, live_request_queue = await start_agent_session(user_id_str, is_audio=is_audio) # Use user_id_str here
        # live_events, live_request_queue = await start_agent_session(user_id_str, is_audio="true")
        sessions[user_id_str] = (live_events, live_request_queue) # Use user_id_str here
        print(f"[SESSION] Created new session for user #{user_id_str}")

        initial_prompt = "What are you?"
        content = Content(role="user", parts=[Part.from_text(text=initial_prompt)])
        live_request_queue.send_content(content=content)
        print(f"[SERVER] Sent initial prompt: {initial_prompt}")

    state = {
        "last_pong": asyncio.get_event_loop().time(),
        "missed_pongs": 0,
        "max_missed_pongs": 4,
        "last_audio_time": 0, # Timestamp of last non-silent audio chunk
        "current_audio_turn_active": False, # Is user currently "speaking" an audio turn?
    }

    # Task for sending keepalive pings (unchanged)
    async def keepalive_ping():
        try:
            while True:
                await websocket.send_text("__ping__")
                print(f"[KEEPALIVE] Sent ping to client #{user_id_str}")
                await asyncio.sleep(10)

                now = asyncio.get_event_loop().time()
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
            print(f"[KEEPALIVE ERROR] Error in keepalive_ping: {e}")

    # Create and run concurrent tasks
    agent_task = asyncio.create_task(agent_to_client_messaging(websocket, live_events, is_audio))
    client_task = asyncio.create_task(client_to_agent_messaging(websocket, live_request_queue, state, user_id))
    ping_task = asyncio.create_task(keepalive_ping())
    
    # --- Start the silence detection task ---
    silence_detector_running_task = asyncio.create_task(check_audio_timeout_task(user_id, live_request_queue, state))

    # Wait for any task to complete
    done, pending = await asyncio.wait(
        [agent_task, client_task, ping_task, silence_detector_running_task], # Include the new task
        return_when=asyncio.FIRST_COMPLETED
    )

    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # On disconnect
    live_request_queue.close()
    if user_id_str in sessions: # Use user_id_str here
        del sessions[user_id_str] # Use user_id_str here
    print(f"[SERVER] Client #{user_id_str} disconnected")