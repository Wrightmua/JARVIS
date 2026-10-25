"""Web server: serves the HUD, streams the conversation over a WebSocket, and speaks via edge-tts."""
import asyncio
import uuid
from contextlib import asynccontextmanager

import edge_tts
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .brain import Brain
from .config import HOST, HUD_DIR, PORT, VOICE, VOICE_RATE
from .tools import pc

brain = Brain()


@asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(brain.warmup())  # load the model into RAM before the first question
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)


@app.get("/api/stats")
def stats():
    return pc.stats()


class Speech(BaseModel):
    text: str


@app.post("/api/tts")
async def tts(req: Speech):
    communicate = edge_tts.Communicate(req.text[:3000], VOICE, rate=VOICE_RATE)
    first = None
    stream = communicate.stream()
    async for chunk in stream:  # pull the first chunk now so failures (offline) become a 503
        if chunk["type"] == "audio":
            first = chunk["data"]
            break

    async def audio():
        if first:
            yield first
        async for chunk in stream:
            if chunk["type"] == "audio":
                yield chunk["data"]

    if first is None:
        return StreamingResponse(iter(()), status_code=503)
    return StreamingResponse(audio(), media_type="audio/mpeg")


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    pending: dict[str, asyncio.Future] = {}
    busy: asyncio.Task | None = None

    async def emit(event: dict):
        try:
            await ws.send_json(event)
        except Exception:
            pass

    async def confirm(message: str) -> bool:
        cid = uuid.uuid4().hex[:8]
        fut = asyncio.get_running_loop().create_future()
        pending[cid] = fut
        await emit({"type": "confirm", "id": cid, "message": message})
        await emit({"type": "state", "value": "awaiting"})
        try:
            return await asyncio.wait_for(fut, 120)
        except asyncio.TimeoutError:
            return False
        finally:
            pending.pop(cid, None)
            await emit({"type": "confirm_closed", "id": cid})

    async def run(text: str):
        try:
            await brain.respond(text, emit, confirm)
        except asyncio.CancelledError:
            await emit({"type": "done", "text": "", "speech": ""})
        except Exception as e:
            await emit({"type": "error", "text": f"{type(e).__name__}: {e}"})
        finally:
            await emit({"type": "state", "value": "idle"})

    await emit(await brain.status())
    try:
        while True:
            msg = await ws.receive_json()
            kind = msg.get("type")
            if kind == "user" and msg.get("text", "").strip():
                if busy and not busy.done():
                    await emit({"type": "error", "text": "Still working on the last request."})
                    continue
                busy = asyncio.create_task(run(msg["text"].strip()))
            elif kind == "confirm" and (fut := pending.get(msg.get("id"))) and not fut.done():
                fut.set_result(bool(msg.get("ok")))
            elif kind == "stop" and busy:
                busy.cancel()
            elif kind == "reset":
                brain.reset()
            elif kind == "status":
                await emit(await brain.status())
    except WebSocketDisconnect:
        if busy:
            busy.cancel()


app.mount("/", StaticFiles(directory=HUD_DIR, html=True), name="hud")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
