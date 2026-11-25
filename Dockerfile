FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    MUSIC_DIR=/app/music \
    PLAYLIST_FILE=/app/playlist.json

RUN apt-get update && apt-get install -y --no-install-recommends \
      icecast2 ffmpeg ca-certificates tini \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /app/music /var/log/icecast2 /run/icecast2 /var/lib/icecast2 \
    && chown -R icecast2:icecast /var/log/icecast2 /run/icecast2 /var/lib/icecast2

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py feeder.py generate_demo_audio.py start.sh icecast.xml ./
COPY demo_music ./demo_music
COPY static ./static
COPY templates ./templates
RUN chmod +x /app/start.sh \
    && python /app/generate_demo_audio.py

EXPOSE 8080
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["./start.sh"]
