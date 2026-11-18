/*
 * Net-Less Chat - browser side.
 *
 * CN concepts:
 *  - HTTP requests (fetch / XMLHttpRequest) = client side of the client-server model
 *  - EventSource (Server-Sent Events) keeps ONE TCP connection open so the server can push messages
 *  - File upload is streamed over TCP; xhr.upload.onprogress shows how many bytes were sent
 */
'use strict';

// ---------------- helpers ----------------
const $ = (sel) => document.querySelector(sel);
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;   // textContent = safe, no HTML injection
  return e;
}
function randomHex(bytes) {
  const a = new Uint8Array(bytes);
  crypto.getRandomValues(a);
  return Array.from(a, (b) => b.toString(16).padStart(2, '0')).join('');
}
function fmtSize(n) {
  const u = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return (i === 0 ? n : n.toFixed(n < 10 ? 1 : 0)) + ' ' + u[i];
}
const fmtTime = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
function fmtDay(ts) {
  const d = new Date(ts * 1000), today = new Date();
  const y = new Date(); y.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return 'Today';
  if (d.toDateString() === y.toDateString()) return 'Yesterday';
  return d.toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' });
}
function colorFor(name) {
  let h = 0;
  for (const ch of name || '?') h = (h * 31 + ch.charCodeAt(0)) % 360;
  return `hsl(${h}, 55%, 48%)`;
}
function avatar(name, online) {
  const a = el('div', 'avatar' + (online ? ' online' : ''), (name || '?').trim().charAt(0).toUpperCase());
  a.style.background = colorFor(name);
  return a;
}
function fileExt(name) {
  const i = name.lastIndexOf('.');
  return i > 0 ? name.slice(i + 1).toUpperCase().slice(0, 4) : 'FILE';
}
const isImage = (name) => /\.(png|jpe?g|gif|webp|bmp)$/i.test(name);

// ---------------- state ----------------
const S = {
  id: localStorage.getItem('netlessId') || randomHex(12),
  name: localStorage.getItem('netlessName') || '',
  users: {},          // online users: id -> {id, name, ip}
  names: {},          // every user id we have seen -> name (kept after they go offline)
  convs: { all: [] }, // conversation key ('all' or other user's id) -> messages
  unread: {},         // conversation key -> count
  active: 'all',
  seen: new Set(),    // message ids already shown (avoid duplicates after reconnect)
  uploads: [],        // pending uploads: {key, row, xhr}
  es: null,
  online: false,
  everConnected: false,
};
localStorage.setItem('netlessId', S.id);

// ---------------- toasts + sound ----------------
function toast(text, kind = '') {
  const t = el('div', 'toast ' + kind, text);
  $('#toasts').appendChild(t);
  setTimeout(() => t.classList.add('hide'), 3200);
  setTimeout(() => t.remove(), 3700);
}
let audioCtx = null;
function beep() {
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    const o = audioCtx.createOscillator(), g = audioCtx.createGain();
    o.frequency.value = 880; o.type = 'sine';
    g.gain.setValueAtTime(0.08, audioCtx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + 0.25);
    o.connect(g); g.connect(audioCtx.destination);
    o.start(); o.stop(audioCtx.currentTime + 0.25);
  } catch (e) { /* no sound support - ignore */ }
}

// ---------------- join screen ----------------
function showJoin() {
  $('#join').classList.remove('hidden');
  $('#join-name').value = S.name;
  setTimeout(() => $('#join-name').focus(), 50);
}
$('#join-form').addEventListener('submit', (e) => {
  e.preventDefault();
  const name = $('#join-name').value.trim().slice(0, 30);
  if (!name) return;
  const renamed = S.name && S.name !== name;
  S.name = name;
  localStorage.setItem('netlessName', name);
  $('#join').classList.add('hidden');
  $('#app').classList.remove('hidden');
  renderMe();
  connect();               // (re)open the live connection with the new name
  if (renamed) toast('Name changed to ' + name, 'ok');
});
$('#rename-btn').addEventListener('click', showJoin);
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  $('#qr-modal').classList.add('hidden');
  if (S.name) $('#join').classList.add('hidden');
});

function renderMe() {
  $('#me-name').textContent = S.name;
  $('#me-avatar').replaceWith(Object.assign(avatar(S.name, true), { id: 'me-avatar' }));
}

// ---------------- live connection (Server-Sent Events) ----------------
function connect() {
  if (S.es) S.es.close();
  setStatus(false, 'Connecting…');
  const url = `/api/events?id=${S.id}&name=${encodeURIComponent(S.name)}`;
  const es = new EventSource(url);
  S.es = es;
  es.onopen = () => setStatus(true, 'Connected to host');
  es.onmessage = (e) => handleEvent(JSON.parse(e.data));
  es.onerror = () => {
    if (S.es !== es) return;
    if (S.online) toast('Lost connection to the host. Reconnecting…', 'error');
    setStatus(false, 'Reconnecting…');
    // The browser retries by itself; if it gave up (CLOSED) we retry manually.
    if (es.readyState === EventSource.CLOSED) setTimeout(() => S.es === es && connect(), 3000);
  };
}
function setStatus(ok, text) {
  S.online = ok;
  $('#conn-dot').className = 'status-dot ' + (ok ? 'ok' : 'bad');
  $('#conn-text').textContent = text;
  updateComposer();
}

function handleEvent(ev) {
  switch (ev.type) {
    case 'hello': {
      // Fresh state from the server (first connect or reconnect)
      $('#room-name').textContent = ev.room;
      S.convs = { all: [] };
      S.seen.clear();
      setUsers(ev.users);
      ev.history.forEach((m) => addMessage(m, true));
      if (S.everConnected) toast('Reconnected', 'ok');
      S.everConnected = true;
      renderSidebar();
      renderChat();
      break;
    }
    case 'users': {
      setUsers(ev.users);
      if (ev.joined && ev.joined !== S.name) toast(`${ev.joined} joined`, 'ok');
      if (ev.left) toast(`${ev.left} went offline`);
      renderSidebar();
      renderHeader();
      break;
    }
    case 'msg':
    case 'file':
      addMessage(ev, false);
      break;
  }
}

function setUsers(list) {
  S.users = {};
  list.forEach((u) => { S.users[u.id] = u; S.names[u.id] = u.name; });
}

// ---------------- messages ----------------
function convKey(m) {
  if (m.to === 'all') return 'all';
  return m.from === S.id ? m.to : m.from;
}

function chatVisible() {
  return window.innerWidth > 760 || $('#app').classList.contains('show-chat');
}

function addMessage(m, silent) {
  if (S.seen.has(m.id)) return;
  S.seen.add(m.id);
  if (m.from_name) S.names[m.from] = m.from_name;
  const key = convKey(m);
  (S.convs[key] = S.convs[key] || []).push(m);

  if (silent) return;
  if (key === S.active) appendRow(m, S.convs[key][S.convs[key].length - 2]);
  const mine = m.from === S.id;
  if (!mine && (key !== S.active || !chatVisible() || document.hidden)) {
    if (key !== S.active || !chatVisible()) S.unread[key] = (S.unread[key] || 0) + 1;
    beep();
  }
  renderSidebar();
  updateTitle();
}

function updateTitle() {
  const n = Object.values(S.unread).reduce((a, b) => a + b, 0);
  document.title = n ? `(${n}) Net-Less Chat` : 'Net-Less Chat';
}

// ---------------- sidebar ----------------
function previewText(key) {
  const c = S.convs[key];
  if (!c || !c.length) return key === 'all' ? 'Chat with everyone on this network' : 'Say hi 👋';
  const m = c[c.length - 1];
  const who = m.from === S.id ? 'You: ' : (key === 'all' ? (S.names[m.from] || '') + ': ' : '');
  return who + (m.type === 'file' ? '📎 ' + m.filename : m.text);
}

function chatItem(key, name, isOnline, sub) {
  const item = el('div', 'chat-item' + (key === S.active ? ' active' : '') + (isOnline ? '' : ' offline'));
  let av;
  if (key === 'all') { av = el('div', 'avatar group', '👥'); }
  else av = avatar(name, isOnline);
  const info = el('div', 'info');
  info.append(el('div', 'name', name), el('div', 'preview', sub || previewText(key)));
  item.append(av, info);
  if (S.unread[key]) item.append(el('div', 'badge', S.unread[key] > 99 ? '99+' : S.unread[key]));
  item.addEventListener('click', () => openChat(key));
  return item;
}

function renderSidebar() {
  const list = $('#chat-list');
  list.replaceChildren();
  const others = Object.values(S.users).filter((u) => u.id !== S.id);
  list.append(chatItem('all', `Everyone (${Object.keys(S.users).length} online)`, true));
  others.sort((a, b) => a.name.localeCompare(b.name))
    .forEach((u) => list.append(chatItem(u.id, u.name, true)));
  // Users who went offline but we chatted with: keep them (faded) so the chat isn't lost
  Object.keys(S.convs)
    .filter((k) => k !== 'all' && !S.users[k] && S.convs[k].length)
    .forEach((k) => list.append(chatItem(k, S.names[k] || 'Unknown', false, 'offline')));
  $('#searching').classList.toggle('hidden', others.length > 0);
}

// ---------------- chat area ----------------
function openChat(key) {
  S.active = key;
  S.unread[key] = 0;
  $('#app').classList.add('show-chat');
  renderSidebar();
  renderChat();
  updateTitle();
  if (window.innerWidth > 760) $('#text').focus();
}
$('#back-btn').addEventListener('click', () => {
  $('#app').classList.remove('show-chat');
  renderSidebar();
});

function renderHeader() {
  const key = S.active;
  let av, title, sub;
  if (key === 'all') {
    av = el('div', 'avatar group', '👥');
    title = 'Everyone';
    const names = Object.values(S.users).map((u) => (u.id === S.id ? 'You' : u.name));
    sub = names.join(', ');
  } else {
    const u = S.users[key];
    title = S.names[key] || 'Unknown';
    av = avatar(title, !!u);
    sub = u ? `online · ${u.ip}` : 'offline';
  }
  av.id = 'chat-avatar';
  $('#chat-avatar').replaceWith(av);
  $('#chat-title').textContent = title;
  $('#chat-sub').textContent = sub;
  updateComposer();
}

function updateComposer() {
  const peerOffline = S.active !== 'all' && !S.users[S.active];
  const disabled = !S.online || peerOffline;
  $('#text').disabled = disabled;
  $('#send-btn').disabled = disabled;
  $('#attach-btn').disabled = disabled;
  $('#text').placeholder = !S.online ? 'Not connected to host…'
    : peerOffline ? `${S.names[S.active] || 'User'} is offline` : 'Type a message…';
}

function renderChat() {
  renderHeader();
  const box = $('#messages');
  box.replaceChildren();
  const msgs = S.convs[S.active] || [];
  if (!msgs.length) {
    const e = el('div', 'empty-chat');
    e.append(el('div', 'big', S.active === 'all' ? '👋' : '💬'),
      el('div', '', S.active === 'all' ? 'No messages yet. Say hi to everyone!' : 'No messages yet.'),
      el('div', 'small', 'Tip: drag & drop files here to send them.'));
    box.append(e);
  }
  msgs.forEach((m, i) => appendRow(m, msgs[i - 1], false));
  // Re-attach rows of uploads still in progress for this chat
  S.uploads.filter((u) => u.key === S.active).forEach((u) => box.append(u.row));
  box.scrollTop = box.scrollHeight;
}

function fileUrl(m) { return `/files/${m.file_id}?id=${S.id}`; }

function appendRow(m, prev, scroll = true) {
  const box = $('#messages');
  const empty = box.querySelector('.empty-chat');
  if (empty) empty.remove();

  const newDay = !prev || new Date(prev.ts * 1000).toDateString() !== new Date(m.ts * 1000).toDateString();
  if (newDay) box.append(el('div', 'day', fmtDay(m.ts)));

  const mine = m.from === S.id;
  const first = newDay || !prev || prev.from !== m.from || m.ts - prev.ts > 300;
  const showAvatar = !mine && S.active === 'all';
  const name = m.from_name || S.names[m.from] || '?';

  const row = el('div', 'row' + (mine ? ' mine' : '') + (first ? ' first' : ''));
  if (showAvatar) row.append(first ? avatar(name, !!S.users[m.from]) : el('div', 'spacer'));

  const bubble = el('div', 'bubble');
  if (showAvatar && first) {
    const who = el('div', 'who', name);
    who.style.color = `hsl(${colorFor(name).match(/\d+/)[0]}, 70%, 70%)`;
    bubble.append(who);
  }
  if (m.type === 'file') bubble.append(fileContent(m));
  else bubble.append(el('div', 'text', m.text));
  bubble.append(el('div', 'time', fmtTime(m.ts)));
  row.append(bubble);

  const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 150;
  box.append(row);
  // keep pending upload rows at the very bottom
  S.uploads.filter((u) => u.key === S.active).forEach((u) => box.append(u.row));
  if (scroll && (nearBottom || mine)) box.scrollTop = box.scrollHeight;
}

function fileContent(m) {
  const wrap = el('div');
  if (isImage(m.filename)) {
    const img = el('img', 'img-preview');
    img.src = fileUrl(m);
    img.alt = m.filename;
    img.loading = 'lazy';
    img.addEventListener('click', () => {
      const v = el('div', 'viewer');
      const big = el('img'); big.src = img.src;
      v.append(big);
      v.addEventListener('click', () => v.remove());
      document.body.append(v);
    });
    img.addEventListener('load', () => {
      const box = $('#messages');
      if (box.scrollHeight - box.scrollTop - box.clientHeight < 400) box.scrollTop = box.scrollHeight;
    });
    wrap.append(img);
  }
  const card = el('div', 'file-card');
  const meta = el('div', 'file-meta');
  meta.append(el('div', 'file-name', m.filename), el('div', 'file-size', fmtSize(m.size)));
  card.append(el('div', 'file-icon', fileExt(m.filename)), meta);
  wrap.append(card);

  const actions = el('div', 'file-actions');
  const a = el('a', '', m.from === S.id ? 'Save copy' : '⬇ Download');
  a.href = fileUrl(m);
  a.download = m.filename;
  actions.append(a);
  wrap.append(actions);

  const sha = el('div', 'sha', 'SHA-256 ' + m.sha256.slice(0, 16) + '…');
  sha.title = 'SHA-256 checksum (verified by the server):\n' + m.sha256;
  wrap.append(sha);
  return wrap;
}

// ---------------- sending text ----------------
async function sendText() {
  const box = $('#text');
  const text = box.value.trim();
  if (!text || box.disabled) return;
  box.value = '';
  autoGrow();
  try {
    const r = await fetch('/api/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: S.id, to: S.active, text }),
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || 'Send failed');
  } catch (e) {
    box.value = text;   // give the text back so it isn't lost
    toast(e.message === 'Failed to fetch' ? 'Host not reachable. Check your Wi-Fi.' : e.message, 'error');
  }
}
$('#composer').addEventListener('submit', (e) => { e.preventDefault(); sendText(); });
$('#text').addEventListener('keydown', (e) => {
  // Enter = send, Shift+Enter = new line
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendText(); }
});
function autoGrow() {
  const t = $('#text');
  t.style.height = 'auto';
  t.style.height = Math.min(t.scrollHeight, 140) + 'px';
}
$('#text').addEventListener('input', autoGrow);

// ---------------- sending files ----------------
$('#attach-btn').addEventListener('click', () => $('#file-input').click());
$('#file-input').addEventListener('change', (e) => {
  [...e.target.files].forEach(uploadFile);
  e.target.value = '';
});

function uploadFile(file) {
  if (!S.online) return toast('Not connected to host', 'error');
  const key = S.active;
  if (key !== 'all' && !S.users[key]) return toast(`${S.names[key]} is offline`, 'error');

  // Pending bubble with a live progress bar
  const row = el('div', 'row mine first');
  const bubble = el('div', 'bubble');
  const card = el('div', 'file-card');
  const meta = el('div', 'file-meta');
  const status = el('div', 'file-size', `${fmtSize(file.size)} · starting…`);
  const bar = el('div');
  const prog = el('div', 'progress'); prog.append(bar);
  meta.append(el('div', 'file-name', file.name), status, prog);
  card.append(el('div', 'file-icon', fileExt(file.name)), meta);
  const actions = el('div', 'file-actions');
  const cancel = el('button', '', 'Cancel');
  actions.append(cancel);
  bubble.append(card, actions);
  row.append(bubble);

  const xhr = new XMLHttpRequest();
  const job = { key, row, xhr };
  S.uploads.push(job);
  if (key === S.active) {
    const box = $('#messages');
    box.querySelector('.empty-chat')?.remove();
    box.append(row);
    box.scrollTop = box.scrollHeight;
  }
  const done = () => {
    S.uploads = S.uploads.filter((u) => u !== job);
    row.remove();
  };

  const started = performance.now();
  xhr.upload.onprogress = (e) => {
    if (!e.lengthComputable) return;
    const pct = Math.round((e.loaded / e.total) * 100);
    const secs = (performance.now() - started) / 1000;
    const speed = secs > 0.3 ? ` · ${fmtSize(e.loaded / secs)}/s` : '';
    bar.style.width = pct + '%';
    status.textContent = `${fmtSize(e.loaded)} / ${fmtSize(e.total)} · ${pct}%${speed}`;
  };
  xhr.upload.onload = () => { status.textContent = 'Verifying checksum…'; };
  xhr.onload = () => {
    done();
    if (xhr.status !== 200) {
      let msg = 'Upload failed';
      try { msg = JSON.parse(xhr.responseText).error || msg; } catch (e) { /* ignore */ }
      toast(`${file.name}: ${msg}`, 'error');
    }
  };
  xhr.onerror = () => { done(); toast(`${file.name}: connection lost during upload`, 'error'); };
  xhr.onabort = () => { done(); toast(`${file.name}: cancelled`); };
  cancel.addEventListener('click', () => xhr.abort());

  const q = new URLSearchParams({ id: S.id, to: key, name: file.name });
  xhr.open('POST', '/api/upload?' + q);
  xhr.setRequestHeader('Content-Type', 'application/octet-stream');
  xhr.send(file);  // the browser streams the file over the TCP connection
}

// drag & drop
let dragDepth = 0;
const chatEl = $('#chat');
chatEl.addEventListener('dragenter', (e) => {
  if (![...e.dataTransfer.types].includes('Files')) return;
  e.preventDefault(); dragDepth++; $('#drop-overlay').classList.add('show');
});
chatEl.addEventListener('dragover', (e) => e.preventDefault());
chatEl.addEventListener('dragleave', () => {
  if (--dragDepth <= 0) { dragDepth = 0; $('#drop-overlay').classList.remove('show'); }
});
chatEl.addEventListener('drop', (e) => {
  e.preventDefault(); dragDepth = 0; $('#drop-overlay').classList.remove('show');
  if ($('#attach-btn').disabled) return toast('Cannot send right now', 'error');
  [...e.dataTransfer.files].forEach(uploadFile);
});
// paste an image / file from clipboard
$('#text').addEventListener('paste', (e) => {
  const files = [...(e.clipboardData?.files || [])];
  if (files.length) { e.preventDefault(); files.forEach(uploadFile); }
});

// ---------------- share link + nearby rooms (from UDP discovery) ----------------
let lastLinks = '';
async function loadInfo() {
  try {
    const r = await fetch('/api/info', { cache: 'no-store' });
    const info = await r.json();
    $('#join-room').textContent = '📶 ' + info.room;
    $('#room-name').textContent = info.room;
    const links = info.links.map((l) => l.url).join('|');
    if (links !== lastLinks) {
      lastLinks = links;
      const sel = $('#share-link');
      // Prefer the link the current browser used to reach us (it is known to work)
      const here = location.origin;
      sel.replaceChildren(...info.links.map((l) => {
        const o = el('option', '', `${l.url}  (${l.label})`);
        o.value = l.url;
        o.dataset.label = l.label;
        o.selected = l.url === here;
        return o;
      }));
    }
    const box = $('#server-list');
    box.replaceChildren();
    info.servers.forEach((s) => {
      const a = el('a', 'server-item');
      a.href = s.url;
      const t = el('div');
      t.append(el('div', '', s.name), el('div', 'url', s.url));
      a.append(avatar(s.name, true), t);
      box.append(a);
    });
    $('#servers-box').classList.toggle('hidden', !info.servers.length);
  } catch (e) { /* host unreachable - the status bar already shows it */ }
}

$('#copy-btn').addEventListener('click', async () => {
  const link = $('#share-link').value;
  try {
    await navigator.clipboard.writeText(link);   // only works on localhost / https
  } catch (e) {
    // Fallback for plain http on the LAN
    const t = el('textarea'); t.value = link;
    document.body.append(t); t.select(); document.execCommand('copy'); t.remove();
  }
  toast('Link copied: ' + link, 'ok');
});

// QR code popup (the QR image is generated by the host's Python server - works offline)
$('#qr-btn').addEventListener('click', () => {
  const link = $('#share-link').value;
  if (!link) return;
  $('#qr-img').src = '/api/qr.svg?text=' + encodeURIComponent(link);
  $('#qr-link').textContent = link;
  const opt = $('#share-link').selectedOptions[0];
  $('#qr-net').textContent = 'For devices on ' + (opt ? opt.dataset.label : 'the same network')
    + ($('#share-link').options.length > 1 ? ' — pick another link in the sidebar for other networks' : '');
  $('#qr-modal').classList.remove('hidden');
});
$('#qr-close').addEventListener('click', () => $('#qr-modal').classList.add('hidden'));
$('#qr-modal').addEventListener('click', (e) => {
  if (e.target.id === 'qr-modal') $('#qr-modal').classList.add('hidden');
});

// ---------------- start ----------------
loadInfo();
setInterval(loadInfo, 5000);
if (S.name) {
  $('#app').classList.remove('hidden');
  renderMe();
  connect();
} else {
  showJoin();
}
