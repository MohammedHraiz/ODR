#!/bin/bash
set -eu

mkdir -p /var/log/icecast2 /run/icecast2 /var/lib/icecast2 /app/music
chown -R icecast2:icecast /var/log/icecast2 /run/icecast2 /var/lib/icecast2
chmod 755 /var/log/icecast2 /run/icecast2 /var/lib/icecast2

MUSIC_DIR="${MUSIC_DIR:-/app/music}"
PLAYLIST_FILE="${PLAYLIST_FILE:-/app/playlist.json}"
mkdir -p "$MUSIC_DIR" "$(dirname "$PLAYLIST_FILE")"
if [ "$MUSIC_DIR" != /app/music ]; then cp -n /app/music/*.mp3 "$MUSIC_DIR"/ 2>/dev/null || true; fi
if [ "$PLAYLIST_FILE" != /app/playlist.json ] && [ ! -f "$PLAYLIST_FILE" ]; then cp /app/playlist.json "$PLAYLIST_FILE"; fi

/usr/bin/icecast2 -c /app/icecast.xml &
ICECAST_PID=$!
APP_PID=""
cleanup() {
  if [ -n "$APP_PID" ]; then kill "$APP_PID" 2>/dev/null || true; fi
  kill "$ICECAST_PID" 2>/dev/null || true
  wait "$ICECAST_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Wait for Icecast's loopback listener before starting the feeder/API.
i=0
until python -c 'import socket; s=socket.create_connection(("127.0.0.1",8000),1); s.close()' 2>/dev/null; do
  i=$((i + 1))
  if [ "$i" -ge 30 ]; then echo 'Icecast did not become ready' >&2; exit 1; fi
  sleep 1
done

python /app/app.py &
APP_PID=$!
wait -n "$ICECAST_PID" "$APP_PID"
