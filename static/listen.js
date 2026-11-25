(() => {
  const audio = document.getElementById('radioAudio');
  const play = document.getElementById('playButton');
  const playIcon = document.getElementById('playIcon');
  const volume = document.getElementById('volume');
  const playerLabel = document.getElementById('playerLabel');
  const statusLabel = document.getElementById('statusLabel');
  const title = document.getElementById('trackTitle');
  let reconnectTimer;
  let lastDataAt = 0;
  let connecting = false;
  let wantsPlayback = false;

  async function refresh() {
    try {
      const response = await fetch('/api/now-playing', { cache: 'no-store' });
      const data = await response.json();
      title.textContent = data.track_title || 'Waiting for the next track';
      statusLabel.textContent = data.is_live ? 'ON AIR · CENTRAL STUDIO' : 'RECONNECTING TO STATION';
      document.getElementById('livePulse').style.background = data.is_live ? '#55ad70' : '#dfa764';
    } catch (_) { statusLabel.textContent = 'RECONNECTING TO STATION'; }
  }

  async function connect() {
    if (connecting) return;
    wantsPlayback = true;
    connecting = true;
    clearTimeout(reconnectTimer);
    playerLabel.textContent = 'Connecting to the live broadcast…';
    statusLabel.textContent = 'CONNECTING TO THE STATION';
    audio.src = '/stream?session=' + Date.now();
    try {
      await audio.play();
      playerLabel.textContent = 'Listening to the live station';
      playIcon.textContent = 'Ⅱ';
      play.setAttribute('aria-label', 'Pause live radio');
      lastDataAt = Date.now();
    } catch (error) {
      playerLabel.textContent = 'Tap play when you are ready to listen';
      playIcon.textContent = '▶';
      play.setAttribute('aria-label', 'Play live radio');
      if (error.name === 'NotAllowedError') wantsPlayback = false;
      else reconnect();
    } finally { connecting = false; }
  }

  function reconnect() {
    if (!wantsPlayback || document.hidden) return;
    statusLabel.textContent = 'RECONNECTING TO STATION';
    playerLabel.textContent = 'The signal paused. Reconnecting…';
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(connect, 1800);
  }

  play.addEventListener('click', () => {
    if (!wantsPlayback || audio.paused) connect();
    else { wantsPlayback = false; audio.pause(); }
  });
  volume.addEventListener('input', () => { audio.volume = Number(volume.value); });
  audio.volume = Number(volume.value);
  audio.addEventListener('playing', () => { lastDataAt = Date.now(); playerLabel.textContent = 'Listening to the live station'; statusLabel.textContent = 'ON AIR · CENTRAL STUDIO'; });
  audio.addEventListener('pause', () => {
    if (wantsPlayback || audio.ended) reconnect();
    else { playerLabel.textContent = 'Broadcast paused'; playIcon.textContent = '▶'; play.setAttribute('aria-label', 'Play live radio'); }
  });
  audio.addEventListener('waiting', () => { playerLabel.textContent = 'Signal buffering…'; });
  audio.addEventListener('stalled', reconnect);
  audio.addEventListener('error', reconnect);
  audio.addEventListener('timeupdate', () => { lastDataAt = Date.now(); });
  setInterval(() => { if (!audio.paused && Date.now() - lastDataAt > 12000) reconnect(); }, 5000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden && !audio.paused && audio.readyState < 2) reconnect(); });
  refresh();
  setInterval(refresh, 10000);
})();
