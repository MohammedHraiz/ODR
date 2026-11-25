from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from feeder import MUSIC_DIR, RadioFeeder

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("radio")
ROOT = Path(__file__).parent
MAX_UPLOAD = 150 * 1024 * 1024
SAFE_NAME = re.compile(r"[^\w .()\[\]-]+", flags=re.UNICODE)
security = HTTPBasic(auto_error=False)
radio = RadioFeeder()
http_client: httpx.AsyncClient | None = None
feeder_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global http_client, feeder_task
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    await radio.load_playlist()
    http_client = httpx.AsyncClient(timeout=httpx.Timeout(None, connect=5.0))
    feeder_task = asyncio.create_task(radio.run(), name="radio-feeder")
    yield
    if feeder_task:
        feeder_task.cancel()
        try:
            await feeder_task
        except asyncio.CancelledError:
            pass
    await radio.stop()
    if http_client:
        await http_client.aclose()


app = FastAPI(title="Ghammas Baladi Radio", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


async def admin_auth(credentials: Annotated[HTTPBasicCredentials | None, Depends(security)]) -> str:
    username = os.environ.get("ADMIN_USER", "admin")
    password = os.environ.get("ADMIN_PASSWORD", "cdr2026")
    valid_user = credentials and secrets.compare_digest(credentials.username.encode(), username.encode())
    valid_password = credentials and secrets.compare_digest(credentials.password.encode(), password.encode())
    if not (valid_user and valid_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin credentials required",
            headers={"WWW-Authenticate": 'Basic realm="Ghammas Baladi Radio Admin"'},
        )
    return credentials.username


class ReorderRequest(BaseModel):
    tracks: list[str]


class PlayRequest(BaseModel):
    filename: str


@app.get("/", include_in_schema=False)
async def home():
    return RedirectResponse("/listen", status_code=307)


@app.get("/listen", include_in_schema=False)
async def listen_page():
    return FileResponse(ROOT / "templates" / "listen.html")


@app.get("/admin", include_in_schema=False)
async def admin_page():
    return FileResponse(ROOT / "templates" / "admin.html")


def shape_now_playing(snapshot: dict) -> dict:
    return {
        **snapshot,
        "track_title": re.sub(r"^\d{2} - ", "", Path(snapshot["current_track"]).stem) if snapshot["current_track"] else "Waiting for the next track",
        "is_live": snapshot["stream_status"] == "live",
    }


@app.get("/api/now-playing")
async def now_playing():
    return shape_now_playing(await radio.snapshot())


@app.get("/api/admin/session")
async def admin_session(username: Annotated[str, Depends(admin_auth)]):
    return {"username": username, "authenticated": True}


@app.get("/stream")
async def stream_proxy():
    if http_client is None:
        raise HTTPException(503, "Radio is starting")
    request = http_client.build_request("GET", "http://127.0.0.1:8000/stream", headers={"Accept": "audio/mpeg"})
    try:
        upstream = await http_client.send(request, stream=True)
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Radio stream is reconnecting") from exc
    if upstream.status_code != 200:
        await upstream.aclose()
        raise HTTPException(503, "Radio stream is not available yet")

    async def chunks():
        try:
            async for chunk in upstream.aiter_raw(chunk_size=16_384):
                if chunk:
                    yield chunk
        finally:
            await upstream.aclose()

    return StreamingResponse(
        chunks(), media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "X-Accel-Buffering": "no",
            "Content-Disposition": 'inline; filename="ghammas-baladi-radio.mp3"',
        },
    )


def clean_filename(raw: str) -> str:
    base = Path(raw.replace("\\", "/")).name.strip()
    base = SAFE_NAME.sub("_", base).strip(" .")
    if not base or not base.lower().endswith(".mp3") or base in {".", ".."}:
        raise HTTPException(400, "Upload a file with the .mp3 extension")
    return base


@app.post("/api/tracks/upload")
async def upload_tracks(
    _: Annotated[str, Depends(admin_auth)],
    files: Annotated[list[UploadFile], File(description="One or more MP3 files")],
):
    tracks = await radio.load_playlist()
    uploaded = []
    for file in files:
        filename = clean_filename(file.filename or "")
        target = MUSIC_DIR / filename
        if target.exists():
            stem, suffix = target.stem, target.suffix
            n = 2
            while (MUSIC_DIR / f"{stem} ({n}){suffix}").exists():
                n += 1
            filename = f"{stem} ({n}){suffix}"
            target = MUSIC_DIR / filename
        temp = target.with_name(target.name + ".uploading")
        total = 0
        try:
            with temp.open("wb") as output:
                while chunk := await file.read(64 * 1024):
                    total += len(chunk)
                    if total > MAX_UPLOAD:
                        raise HTTPException(413, "Each MP3 must be 150 MB or smaller")
                    output.write(chunk)
            if total == 0:
                raise HTTPException(400, "The uploaded file is empty")
            temp.replace(target)
            tracks.append(filename)
            uploaded.append(filename)
        except Exception:
            temp.unlink(missing_ok=True)
            raise
        finally:
            await file.close()
    await radio.save_playlist(tracks)
    return {"uploaded": uploaded, "playlist": tracks}


@app.post("/api/tracks/reorder")
async def reorder_tracks(payload: ReorderRequest, _: Annotated[str, Depends(admin_auth)]):
    current = await radio.load_playlist()
    if len(payload.tracks) != len(current) or set(payload.tracks) != set(current) or len(set(payload.tracks)) != len(payload.tracks):
        raise HTTPException(400, "Reorder must include every current track exactly once")
    await radio.save_playlist(payload.tracks)
    return {"playlist": payload.tracks}


@app.delete("/api/tracks/{filename}")
async def delete_track(filename: str, _: Annotated[str, Depends(admin_auth)]):
    filename = Path(filename).name
    tracks = await radio.load_playlist()
    if filename not in tracks:
        raise HTTPException(404, "Track not found")
    await radio.save_playlist([track for track in tracks if track != filename])
    (MUSIC_DIR / filename).unlink(missing_ok=True)
    return {"deleted": filename, "playlist": await radio.load_playlist()}


@app.post("/api/tracks/skip")
async def skip_track(_: Annotated[str, Depends(admin_auth)]):
    result = await radio.skip()
    if not result["advanced"]:
        raise HTTPException(409, "No track is currently playing")
    return {**shape_now_playing(await radio.snapshot()), **result, "message": "Advancing to the next track"}


@app.post("/api/tracks/play")
async def play_track(payload: PlayRequest, _: Annotated[str, Depends(admin_auth)]):
    result = await radio.play(payload.filename)
    if result is None:
        raise HTTPException(404, "Track not found in the playlist")
    return shape_now_playing(await radio.snapshot())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), proxy_headers=True, forwarded_allow_ips="*")
