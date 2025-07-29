import os
import json
import asyncio
import warnings
import time
import base64
from copy import deepcopy
from typing import List, Dict, Any, Optional  # Added missing imports

from dotenv import load_dotenv

from google.genai.types import Part, Content, Blob
from google.adk.runners import InMemoryRunner
from google.adk.agents import LiveRequestQueue
from google.adk.tools.agent_tool import AgentTool
from google.adk.agents.run_config import RunConfig, StreamingMode
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from google.genai import types

# Import the function and agent from your module
from aavraa_assistant.agent import aavraa_orchestrator, find_shopping_items

warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")
load_dotenv()

APP_NAME = "Aavraa"

# --- Agent Session Setup ---

async def start_agent_session(user_id: str, is_audio: bool = False, agent=None):
    """
    Initializes an agent session with the specified modality.
    """
    # Use the provided agent or default to the global one
    agent = agent or aavraa_orchestrator
    
    runner = InMemoryRunner(
        app_name=APP_NAME,
        agent=agent,
    )
    session = await runner.session_service.create_session(
        app_name=APP_NAME,
        user_id=user_id,
    )
    # Initialize session storage for shopping results
    session.shopping_results = []

    modality = "AUDIO" if is_audio else "TEXT"
    run_config = RunConfig(
        response_modalities=[modality],
        output_audio_transcription=types.AudioTranscriptionConfig(), 
        input_audio_transcription=types.AudioTranscriptionConfig(), 
        realtime_input_config=types.RealtimeInputConfig(), 
        streaming_mode=StreamingMode.BIDI, 
        save_input_blobs_as_artifacts=True,
    )
    live_request_queue = LiveRequestQueue()
    live_events = runner.run_live(
        session=session,
        live_request_queue=live_request_queue,
        run_config=run_config,
    )
    return live_events, live_request_queue, session  

# --- Agent to Client Messaging ---

async def agent_to_client_messaging(websocket: WebSocket, live_events, is_audio: bool, session):
    """
    Handles messages coming from the agent and sends them to the client.
    Also sends shopping results after processing events.
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

            # If it's audio data, send it
            if part.inline_data and part.inline_data.mime_type.startswith("audio/pcm"):
                audio_data = part.inline_data.data
                if audio_data:
                    await websocket.send_text(json.dumps({
                        "mime_type": "audio/pcm",
                        "data": base64.b64encode(audio_data).decode("ascii"),
                    }))
                    print(f"[AGENT TO CLIENT]: audio/pcm: {len(audio_data)} bytes.")

            # If it's text data, send it ONLY IF IT'S A PARTIAL EVENT
            elif part.text:
                if event.partial:  # Critical: Only send partial text updates
                    await websocket.send_text(json.dumps({
                        "mime_type": "text/plain",
                        "data": part.text,
                    }))
                    print(f"[AGENT TO CLIENT]: text/plain: {part.text}")

        # After processing events, send shopping results if any
        if hasattr(session, 'shopping_results') and session.shopping_results:
            await websocket.send_text(json.dumps({
                "type": "shopping_results",
                "data": session.shopping_results
            }))
            print(f"[AGENT TO CLIENT] Sent {len(session.shopping_results)} shopping items")

    except Exception as e:
        print(f"[AGENT ERROR] Error in agent_to_client_messaging: {e}")

# --- Client to Agent Messaging ---

async def client_to_agent_messaging(websocket: WebSocket, live_request_queue: LiveRequestQueue, state: dict, user_id: int):
    """
    Handles messages coming from the client and sends them to the agent.
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

            else:
                print(f"[CLIENT ERROR] Unsupported message: {message}")

    except WebSocketDisconnect:
        print("[CLIENT] WebSocket disconnected gracefully.")
    except Exception as e:
        print(f"[CLIENT ERROR] Error in client_to_agent_messaging: {e}")

# --- FastAPI App Setup ---

app = FastAPI()

# --- CORS Middleware ---
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
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

# Create session-specific shopping tool wrapper
def create_shopping_tool_wrapper(session):
    """Factory for creating session-aware shopping tools"""
    def wrapped_find_shopping_items(queries: List[str]) -> Dict[str, Any]:
        result = find_shopping_items(queries)
        if result.get("status") == "success" and result.get("items"):
            # Store items in session
            if not hasattr(session, 'shopping_results'):
                session.shopping_results = []
            session.shopping_results.extend(result["items"])
        return result
    return wrapped_find_shopping_items

# Create a session-specific agent
def create_session_agent(session):
    """Create a session-specific agent with a custom shopping tool"""
    # Create a deep copy of the original agent
    session_agent = deepcopy(aavraa_orchestrator)
    
    # Create session-specific shopping tool
    shopping_tool = create_shopping_tool_wrapper(session)
    
    # Replace the shopping tool in the agent's tools
    session_agent.tools = [
        AgentTool(agent=tool.agent) if hasattr(tool, 'agent') else shopping_tool
        for tool in session_agent.tools
    ]
    
    return session_agent

# Dedicated Audio-Only WebSocket Endpoint
@app.websocket("/ws/audio/{user_id}")
async def audio_websocket_endpoint(websocket: WebSocket, user_id: int):
    await websocket.accept()
    print(f"Audio-only client #{user_id} connected")

    # Create session-specific agent
    session_agent = create_session_agent(None)  # We'll attach session later
    
    # Start agent session
    live_events, live_request_queue, session = await start_agent_session(
        str(user_id), 
        is_audio=True,
        agent=session_agent
    )
    
    # Now that we have session, attach it to the agent
    session_agent = create_session_agent(session)

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

    # Send initial prompt
    initial_prompt = "What are you?"
    content = Content(role="user", parts=[Part.from_text(text=initial_prompt)])
    live_request_queue.send_content(content=content)
    print(f"[SERVER] Sent initial prompt: '{initial_prompt}' to audio client.")

    # Create and run concurrent tasks
    agent_task = asyncio.create_task(agent_to_client_messaging(websocket, live_events, True, session))
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
    await websocket.accept()
    print(f"Text-only client #{user_id} connected")

    # Create session-specific agent
    session_agent = create_session_agent(None)  # We'll attach session later
    
    # Start agent session
    live_events, live_request_queue, session = await start_agent_session(
        str(user_id), 
        is_audio=False,
        agent=session_agent
    )
    
    # Now that we have session, attach it to the agent
    session_agent = create_session_agent(session)

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

    # Send initial prompt
    initial_prompt = "What are you?"
    content = Content(role="user", parts=[Part.from_text(text=initial_prompt)])
    live_request_queue.send_content(content=content)
    print(f"[SERVER] Sent initial prompt: '{initial_prompt}' to text client.")

    # Create and run concurrent tasks
    agent_task = asyncio.create_task(agent_to_client_messaging(websocket, live_events, False, session))
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