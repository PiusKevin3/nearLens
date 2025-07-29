import os
import json
import asyncio
import warnings
import time
import base64 # Explicitly import base64 if not already there

from dotenv import load_dotenv

from google.genai.types import Part, Content, Blob
from google.adk.runners import InMemoryRunner
from google.adk.agents import LiveRequestQueue
from google.adk.agents.run_config import RunConfig,StreamingMode
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from google.genai import types

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
    run_config = RunConfig(
        response_modalities=[modality],
        output_audio_transcription=types.AudioTranscriptionConfig(), # Enables ADK to send text transcription of its spoken response
        input_audio_transcription=types.AudioTranscriptionConfig(),  # Enables ADK to transcribe user's audio input
        realtime_input_config=types.RealtimeInputConfig(),          # Enables real-time input processing
        streaming_mode=StreamingMode.BIDI,                           # Crucial for continuous bidirectional streaming with VAD
        save_input_blobs_as_artifacts=True,
    )
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
    Differentiates between structured output (for UI) and speakable summary (for audio).
    Accumulates partial text events.
    """
    # Buffer to accumulate partial text from each agent for the current session.
    # This ensures that incomplete JSON strings are not parsed.
    agent_text_buffers = {} # {agent_name: accumulated_text_string}

    try:
        async for event in live_events:
            event_author = getattr(event, 'author', 'unknown_agent')

            # Initialize buffer for this agent if not present
            if event_author not in agent_text_buffers:
                agent_text_buffers[event_author] = ""

            # Handle turn completion or interruption signals first
            if event.turn_complete or event.interrupted:
                message = {
                    "turn_complete": event.turn_complete,
                    "interrupted": event.interrupted,
                }
                await websocket.send_text(json.dumps(message))
                print(f"[AGENT TO CLIENT]: {message}")
                
                # Clear buffer for this agent on turn completion, in case of lingering partials
                agent_text_buffers[event_author] = ""
                continue

            # Ensure there's content and parts to process
            part: Part = event.content.parts[0] if event.content and event.content.parts else None
            if not part:
                continue # No relevant content part, move to next event

            # If it's audio data, send it regardless of mode
            if part.inline_data and part.inline_data.mime_type.startswith("audio/pcm"):
                audio_data = part.inline_data.data
                if audio_data:
                    await websocket.send_text(json.dumps({
                        "mime_type": "audio/pcm",
                        "data": base64.b64encode(audio_data).decode("ascii"),
                    }))
                    print(f"[AGENT TO CLIENT]: audio/pcm: {len(audio_data)} bytes. (From {event_author})")
                continue # Audio handled, move to next event

            # If it's text data
            if part.text:
                # If it's a partial event, just append to the buffer and send the chunk.
                # Do NOT attempt JSON parsing here, as the text is incomplete.
                if event.partial:
                    agent_text_buffers[event_author] += part.text
                    await websocket.send_text(json.dumps({
                        "mime_type": "text/plain",
                        "data": part.text, # Send the current partial chunk
                        "agent": event_author,
                        "partial": True # Indicate to client this is a partial update
                    }))
                    print(f"[AGENT TO CLIENT]: text/plain (partial): '{part.text}' (From {event_author})")
                    continue # Wait for the next part or the final event

                # If we reach here, it's a non-partial event, meaning this is the final chunk
                # or the entire message was sent in one go.
                full_text_content = agent_text_buffers[event_author] + part.text
                # Clear the buffer for this agent as the full message is now processed.
                agent_text_buffers[event_author] = ""

                is_json_output = False
                # Attempt to parse as a structured JSON output ONLY if it's from the shopping_worker_agent
                # and the full accumulated content starts with the JSON markdown fence.
                if event_author == "shopping_worker_agent" and full_text_content.strip().startswith("```json"):
                    print(f"[AGENT TO CLIENT]: Detected potential JSON code block from {event_author} (full message).")
                    try:
                        # Extract the JSON string from within the markdown block.
                        # This slicing is designed to remove the "```json" prefix and "```" suffix.
                        json_str_for_parsing = full_text_content.strip()[len("```json"): -len("```")].strip()
                        
                        parsed_data = json.loads(json_str_for_parsing)
                        is_json_output = True

                        # Send as structured data to client (for UI display of products)
                        await websocket.send_text(json.dumps({
                            "type": "agent_structured_output", # Custom type for structured data
                            "agent": event_author, # Indicate which agent sent this structured data
                            "data": parsed_data
                        }))
                        print(f"[AGENT TO CLIENT]: Sent parsed structured output from {event_author}.")

                        # If in audio mode and this is the shopping_worker_agent's JSON,
                        # we DO NOT want to generate audio for this. Skip further processing for this event.
                        if is_audio:
                            print(f"[AGENT TO CLIENT]: Suppressing audio for structured JSON from {event_author} in audio mode.")
                            continue # Move to the next event in the live_events stream

                    except (json.JSONDecodeError, IndexError) as e:
                        print(f"[AGENT ERROR] JSON Decode Error or indexing issue from full text part ({event_author}): {e}")
                        print(f"Failed JSON string (from full text part, attempting parse): '{json_str_for_parsing}'")
                        is_json_output = False # If parsing fails, treat it as regular text below
                    except Exception as e:
                        print(f"[AGENT ERROR] General error processing JSON from full text part ({event_author}): {e}")
                        is_json_output = False # If general error, treat as regular text below

                # If it's not a JSON block (or JSON parsing failed), then it's a plain text message.
                # This includes the final summary from the `shop_agent`.
                if not is_json_output:
                    message_type = "text/plain"
                    # If this is the `shop_agent`'s output and we are in audio mode,
                    # mark it as the final summary for text-to-speech.
                    if event_author == "shop_agent" and is_audio:
                        message_type = "final_text_summary"

                    await websocket.send_text(json.dumps({
                        "mime_type": "text/plain",
                        "data": full_text_content,
                        "agent": event_author,
                        "type": message_type # Differentiate summary for TTS (client-side)
                    }))
                    print(f"[AGENT TO CLIENT]: Full text output: '{full_text_content}' (From {event_author}, type: {message_type})")
                    # No `continue` here, as this is the intended final text/audio output for the user's turn.

    except WebSocketDisconnect:
        print("[AGENT TO CLIENT]: WebSocket disconnected gracefully.")
    except Exception as e:
        print(f"[AGENT ERROR] Error in agent_to_client_messaging: {e}")

# --- Client to Agent Messaging ---

async def client_to_agent_messaging(websocket: WebSocket, live_request_queue: LiveRequestQueue, state: dict, user_id: int):
    """
    Handles messages coming from the client and sends them to the agent.
    Removed explicit end of audio turn signaling via empty content,
    relying on ADK's implicit end-of-stream detection.
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
                # print(f"[KEEPALIVE] Pong received from client #{user_id}") # Too chatty
                continue

            try:
                message = json.loads(msg_json)
            except json.JSONDecodeError:
                print(f"[CLIENT ERROR] Invalid JSON message received: {msg_json}")
                continue

            mime_type = message.get("mime_type")
            data = message.get("data")

            # Process text input from client
            if mime_type == "text/plain":
                content = Content(role="user", parts=[Part.from_text(text=data)])
                live_request_queue.send_content(content=content)
                print(f"[CLIENT TO AGENT]: Text: {data}")

            # Process audio input from client
            elif mime_type == "audio/pcm":
                if websocket.client_state.name != "CONNECTED":
                    print(f"[CLIENT ERROR] Skipping audio: client disconnected.")
                    break
                audio_bytes = base64.b64decode(data)
                blob = Blob(data=audio_bytes, mime_type=mime_type)
                live_request_queue.send_realtime(blob)
                print(f"[CLIENT TO AGENT]: Audio: {len(audio_bytes)} bytes")

            # Removed the 'endOfAudio' command logic.
            # The ADK is expected to detect the end of the audio turn implicitly
            # when audio chunks stop arriving for a certain duration (silence detection).

            else:
                print(f"[CLIENT ERROR] Unsupported message: {message}")

    except WebSocketDisconnect:
        print("[CLIENT] WebSocket disconnected gracefully.")
    except Exception as e:
        print(f"[CLIENT ERROR] Error in client_to_agent_messaging: {e}")

# --- FastAPI App Setup ---

app = FastAPI()

# --- CORS Middleware (Crucial for frontend communication) ---
origins = [
    "http://localhost:3000",  # Dev frontend
    "http://127.0.0.1:3000",
    "https://aavraa.com",  # Production frontend domain
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# --- End CORS Middleware ---

@app.get("/")
def health():
    return {"status": "ok", "app": "aavraa-agent"}

# Dedicated Audio-Only WebSocket Endpoint
@app.websocket("/ws/audio/{user_id}")
async def audio_websocket_endpoint(websocket: WebSocket, user_id: int):
    """
    Dedicated audio-only WebSocket endpoint.
    Forces audio mode regardless of query parameters.
    """
    await websocket.accept()
    print(f"Audio-only client #{user_id} connected")

    # Start agent session with audio mode forced
    live_events, live_request_queue = await start_agent_session(str(user_id), is_audio=True)

    # State for tracking keepalive pings
    state = {
        "last_pong": asyncio.get_event_loop().time(),
        "missed_pongs": 0,
        "max_missed_pongs": 4,
    }

    # Task for sending keepalive pings
    async def keepalive_ping():
        try:
            while True:
                await websocket.send_text("__ping__")
                await asyncio.sleep(10)

                now = asyncio.get_event_loop().time()
                if now - state["last_pong"] > 10:
                    state["missed_pongs"] += 1
                    print(f"[KEEPALIVE] Missed pong #{state['missed_pongs']} from audio client #{user_id}")

                    if state["missed_pongs"] >= state["max_missed_pongs"]:
                        warning_message = {
                            "type": "disconnect_warning",
                            "reason": "No pong response, closing connection."
                        }
                        await websocket.send_text(json.dumps(warning_message))
                        print(f"[KEEPALIVE] Disconnecting audio client #{user_id} due to missed pongs.")
                        await websocket.close(code=1001)
                        break
        except Exception as e:
            print(f"[KEEPALIVE ERROR] Error in keepalive_ping: {e}")

    # Send initial prompt (Optional, but useful for a first greeting/intro)
    initial_prompt = "What are you?" # Or a more audio-friendly greeting
    content = Content(role="user", parts=[Part.from_text(text=initial_prompt)])
    live_request_queue.send_content(content=content)
    print(f"[SERVER] Sent initial prompt: '{initial_prompt}' to audio client.")

    # Create and run concurrent tasks
    agent_task = asyncio.create_task(agent_to_client_messaging(websocket, live_events, True))
    client_task = asyncio.create_task(client_to_agent_messaging(websocket, live_request_queue, state, user_id))
    ping_task = asyncio.create_task(keepalive_ping())

    # Wait for any task to complete
    done, pending = await asyncio.wait(
        [agent_task, client_task, ping_task],
        return_when=asyncio.FIRST_COMPLETED
    )

    # Cancel remaining tasks
    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # Clean up
    live_request_queue.close()
    print(f"[SERVER] Audio client #{user_id} disconnected")

# Dedicated Text-Only WebSocket Endpoint
@app.websocket("/ws/text/{user_id}")
async def text_websocket_endpoint(websocket: WebSocket, user_id: int):
    """
    Dedicated text-only WebSocket endpoint.
    Forces text mode regardless of query parameters.
    """
    await websocket.accept()
    print(f"Text-only client #{user_id} connected")

    # Start agent session with text mode forced
    live_events, live_request_queue = await start_agent_session(str(user_id), is_audio=False)

    # State for tracking keepalive pings
    state = {
        "last_pong": asyncio.get_event_loop().time(),
        "missed_pongs": 0,
        "max_missed_pongs": 4,
    }

    # Task for sending keepalive pings
    async def keepalive_ping():
        try:
            while True:
                await websocket.send_text("__ping__")
                await asyncio.sleep(10)

                now = asyncio.get_event_loop().time()
                if now - state["last_pong"] > 10:
                    state["missed_pongs"] += 1
                    print(f"[KEEPALIVE] Missed pong #{state['missed_pongs']} from text client #{user_id}")

                    if state["missed_pongs"] >= state["max_missed_pongs"]:
                        warning_message = {
                            "type": "disconnect_warning",
                            "reason": "No pong response, closing connection."
                        }
                        await websocket.send_text(json.dumps(warning_message))
                        print(f"[KEEPALIVE] Disconnecting text client #{user_id} due to missed pongs.")
                        await websocket.close(code=1001)
                        break
        except Exception as e:
            print(f"[KEEPALIVE ERROR] Error in keepalive_ping: {e}")

    # Send initial prompt (Optional, but useful for a first greeting/intro)
    initial_prompt = "What are you?"
    content = Content(role="user", parts=[Part.from_text(text=initial_prompt)])
    live_request_queue.send_content(content=content)
    print(f"[SERVER] Sent initial prompt: '{initial_prompt}' to text client.")

    # Create and run concurrent tasks
    agent_task = asyncio.create_task(agent_to_client_messaging(websocket, live_events, False))
    client_task = asyncio.create_task(client_to_agent_messaging(websocket, live_request_queue, state, user_id))
    ping_task = asyncio.create_task(keepalive_ping())

    # Wait for any task to complete
    done, pending = await asyncio.wait(
        [agent_task, client_task, ping_task],
        return_when=asyncio.FIRST_COMPLETED
    )

    # Cancel remaining tasks
    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # Clean up
    live_request_queue.close()
    print(f"[SERVER] Text client #{user_id} disconnected")

# Removed the general /ws/{user_id} endpoint as it's now redundant with dedicated /ws/audio and /ws/text
# This simplifies the routing and ensures clear modality handling.