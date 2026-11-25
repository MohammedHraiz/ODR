"""Keep one Icecast source and MP3 encoder alive while switching decoded tracks."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

log = logging.getLogger("radio.feeder")
MUSIC_DIR = Path(os.environ.get("MUSIC_DIR", "/app/music"))
PLAYLIST_FILE = Path(os.environ.get("PLAYLIST_FILE", "/app/playlist.json"))
SAMPLE_RATE = 44100
CHUNK = 16_384


class RadioFeeder:
    def __init__(self) -> None:
        self.skip_event = asyncio.Event()
        self.playlist_lock = asyncio.Lock()
        self.state_lock = asyncio.Lock()
        self.playlist: list[str] = []
        self.current_track: str | None = None
        self.stream_status = "starting"
        self.encoder: asyncio.subprocess.Process | None = None

    async def load_playlist(self) -> list[str]:
        async with self.playlist_lock:
            try:
                raw = json.loads(PLAYLIST_FILE.read_text(encoding="utf-8"))
                if not isinstance(raw, list):
                    raise ValueError("playlist.json must contain a JSON array")
                names = [name for name in raw if isinstance(name, str) and (MUSIC_DIR / name).is_file()]
                self.playlist = names
            except (OSError, json.JSONDecodeError, ValueError):
                log.exception("Could not read playlist")
                self.playlist = []
            return list(self.playlist)

    async def save_playlist(self, tracks: list[str]) -> None:
        async with self.playlist_lock:
            temp = PLAYLIST_FILE.with_suffix(".json.tmp")
            temp.write_text(json.dumps(tracks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temp.replace(PLAYLIST_FILE)
            self.playlist = list(tracks)

    async def snapshot(self) -> dict:
        async with self.state_lock:
            tracks = await self.load_playlist()
            return {
                "current_track": self.current_track,
                "playlist": tracks,
                "stream_status": self.stream_status,
                "stream_url": "/stream",
            }

    async def skip(self) -> None:
        self.skip_event.set()

    async def _set_state(self, *, track: str | None = None, status: str | None = None) -> None:
        async with self.state_lock:
            if track is not None or status == "idle":
                self.current_track = track
            if status is not None:
                self.stream_status = status

    async def _start_encoder(self) -> asyncio.subprocess.Process:
        return await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "warning",
            "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "2", "-i", "pipe:0",
            "-vn", "-codec:a", "libmp3lame", "-b:a", "128k", "-content_type", "audio/mpeg",
            "-ice_name", "Ghammas Baladi Radio - CDR Group",
            "-f", "mp3", "icecast://source:hackme@127.0.0.1:8000/stream",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

    async def _play_track(self, filename: str) -> None:
        path = MUSIC_DIR / filename
        decoder = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
            "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "2", "pipe:1",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        assert decoder.stdout is not None and self.encoder and self.encoder.stdin
        await self._set_state(track=filename, status="live")
        while True:
            read_task = asyncio.create_task(decoder.stdout.read(CHUNK))
            skip_task = asyncio.create_task(self.skip_event.wait())
            done, pending = await asyncio.wait((read_task, skip_task), return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            if skip_task in done and self.skip_event.is_set():
                decoder.terminate()
                await decoder.wait()
                return
            pcm = read_task.result()
            if not pcm:
                await decoder.wait()
                if decoder.returncode:
                    log.warning("Decoder failed for %s", filename)
                return
            try:
                self.encoder.stdin.write(pcm)
                await self.encoder.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                raise RuntimeError("The Icecast encoder stopped accepting audio")

    async def run(self) -> None:
        while True:
            try:
                self.encoder = await self._start_encoder()
                await self._set_state(status="live")
                index = 0
                while True:
                    tracks = await self.load_playlist()
                    if not tracks:
                        await self._set_state(track=None, status="idle")
                        # Feed silence to preserve the public mount/source if an operator clears the queue.
                        assert self.encoder.stdin
                        silence = int(SAMPLE_RATE * 4 * 0.18)
                        self.encoder.stdin.write(bytes(silence))
                        await self.encoder.stdin.drain()
                        await asyncio.sleep(0.18)
                        continue
                    index %= len(tracks)
                    filename = tracks[index]
                    self.skip_event.clear()
                    try:
                        await self._play_track(filename)
                    except FileNotFoundError:
                        log.exception("Track disappeared during playback: %s", filename)
                    if self.skip_event.is_set():
                        self.skip_event.clear()
                        current = await self.load_playlist()
                        if filename in current:
                            index = (current.index(filename) + 1) % max(1, len(current))
                        else:
                            index = min(index, max(0, len(current) - 1))
                    else:
                        current = await self.load_playlist()
                        index = (current.index(filename) + 1) % len(current) if filename in current else index
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Feeder failed; reconnecting the encoder")
                await self._set_state(status="reconnecting")
                if self.encoder and self.encoder.returncode is None:
                    self.encoder.kill()
                    await self.encoder.wait()
                await asyncio.sleep(2)

    async def stop(self) -> None:
        if self.encoder and self.encoder.returncode is None:
            if self.encoder.stdin:
                self.encoder.stdin.close()
            self.encoder.terminate()
            await self.encoder.wait()
