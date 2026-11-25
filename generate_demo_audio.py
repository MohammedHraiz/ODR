"""Create three original chime/synth demo tracks with the system FFmpeg."""
import json
import math
import os
import shutil
import struct
import subprocess
import wave
from pathlib import Path

ROOT = Path(os.environ.get("MUSIC_DIR", "/app/music"))
PLAYLIST = Path(os.environ.get("PLAYLIST_FILE", "/app/playlist.json"))
RATE = 44100

TRACKS = [
    ("01 - Morning Courtyard.mp3", [523.25, 659.25, 783.99, 659.25, 587.33, 698.46, 880.00, 698.46], 0.30, 0.40),
    ("02 - Olive Branch.mp3", [392.00, 493.88, 587.33, 659.25, 587.33, 493.88, 440.00, 587.33], 0.36, 0.48),
    ("03 - Lanterns at Dusk.mp3", [440.00, 554.37, 659.25, 880.00, 783.99, 659.25, 554.37, 493.88], 0.28, 0.54),
]


def synthesize(path: Path, notes: list[float], note_seconds: float, tail: float) -> None:
    count = int(RATE * note_seconds * len(notes))
    with wave.open(str(path.with_suffix(".wav")), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        frames = bytearray()
        for n in range(count):
            t = n / RATE
            note_index = min(int(t / note_seconds), len(notes) - 1)
            local = t - note_index * note_seconds
            duration = note_seconds + tail
            envelope = min(1.0, local / 0.012) * math.exp(-3.2 * local / duration)
            phase = 2 * math.pi * notes[note_index] * local
            sample = (math.sin(phase) + 0.26 * math.sin(2.01 * phase) + 0.10 * math.sin(3.98 * phase)) * envelope * 0.34
            pan = 0.78 + 0.22 * math.sin(2 * math.pi * t / 9.0)
            left = int(max(-1, min(1, sample * pan)) * 32767)
            right = int(max(-1, min(1, sample * (1.0 - 0.22 * (pan - 0.78)))) * 32767)
            frames.extend(struct.pack("<hh", left, right))
        wav.writeframes(frames)
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(path.with_suffix(".wav")),
        "-codec:a", "libmp3lame", "-b:a", "128k", "-metadata", f"title={path.stem[5:]}", str(path),
    ], check=True)
    path.with_suffix(".wav").unlink()


def main() -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg must be installed to generate demo audio")
    ROOT.mkdir(parents=True, exist_ok=True)
    playlist = []
    for filename, notes, duration, tail in TRACKS:
        path = ROOT / filename
        synthesize(path, notes, duration, tail)
        playlist.append(filename)
    PLAYLIST.parent.mkdir(parents=True, exist_ok=True)
    PLAYLIST.write_text(json.dumps(playlist, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
