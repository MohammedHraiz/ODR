(() => {
  let credentials = null;
  let tracks = [];
  let reorderInFlight = false;
  let refreshAfterReorder = false;
  let draggedTrack = null;
  let currentFilename = null;
  let currentStartedAt = null;
  let currentDuration = null;
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

  async function uploadWithProgress(form, button) {
    if (!credentials) await signIn();
    if (!credentials) throw new Error('Admin sign-in is required to upload tracks');
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/tracks/upload');
      xhr.setRequestHeader('Authorization', 'Basic ' + btoa(unescape(encodeURIComponent(credentials.user + ':' + credentials.pass))));
      xhr.upload.onprogress = event => {
        const percent = event.lengthComputable ? Math.round(event.loaded * 100 / event.total) : null;
        button.textContent = percent === null ? 'Uploading...' : `Uploading... ${percent}%`;
      };
      xhr.onload = async () => {
        if (xhr.status === 401) {
          credentials = null;
          await signIn();
          if (credentials) uploadWithProgress(form, button).then(resolve, reject);
          else reject(new Error('Admin sign-in is required to upload tracks'));
          return;
        }
        if (xhr.status < 200 || xhr.status >= 300) {
          try { reject(new Error(JSON.parse(xhr.responseText).detail || `Upload failed (${xhr.status})`)); }
          catch (_) { reject(new Error(`Upload failed (${xhr.status})`)); }
          return;
        }
        try { resolve(JSON.parse(xhr.responseText)); }
        catch (_) { reject(new Error('The server returned an invalid upload response')); }
      };
      xhr.onerror = () => reject(new Error('Upload network error'));
      xhr.onabort = () => reject(new Error('Upload was cancelled'));
      xhr.send(form);
    });
  }

  function renderPlaylist() {
    document.getElementById('trackCount').textContent = `${tracks.length} ${tracks.length === 1 ? 'track' : 'tracks'}`;
    if (!tracks.length) { playlistEl.innerHTML = '<div class="empty-state">No tracks in rotation. Add an MP3 to get the broadcast moving.</div>'; return; }
    playlistEl.innerHTML = tracks.map((name, index) => `<div class="track-row" draggable="${!reorderInFlight}" data-index="${index}"><span class="track-leading"><span class="drag-handle" aria-hidden="true">⋮⋮</span><span class="track-number">${String(index + 1).padStart(2, '0')}</span></span><div class="track-info"><button class="track-play" data-action="play" data-filename="${escapeHtml(name)}" aria-label="Play ${escapeHtml(name)} from the beginning" ${reorderInFlight ? 'disabled' : ''}><strong title="${escapeHtml(name)}">${escapeHtml(name.replace(/\.mp3$/i, ''))}</strong><span class="play-song" aria-hidden="true">▶</span></button><small>${name === currentFilename ? 'Playing now' : 'Select to play now'}</small></div><div class="track-actions"><button class="icon-button" data-action="up" aria-label="Move ${escapeHtml(name)} up" ${index === 0 || reorderInFlight ? 'disabled' : ''}>↑</button><button class="icon-button" data-action="down" aria-label="Move ${escapeHtml(name)} down" ${index === tracks.length - 1 || reorderInFlight ? 'disabled' : ''}>↓</button><button class="icon-button delete" data-action="delete" aria-label="Delete ${escapeHtml(name)}" ${reorderInFlight ? 'disabled' : ''}>×</button></div></div>`).join('');
  }

  function escapeHtml(value) { return String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }

  async function loadPlaylist() {
    if (reorderInFlight) { refreshAfterReorder = true; return; }
    const data = await (await request('/api/now-playing')).json();
    if (reorderInFlight) { refreshAfterReorder = true; return; }
    tracks = data.playlist || [];
    applyNowPlaying(data);
    document.getElementById('streamStatus').textContent = data.stream_status === 'live' ? 'Broadcasting live' : 'Reconnecting';
    document.getElementById('statusDot').classList.toggle('online', data.stream_status === 'live');
    document.getElementById('statusLabel').textContent = data.stream_status === 'live' ? 'CENTRAL STUDIO · ON AIR' : 'CENTRAL STUDIO · RECONNECTING';
  }

  function formatElapsed(seconds) { return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`; }

  function applyNowPlaying(data) {
    const filename = data.current_filename || data.current_track || null;
    const startedAt = data.started_at || null;
    const changed = filename !== currentFilename || startedAt !== currentStartedAt;
    currentFilename = filename;
    currentStartedAt = startedAt;
    currentDuration = data.duration || null;
    document.getElementById('liveTrack').textContent = data.track_title || 'Waiting for the next track';
    if (changed) document.getElementById('liveElapsed').textContent = '0:00';
    renderPlaylist();
  }

  function updateElapsed() {
    const seconds = currentStartedAt ? Math.max(0, Math.floor(Date.now() / 1000 - currentStartedAt)) : 0;
    document.getElementById('liveElapsed').textContent = formatElapsed(seconds) + (currentDuration ? ` / ${formatElapsed(Math.floor(currentDuration))}` : '');
  }

  function persistOrder(previous) {
    reorderInFlight = true;
    renderPlaylist();
    request('/api/tracks/reorder', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tracks }) })
      .then(() => toast('Playlist order updated'))
      .catch(error => { tracks = previous; renderPlaylist(); toast(error.message); })
      .finally(() => {
        reorderInFlight = false;
        renderPlaylist();
        if (refreshAfterReorder) { refreshAfterReorder = false; loadPlaylist().catch(() => {}); }
      });
  }

  playlistEl.addEventListener('click', event => {
    if (reorderInFlight) return;
    const button = event.target.closest('button[data-action]');
    if (!button) return;
    const row = button.closest('.track-row');
    const index = Number(row.dataset.index);
    if (button.dataset.action === 'up' && index > 0) {
      const previous = [...tracks]; [tracks[index - 1], tracks[index]] = [tracks[index], tracks[index - 1]]; renderPlaylist(); persistOrder(previous);
    } else if (button.dataset.action === 'down' && index < tracks.length - 1) {
      const previous = [...tracks]; [tracks[index + 1], tracks[index]] = [tracks[index], tracks[index + 1]]; renderPlaylist(); persistOrder(previous);
    } else if (button.dataset.action === 'delete') {
      request('/api/tracks/' + encodeURIComponent(tracks[index]), { method: 'DELETE' }).then(loadPlaylist).then(() => toast('Track removed from rotation')).catch(error => toast(error.message));
    } else if (button.dataset.action === 'play') {
      request('/api/tracks/play', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ filename: button.dataset.filename }) })
        .then(response => response.json()).then(data => { applyNowPlaying(data); toast('Playing selected track from the beginning'); })
        .catch(error => toast(error.message));
    }
  });

  playlistEl.addEventListener('dragstart', event => {
    if (reorderInFlight) { event.preventDefault(); return; }
    const row = event.target.closest('.track-row');
    if (!row || event.target.closest('button')) { event.preventDefault(); return; }
    draggedTrack = tracks[Number(row.dataset.index)];
    row.classList.add('dragging');
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', draggedTrack);
  });
  playlistEl.addEventListener('dragend', () => {
    draggedTrack = null;
    playlistEl.querySelectorAll('.dragging,.drop-target').forEach(row => row.classList.remove('dragging', 'drop-target'));
  });
  playlistEl.addEventListener('dragover', event => {
    if (!draggedTrack || reorderInFlight) return;
    event.preventDefault();
    playlistEl.querySelectorAll('.drop-target').forEach(row => row.classList.remove('drop-target'));
    const row = event.target.closest('.track-row');
    if (row) row.classList.add('drop-target');
    event.dataTransfer.dropEffect = 'move';
  });
  playlistEl.addEventListener('drop', event => {
    if (!draggedTrack || reorderInFlight) return;
    event.preventDefault();
    const target = event.target.closest('.track-row');
    if (!target) return;
    const previous = [...tracks];
    const from = tracks.indexOf(draggedTrack);
    let to = Number(target.dataset.index);
    const after = event.clientY > target.getBoundingClientRect().top + target.offsetHeight / 2;
    if (after) to += 1;
    if (from < to) to -= 1;
    const [item] = tracks.splice(from, 1);
    tracks.splice(Math.max(0, Math.min(to, tracks.length)), 0, item);
    draggedTrack = null;
    if (tracks.some((name, index) => name !== previous[index])) { renderPlaylist(); persistOrder(previous); }
  });

  document.getElementById('loginButton').addEventListener('click', signIn);
  document.getElementById('uploadForm').addEventListener('submit', async event => {
    event.preventDefault();
    const input = document.getElementById('files');
    if (!input.files.length) { toast('Choose at least one MP3 file'); return; }
    const form = new FormData();
    for (const file of input.files) form.append('files', file);
    const submit = event.currentTarget.querySelector('button[type="submit"]');
    submit.disabled = true;
    try { const result = await uploadWithProgress(form, submit); input.value = ''; document.getElementById('selectedFiles').textContent = 'Choose one or more .mp3 files - 150 MB max each'; await loadPlaylist(); toast(`${result.uploaded.length} track${result.uploaded.length === 1 ? '' : 's'} added`); }
    catch (error) { toast(error.message); }
    finally { submit.disabled = false; submit.innerHTML = 'Add to playlist <span>&#8599;</span>'; }
  });
  document.getElementById('files').addEventListener('change', event => {
    const files = [...event.target.files];
    document.getElementById('selectedFiles').textContent = files.length
      ? `${files.length} ${files.length === 1 ? 'file' : 'files'} selected: ${files.map(file => file.name).join(', ')}`
      : 'Choose one or more .mp3 files - 150 MB max each';
  });
  document.getElementById('skipButton').addEventListener('click', async () => {
    try { const data = await (await request('/api/tracks/skip', { method: 'POST' })).json(); applyNowPlaying(data); toast('Skipping to the next track'); }
    catch (error) { toast(error.message); }
  });
  loadPlaylist().catch(() => { document.getElementById('streamStatus').textContent = 'Sign in to manage the station'; document.getElementById('statusLabel').textContent = 'ADMIN ACCESS REQUIRED'; });
  setInterval(() => loadPlaylist().catch(() => {}), 1000);
  setInterval(updateElapsed, 1000);
})();
