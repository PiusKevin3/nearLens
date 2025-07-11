import os
import json
import asyncio
import base64
import warnings
from pathlib import Path
from dotenv import load_dotenv

from google.genai.types import Part, Content, Blob
from google.adk.runners import InMemoryRunner
from google.adk.agents import LiveRequestQueue
from google.adk.agents.run_config import RunConfig
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from aavraa_assistant.agent import root_agent

warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")
load_dotenv()

APP_NAME = "ADK Streaming example"
STATIC_DIR = Path("static")

#
# --- Agent Session Setup ---
#

async def start_agent_session(user_id: str, is_audio: bool = False):
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


#
# --- Message Handlers ---
#

async def agent_to_client_messaging(websocket: WebSocket, live_events):
    try:
        async for event in live_events:
            # Turn completion or interruption
            if event.turn_complete or event.interrupted:
                message = {
                    "turn_complete": event.turn_complete,
                    "interrupted": event.interrupted,
                }
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

            elif part.text and event.partial:
                await websocket.send_text(json.dumps({
                    "mime_type": "text/plain",
                    "data": part.text,
                }))
                print(f"[AGENT TO CLIENT]: text/plain: {part.text}")

    except Exception as e:
        print(f"[AGENT ERROR] {e}")


async def client_to_agent_messaging(websocket: WebSocket, live_request_queue: LiveRequestQueue):
    try:
        while True:
            # Decode JSON message
            msg_json = await websocket.receive_text()
            message = json.loads(msg_json)

            mime_type = message.get("mime_type")
            data = message.get("data")

            # Handle text messages
            if mime_type == "text/plain":
                content = Content(role="user", parts=[Part.from_text(text=data)])
                live_request_queue.send_content(content=content)
                print(f"[CLIENT TO AGENT]: {data}")

            # Handle audio messages
            elif mime_type == "audio/pcm":
                audio_bytes = base64.b64decode(data)
                blob = Blob(data=audio_bytes, mime_type=mime_type)
                live_request_queue.send_realtime(blob)
                print(f"[CLIENT TO AGENT]: Audio: {len(audio_bytes)} bytes")

            # Handle end of audio stream
            elif message.get("command") == "endOfAudio":
                # For ADK 1.2.1, we need to send a silent audio packet to trigger processing
                silent_audio = bytes([128] * 320)  # 20ms of silence at 16kHz
                live_request_queue.send_realtime(Blob(data=silent_audio, mime_type="audio/pcm"))
                print(f"[CLIENT TO AGENT]: End of audio signal received")
                
            else:
                print(f"[CLIENT ERROR] Unsupported message: {message}")

    except WebSocketDisconnect:
        print("[CLIENT] WebSocket disconnected")
    except Exception as e:
        print(f"[CLIENT ERROR] {e}")


#
# --- FastAPI App ---
#

app = FastAPI()

# STATIC_DIR = Path("static")
# app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# @app.get("/")
# async def root():
#     return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    await websocket.accept()
    is_audio = websocket.query_params.get("is_audio", "false").lower() == "true"
    print(f"Client #{user_id} connected, audio mode: {is_audio}")

    live_events, live_request_queue = await start_agent_session(str(user_id), is_audio=is_audio)

    # Inject initial prompt (e.g., a way to introduce the assistant)
    initial_prompt = "What are you?"
    content = Content(role="user", parts=[Part.from_text(text=initial_prompt)])
    live_request_queue.send_content(content=content)
    print(f"[SERVER] Sent initial prompt: {initial_prompt}")

    agent_task = asyncio.create_task(
        agent_to_client_messaging(websocket, live_events)
    )
    client_task = asyncio.create_task(
        client_to_agent_messaging(websocket, live_request_queue)
    )

    # Wait for both tasks to complete (or one fails)
    done, pending = await asyncio.wait(
        [agent_task, client_task],
        return_when=asyncio.FIRST_COMPLETED
    )

    # Cancel any remaining tasks
    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    live_request_queue.close()
    print(f"Client #{user_id} disconnected")
