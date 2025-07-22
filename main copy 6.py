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
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.genai import types

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware 

# Assuming aavraa_assistant.agent and root_agent exist in your project structure
# Make sure your agent.py file is correctly configured to be imported here.
# Change this import to your actual root agent name. You had 'aavraa_orchestrator'
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
        agent=aavraa_orchestrator, # Use your orchestrator agent here
    )
    session = await runner.session_service.create_session(
        app_name=APP_NAME,
        user_id=user_id,
    )
    modality = "AUDIO" if is_audio else "TEXT"
    
    # --- Correct RunConfig for ADK streaming with VAD ---
    run_config = RunConfig(
        response_modalities=[modality],
        output_audio_transcription=types.AudioTranscriptionConfig(), # Enables ADK to send text transcription of its spoken response
        input_audio_transcription=types.AudioTranscriptionConfig(),  # Enables ADK to transcribe user's audio input
        realtime_input_config=types.RealtimeInputConfig(),          # Enables real-time input processing
        streaming_mode=StreamingMode.BIDI,                           # Crucial for continuous bidirectional streaming with VAD
        save_input_blobs_as_artifacts=True,
    )
    # --- End RunConfig ---

    live_request_queue = LiveRequestQueue() # This should be the official ADK LiveRequestQueue if you have it
    live_events = runner.run_live(
        session=session,
        live_request_queue=live_request_queue,
        run_config=run_config,
    )
    return live_events, live_request_queue

# --- Agent to Client Messaging ---

async def agent_to_client_messaging(websocket: WebSocket, live_events): # Removed is_audio param as filter is elsewhere
    """
    Handles messages coming from the agent and sends them to the client.
    Sends only partial text updates for streaming, and full audio.
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

            # If it's text data, send it ONLY IF IT'S A PARTIAL EVENT (for live captions)
            # The final full text is implicitly communicated via turn_complete after all partials.
            elif part.text:
                if event.partial: 
                    await websocket.send_text(json.dumps({
                        "mime_type": "text/plain",
                        "data": part.text,
                    }))
                    print(f"[AGENT TO CLIENT]: text/plain (partial): {part.text}")
                else:
                    # This is likely the final text response.
                    # Frontend should have accumulated this from partials already.
                    # Or it's a non-audio response in text-only mode (which is fine).
                    # We don't send it again to avoid duplication if frontend handles partials.
                    # You *could* send it if event.partial is False, but ensure frontend deduplicates.
                    # For a clean streaming experience, often only partials are streamed.
                    print(f"[AGENT TO CLIENT]: text/plain (full/non-partial): '{part.text}' (not explicitly sent as a separate message if frontend aggregates partials)")


    except Exception as e:
        print(f"[AGENT ERROR] Error in agent_to_client_messaging: {e}")

# --- Client to Agent Messaging ---

async def client_to_agent_messaging(websocket: WebSocket, live_request_queue: LiveRequestQueue, state: dict, user_id: int):
    """
    Handles messages coming from the client and sends them to the agent.
    ADK's VAD handles end of audio turn.
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
            # command = message.get("command") # No longer needed if frontend only streams audio

            # Process text input from client
            if mime_type == "text/plain":
                content = Content(role="user", parts=[Part.from_text(text=data)])
                live_request_queue.send_content(content=content)
                print(f"[CLIENT TO AGENT]: Text: '{data}'")

            # Process audio input from client (continuous streaming, ADK handles VAD)
            elif mime_type == "audio/pcm":
                if websocket.client_state.name != "CONNECTED":
                    print(f"[CLIENT ERROR] Skipping audio: client disconnected.")
                    break
                audio_bytes = base64.b64decode(data)
                blob = Blob(data=audio_bytes, mime_type=mime_type)
                live_request_queue.send_realtime(blob)
                print(f"[CLIENT TO AGENT]: Audio: {len(audio_bytes)} bytes")

            # --- REMOVE THIS BLOCK: ADK handles end of audio turns via VAD ---
            # elif command == "endOfAudio":
            #     silent_audio = bytes([128] * 320)
            #     live_request_queue.send_realtime(Blob(data=silent_audio, mime_type="audio/pcm"))
            #     # This was the workaround; no longer needed with proper ADK config
            #     live_request_queue.send_content(Content(role="user", parts=[Part.from_text(text="")])) 
            #     print(f"[CLIENT TO AGENT]: End of audio signal received -> Sent empty content to end turn.")
            # --- END REMOVAL ---

            else:
                print(f"[CLIENT ERROR] Unsupported message: {message}")

    except WebSocketDisconnect:
        print("[CLIENT] WebSocket disconnected gracefully.")
    except Exception as e:
        print(f"[CLIENT ERROR] Error in client_to_agent_messaging: {e}")

# --- FastAPI App Setup ---

app = FastAPI()

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
def health():
    return {"status": "ok", "app": "aavraa-agent"}


# --- WebSocket Endpoint (Restored dynamic is_audio, removed session dict attempt) ---
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

    # Start the agent session with the determined modality (DYNAMIC AGAIN)
    # live_events, live_request_queue = await start_agent_session(str(user_id), is_audio=is_audio)
    live_events, live_request_queue = await start_agent_session(str(user_id), is_audio="true")


    # Send an initial prompt to the agent when the session starts (for new connections)
    initial_prompt = "What are you?"
    content = Content(role="user", parts=[Part.from_text(text=initial_prompt)])
    live_request_queue.send_content(content=content)
    print(f"[SERVER] Sent initial prompt: {initial_prompt}")

    # State for tracking keepalive pings
    state = {
        "last_pong": time.time(), # Use time.time()
        "missed_pongs": 0,
        "max_missed_pongs": 4, 
    }

    # Task for sending keepalive pings to the client
    async def keepalive_ping():
        try:
            while True:
                await websocket.send_text("__ping__")
                print(f"[KEEPALIVE] Sent ping to client #{user_id}")
                await asyncio.sleep(10) 

                now = time.time() # Use time.time()
                if now - state["last_pong"] > 10: 
                    state["missed_pongs"] += 1
                    print(f"[KEEPALIVE] Missed pong #{state['missed_pongs']} from client #{user_id}")

                    if state["missed_pongs"] >= state["max_missed_pongs"]:
                        warning_message = {
                            "type": "disconnect_warning",
                            "reason": "No pong response, closing connection."
                        }
                        await websocket.send_text(json.dumps(warning_message))
                        print(f"[KEEPALIVE] Disconnecting client #{user_id} due to missed pongs.")
                        await websocket.close(code=1001) 
                        break 
        except Exception as e:
            print(f"[KEEPALIVE ERROR] Error in keepalive_ping: {e}")

    # Create and run concurrent tasks for communication and keepalive
    # Removed the 'is_audio' param from agent_to_client_messaging as it's no longer used for filtering
    agent_task = asyncio.create_task(agent_to_client_messaging(websocket, live_events)) 
    client_task = asyncio.create_task(client_to_agent_messaging(websocket, live_request_queue, state, user_id))
    ping_task = asyncio.create_task(keepalive_ping())

    # Wait for any of the tasks to complete
    done, pending = await asyncio.wait(
        [agent_task, client_task, ping_task],
        return_when=asyncio.FIRST_COMPLETED
    )

    # Cancel any remaining pending tasks
    for task in pending:
        task.cancel()
        try:
            await task 
        except asyncio.CancelledError:
            pass

    # Ensure the live request queue is closed when the session ends
    live_request_queue.close()
    print(f"[SERVER] Client #{user_id} disconnected")