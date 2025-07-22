import os
import json
import asyncio
import base64
import warnings
import time # Added for keepalive timing

from dotenv import load_dotenv

from google.genai.types import Part, Content, Blob
from google.adk.runners import InMemoryRunner
from google.adk.agents import LiveRequestQueue
from google.adk.agents.run_config import RunConfig
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware # Added for CORS

from aavraa_assistant.agent import aavraa_orchestrator 

warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")
load_dotenv()

APP_NAME = "Aavraa"

# --- Agent Session Setup ---

async def start_agent_session(user_id: str, is_audio: bool = False):
    """
    Initializes an agent session with the specified modality.
    """
    runner = InMemoryRunner(
        app_name=APP_NAME,
        agent=aavraa_orchestrator,
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

# --- Agent to Client Messaging ---

async def agent_to_client_messaging(websocket: WebSocket, live_events, is_audio: bool):
    """
    Handles messages coming from the agent and sends them to the client.
    Now sends text even in audio mode, and filters non-partial text events.
    """
    try:
        async for event in live_events:
            # Handle turn completion or interruption signals first
            if event.turn_complete or event.interrupted:
                message = {
                    "turn_complete": event.turn_complete,
                    "interrupted": event.interrupted,
                }
                await websocket.send_text(json.dumps(message))
                print(f"[AGENT TO CLIENT]: {message}")
                continue

            # Ensure there's content and parts to process
            part: Part = event.content.parts[0] if event.content and event.content.parts else None
            if not part:
                continue

            # If it's audio data, send it regardless of mode
            if part.inline_data and part.inline_data.mime_type.startswith("audio/pcm"):
                audio_data = part.inline_data.data
                if audio_data:
                    await websocket.send_text(json.dumps({
                        "mime_type": "audio/pcm",
                        "data": base64.b64encode(audio_data).decode("ascii"),
                    }))
                    print(f"[AGENT TO CLIENT]: audio/pcm: {len(audio_data)} bytes.")

            # If it's text data, send it ONLY IF IT'S A PARTIAL EVENT
            # This prevents sending duplicate full text responses after partials.
            elif part.text:
                # Removed the `if not is_audio` filter to always send text if available
                if event.partial: # <--- CRITICAL: Only send partial text updates
                    await websocket.send_text(json.dumps({
                        "mime_type": "text/plain",
                        "data": part.text,
                    }))
                    print(f"[AGENT TO CLIENT]: text/plain: {part.text}")
                # else:
                    # If event.partial is False, it's typically the final full text.
                    # Frontend should have already accumulated this from partials.
                    # print(f"[AGENT TO CLIENT]: Ignored non-partial text part (assumed aggregated by client): '{part.text}'")

    except Exception as e:
        print(f"[AGENT ERROR] Error in agent_to_client_messaging: {e}")

# --- Client to Agent Messaging ---

async def client_to_agent_messaging(websocket: WebSocket, live_request_queue: LiveRequestQueue, state: dict, user_id: int):
    """
    Handles messages coming from the client and sends them to the agent.
    Manages end of audio turn signaling via empty content.
    """
    try:
        while True:
            msg_json = await websocket.receive_text()

            if not msg_json.strip():
                continue

            # Handle WebSocket keepalive pongs
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
            command = message.get("command") # Explicitly capture command

            # Process text input from client
            if mime_type == "text/plain":
                content = Content(role="user", parts=[Part.from_text(text=data)])
                live_request_queue.send_content(content=content)
                print(f"[CLIENT TO AGENT]: {data}")

            # Process audio input from client
            elif mime_type == "audio/pcm":
                # Ensure websocket is still connected before processing audio
                if websocket.client_state.name != "CONNECTED":
                    print(f"[CLIENT ERROR] Skipping audio: client disconnected.")
                    break
                audio_bytes = base64.b64decode(data)
                blob = Blob(data=audio_bytes, mime_type=mime_type)
                live_request_queue.send_realtime(blob)
                print(f"[CLIENT TO AGENT]: Audio: {len(audio_bytes)} bytes")

            # Handle end of audio signal from client (e.g., when recording stops)
            # This is the signal for a complete user utterance in audio mode.
            elif command == "endOfAudio": # <--- Use the captured command
                # Send a small silent chunk (optional, helps ensure last bits of audio are processed)
                silent_audio = bytes([128] * 320) # A small silent PCM chunk
                live_request_queue.send_realtime(Blob(data=silent_audio, mime_type="audio/pcm"))
                
                # --- CRITICAL: Signal end of turn using empty content ---
                # This is the workaround for missing `end_realtime()` in your LiveRequestQueue.
                # It tells the ADK that the user's turn is complete and it should process prior input.
                live_request_queue.send_content(Content(role="user", parts=[Part.from_text(text="")]))
                print(f"[CLIENT TO AGENT]: End of audio signal received -> Sent empty content to end turn.")

            else:
                print(f"[CLIENT ERROR] Unsupported message: {message}")

    except WebSocketDisconnect:
        print("[CLIENT] WebSocket disconnected gracefully.")
    except Exception as e:
        print(f"[CLIENT ERROR] Error in client_to_agent_messaging: {e}")

# --- FastAPI App Setup ---

app = FastAPI()

# --- Re-added CORS Middleware (Crucial for frontend communication) ---
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
# --- End Re-added CORS Middleware ---

@app.get("/")
def health():
    return {"status": "ok", "app": "aavraa-agent"}


@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    """
    Main WebSocket endpoint for client connections.
    Manages session setup, message handling, and keepalives.
    """
    await websocket.accept()
    
    # Determine if the client wants audio mode based on query parameter
    is_audio = websocket.query_params.get("is_audio", "false").lower() == "true"
    print(f"Client #{user_id} connected, audio mode: {is_audio}")
    print(f"DEBUG: Determined is_audio from query params: {is_audio}")

    # Start the agent session with the determined modality
    live_events, live_request_queue = await start_agent_session(str(user_id), is_audio=is_audio)

    # Send an initial prompt to the agent when the session starts
    initial_prompt = "What are you?"
    content = Content(role="user", parts=[Part.from_text(text=initial_prompt)])
    live_request_queue.send_content(content=content)
    print(f"[SERVER] Sent initial prompt: {initial_prompt}")

    # State for tracking keepalive pings
    state = {
        "last_pong": asyncio.get_event_loop().time(), # Use time.time() for more accuracy if not in loop
        "missed_pongs": 0,
        "max_missed_pongs": 4, # Max pongs to miss before disconnecting
    }

    # Task for sending keepalive pings to the client
    async def keepalive_ping():
        try:
            while True:
                await websocket.send_text("__ping__")
                print(f"[KEEPALIVE] Sent ping to client #{user_id}")
                await asyncio.sleep(10) # Ping every 10 seconds

                now = asyncio.get_event_loop().time() # Use time.time() if not in loop scope
                if now - state["last_pong"] > 10: # If pong not received within 10 seconds of last ping
                    state["missed_pongs"] += 1
                    print(f"[KEEPALIVE] Missed pong #{state['missed_pongs']} from client #{user_id}")

                    if state["missed_pongs"] >= state["max_missed_pongs"]:
                        warning_message = {
                            "type": "disconnect_warning",
                            "reason": "No pong response, closing connection."
                        }
                        await websocket.send_text(json.dumps(warning_message))
                        print(f"[KEEPALIVE] Disconnecting client #{user_id} due to missed pongs.")
                        await websocket.close(code=1001) # Close connection with a "going away" code
                        break # Exit the ping loop
        except Exception as e:
            print(f"[KEEPALIVE ERROR] Error in keepalive_ping: {e}")

    # Create and run concurrent tasks for communication and keepalive
    agent_task = asyncio.create_task(agent_to_client_messaging(websocket, live_events, is_audio))
    client_task = asyncio.create_task(client_to_agent_messaging(websocket, live_request_queue, state, user_id))
    ping_task = asyncio.create_task(keepalive_ping())

    # Wait for any of the tasks to complete (e.g., client disconnects, error)
    done, pending = await asyncio.wait(
        [agent_task, client_task, ping_task],
        return_when=asyncio.FIRST_COMPLETED
    )

    # Cancel any remaining pending tasks
    for task in pending:
        task.cancel()
        try:
            await task # Await cancellation to avoid warnings
        except asyncio.CancelledError:
            pass

    # Ensure the live request queue is closed when the session ends
    live_request_queue.close()
    print(f"[SERVER] Client #{user_id} disconnected")