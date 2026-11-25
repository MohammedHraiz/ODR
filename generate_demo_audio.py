"""Generate three original, clearly distinct instrumental MP3 demo tracks."""
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

# Notes are MIDI pitches. Each melody contains eight eighth-note slots per bar;
# None is a rest. Four-bar progressions repeat twice, producing an audible phrase.
TRACKS = [
    {
        "filename": "01 - Morning Courtyard.mp3", "bpm": 96, "style": "arpeggio",
        "chords": [[48, 52, 55], [43, 47, 50], [45, 48, 52], [41, 45, 48]],  # C - G - Am - F
        "melody": [72, 76, 79, 76, 74, 79, 83, 79],
    },
    {
        "filename": "02 - Olive Branch.mp3", "bpm": 132, "style": "pulse",
        "chords": [[53, 57, 60], [46, 50, 53], [48, 52, 55], [53, 57, 60]],  # F - Bb - C - F
        "melody": [77, None, 81, 84, 82, 81, 79, 84],
    },
    {
        "filename": "03 - Lanterns at Dusk.mp3", "bpm": 68, "style": "calm",
        "chords": [[45, 48, 52], [41, 45, 48], [48, 52, 55], [43, 47, 50]],  # Am - F - C - G
        "melody": [69, None, 72, 76, None, 74, 72, None],
    },
]


def midi_hz(note: int) -> float:
    return 440.0 * (2.0 ** ((note - 69) / 12.0))


def synthesize(path: Path, track: dict) -> None:
    bpm = track["bpm"]
    beat = 60.0 / bpm
    step = beat / 2
    bar = beat * 4
    duration = bar * 8  # Repeat the four-bar progression twice.
    total_samples = int(RATE * duration)
    chords = track["chords"]
    melody = track["melody"]
    style = track["style"]
    frames = bytearray()

    for n in range(total_samples):
        t = n / RATE
        bar_index = int(t / bar)
        chord = chords[bar_index % len(chords)]
        beat_phase = (t % beat) / beat
        step_index = int((t % bar) / step) % 8
        step_phase = (t % step) / step
        melody_note = melody[step_index]

        if style == "pulse":
            # Bright offbeat chord hits and a firm bass pulse give this track a
            # faster, more rhythmic character than the other two.
            stab = math.exp(-9.0 * beat_phase)
            harmony = sum(math.sin(2 * math.pi * midi_hz(note + 12) * t) for note in chord) * 0.055 * stab
            bass = math.sin(2 * math.pi * midi_hz(chord[0] - 12) * t) * 0.12 * math.exp(-7.0 * beat_phase)
            lead_decay = math.exp(-3.5 * step_phase)
        elif style == "calm":
            # Slow, softly breathing chord bed and legato evening melody.
            swell = 0.78 + 0.22 * math.sin(2 * math.pi * (t % bar) / bar)
            harmony = sum(math.sin(2 * math.pi * midi_hz(note) * t) for note in chord) * 0.045 * swell
            bass = math.sin(2 * math.pi * midi_hz(chord[0] - 12) * t) * 0.075
            lead_decay = math.exp(-0.8 * step_phase)
        else:
            # Warm sustained triads under a plucked eighth-note arpeggio.
            harmony = sum(math.sin(2 * math.pi * midi_hz(note) * t) for note in chord) * 0.04
            bass = math.sin(2 * math.pi * midi_hz(chord[0] - 12) * t) * 0.09
            lead_decay = math.exp(-3.0 * step_phase)

        lead = 0.0
        if melody_note is not None:
            attack = min(1.0, step_phase * RATE * step / 0.012)
            lead = math.sin(2 * math.pi * midi_hz(melody_note) * t) * 0.19 * attack * lead_decay
            lead += math.sin(2 * math.pi * midi_hz(melody_note + 12) * t) * 0.035 * attack * lead_decay

        sample = max(-0.92, min(0.92, harmony + bass + lead))
        pan = 0.86 + 0.12 * math.sin(2 * math.pi * t / (9 if style == "calm" else 6))
        left = int(sample * pan * 32767)
        right = int(sample * (1.0 - (pan - 0.86) * 0.45) * 32767)
        frames.extend(struct.pack("<hh", left, right))

    wav_path = path.with_suffix(".wav")
    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(frames)
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav_path),
        "-codec:a", "libmp3lame", "-b:a", "128k", "-metadata", f"title={path.stem[5:]}", str(path),
    ], check=True)
    wav_path.unlink()


def main() -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg must be installed to generate demo audio")
    ROOT.mkdir(parents=True, exist_ok=True)
    playlist = []
    for track in TRACKS:
        filename = track["filename"]
        synthesize(ROOT / filename, track)
        playlist.append(filename)
    PLAYLIST.parent.mkdir(parents=True, exist_ok=True)
    PLAYLIST.write_text(json.dumps(playlist, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
