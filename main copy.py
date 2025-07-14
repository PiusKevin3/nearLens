import os
import json
import asyncio
import base64
import warnings
from dotenv import load_dotenv

from google.genai.types import Part, Content, Blob
from google.adk.runners import InMemoryRunner
from google.adk.agents import LiveRequestQueue
from google.adk.agents.run_config import RunConfig
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from aavraa_assistant.agent import root_agent

warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")
load_dotenv()

APP_NAME = "Aavraa"

# --- Agent Session Setup ---

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

# --- Agent to Client Messaging ---

async def agent_to_client_messaging(websocket: WebSocket, live_events):
    try:
        async for event in live_events:
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

# --- Client to Agent Messaging ---

async def client_to_agent_messaging(websocket: WebSocket, live_request_queue: LiveRequestQueue, state: dict, user_id: int):
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

            if mime_type == "text/plain":
                content = Content(role="user", parts=[Part.from_text(text=data)])
                live_request_queue.send_content(content=content)
                print(f"[CLIENT TO AGENT]: {data}")

            elif mime_type == "audio/pcm":
                if websocket.client_state.name != "CONNECTED":
                    print(f"[CLIENT ERROR] Skipping audio: client disconnected.")
                    break
                audio_bytes = base64.b64decode(data)
                blob = Blob(data=audio_bytes, mime_type=mime_type)
                live_request_queue.send_realtime(blob)
                print(f"[CLIENT TO AGENT]: Audio: {len(audio_bytes)} bytes")

            elif message.get("command") == "endOfAudio":
                silent_audio = bytes([128] * 320)
                live_request_queue.send_realtime(Blob(data=silent_audio, mime_type="audio/pcm"))
                print(f"[CLIENT TO AGENT]: End of audio signal received")

            else:
                print(f"[CLIENT ERROR] Unsupported message: {message}")

    except WebSocketDisconnect:
        print("[CLIENT] WebSocket disconnected")
    except Exception as e:
        print(f"[CLIENT ERROR] {e}")

# --- FastAPI App Setup ---

app = FastAPI()

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    await websocket.accept()
    is_audio = websocket.query_params.get("is_audio", "false").lower() == "true"
    print(f"Client #{user_id} connected, audio mode: {is_audio}")

    live_events, live_request_queue = await start_agent_session(str(user_id), is_audio=is_audio)

    initial_prompt = "What are you?"
    content = Content(role="user", parts=[Part.from_text(text=initial_prompt)])
    live_request_queue.send_content(content=content)
    print(f"[SERVER] Sent initial prompt: {initial_prompt}")

    state = {
        "last_pong": asyncio.get_event_loop().time(),
        "missed_pongs": 0,
        "max_missed_pongs": 4,
    }

    async def keepalive_ping():
        try:
            while True:
                await websocket.send_text("__ping__")
                print(f"[KEEPALIVE] Sent ping to client #{user_id}")
                await asyncio.sleep(10)

                now = asyncio.get_event_loop().time()
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
            print(f"[KEEPALIVE ERROR] {e}")

    agent_task = asyncio.create_task(agent_to_client_messaging(websocket, live_events))
    client_task = asyncio.create_task(client_to_agent_messaging(websocket, live_request_queue, state, user_id))
    ping_task = asyncio.create_task(keepalive_ping())

    done, pending = await asyncio.wait(
        [agent_task, client_task, ping_task],
        return_when=asyncio.FIRST_COMPLETED
    )

    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    live_request_queue.close()
    print(f"[SERVER] Client #{user_id} disconnected")
