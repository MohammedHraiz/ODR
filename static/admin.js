(() => {
  let credentials = null;
  let tracks = [];
  const playlistEl = document.getElementById('playlist');
  const toastEl = document.getElementById('toast');
  let toastTimer;

  function toast(message) {
    toastEl.textContent = message;
    toastEl.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove('show'), 2600);
  }

  async function request(url, options = {}, auth = true, promptOn401 = true) {
    const headers = new Headers(options.headers || {});
    if (auth && credentials) headers.set('Authorization', 'Basic ' + btoa(unescape(encodeURIComponent(credentials.user + ':' + credentials.pass))));
    let response = await fetch(url, { ...options, headers, cache: 'no-store' });
    if (auth && promptOn401 && response.status === 401) {
      credentials = null;
      await signIn();
      if (!credentials) throw new Error('Sign-in cancelled');
      headers.set('Authorization', 'Basic ' + btoa(unescape(encodeURIComponent(credentials.user + ':' + credentials.pass))));
      response = await fetch(url, { ...options, headers, cache: 'no-store' });
    }
    if (!response.ok) {
      let message = `Request failed (${response.status})`;
      try { message = (await response.json()).detail || message; } catch (_) {}
      if (response.status === 401) credentials = null;
      throw new Error(message);
    }
    return response;
  }

  async function signIn() {
    const user = window.prompt('Radio admin username', 'admin');
    if (user === null) return;
    const pass = window.prompt('Radio admin password');
    if (pass === null) return;
    credentials = { user, pass };
    try { await request('/api/admin/session', {}, true, false); await loadPlaylist(); document.getElementById('loginButton').textContent = 'Signed in'; toast('Admin access ready'); }
    catch (error) { credentials = null; toast(error.message === 'Admin credentials required' ? 'Those credentials were not accepted' : error.message); }
  }

  function renderPlaylist() {
    document.getElementById('trackCount').textContent = `${tracks.length} ${tracks.length === 1 ? 'track' : 'tracks'}`;
    if (!tracks.length) { playlistEl.innerHTML = '<div class="empty-state">No tracks in rotation. Add an MP3 to get the broadcast moving.</div>'; return; }
    playlistEl.innerHTML = tracks.map((name, index) => `<div class="track-row" data-index="${index}"><span class="track-number">${String(index + 1).padStart(2, '0')}</span><div class="track-info"><strong title="${escapeHtml(name)}">${escapeHtml(name.replace(/\.mp3$/i, ''))}</strong><small>${index === 0 ? 'Up next in rotation' : 'In the shared rotation'}</small></div><div class="track-actions"><button class="icon-button" data-action="up" aria-label="Move ${escapeHtml(name)} up" ${index === 0 ? 'disabled' : ''}>↑</button><button class="icon-button" data-action="down" aria-label="Move ${escapeHtml(name)} down" ${index === tracks.length - 1 ? 'disabled' : ''}>↓</button><button class="icon-button delete" data-action="delete" aria-label="Delete ${escapeHtml(name)}">×</button></div></div>`).join('');
  }

  function escapeHtml(value) { return String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }

  async function loadPlaylist() {
    const data = await (await request('/api/now-playing')).json();
    tracks = data.playlist || [];
    renderPlaylist();
    document.getElementById('liveTrack').textContent = data.track_title || 'Waiting for the next track';
    document.getElementById('streamStatus').textContent = data.stream_status === 'live' ? 'Broadcasting live' : 'Reconnecting';
    document.getElementById('statusDot').classList.toggle('online', data.stream_status === 'live');
    document.getElementById('statusLabel').textContent = data.stream_status === 'live' ? 'CENTRAL STUDIO · ON AIR' : 'CENTRAL STUDIO · RECONNECTING';
  }

  async function saveOrder() {
    await request('/api/tracks/reorder', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tracks }) });
    renderPlaylist();
    toast('Playlist order updated');
  }

  playlistEl.addEventListener('click', async event => {
    const button = event.target.closest('button[data-action]');
    if (!button) return;
    const row = button.closest('.track-row');
    const index = Number(row.dataset.index);
    try {
      if (button.dataset.action === 'up' && index > 0) { [tracks[index - 1], tracks[index]] = [tracks[index], tracks[index - 1]]; await saveOrder(); }
      if (button.dataset.action === 'down' && index < tracks.length - 1) { [tracks[index + 1], tracks[index]] = [tracks[index], tracks[index + 1]]; await saveOrder(); }
      if (button.dataset.action === 'delete') { await request('/api/tracks/' + encodeURIComponent(tracks[index]), { method: 'DELETE' }); await loadPlaylist(); toast('Track removed from rotation'); }
    } catch (error) { toast(error.message); loadPlaylist().catch(() => {}); }
  });

  document.getElementById('loginButton').addEventListener('click', signIn);
  document.getElementById('uploadForm').addEventListener('submit', async event => {
    event.preventDefault();
    const input = document.getElementById('files');
    if (!input.files.length) { toast('Choose at least one MP3 file'); return; }
    const form = new FormData();
    for (const file of input.files) form.append('files', file);
    try { const result = await (await request('/api/tracks/upload', { method: 'POST', body: form })).json(); input.value = ''; await loadPlaylist(); toast(`${result.uploaded.length} track${result.uploaded.length === 1 ? '' : 's'} added`); }
    catch (error) { toast(error.message); }
  });
  document.getElementById('skipButton').addEventListener('click', async () => {
    try { await request('/api/tracks/skip', { method: 'POST' }); toast('Skipping to the next track'); setTimeout(() => loadPlaylist().catch(() => {}), 500); }
    catch (error) { toast(error.message); }
  });
  loadPlaylist().catch(() => { document.getElementById('streamStatus').textContent = 'Sign in to manage the station'; document.getElementById('statusLabel').textContent = 'ADMIN ACCESS REQUIRED'; });
  setInterval(() => loadPlaylist().catch(() => {}), 12000);
})();
