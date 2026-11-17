"""
server.py - the HTTP server and chat hub for Net-Less Chat.

CN concepts used here:
  * Client-server model  -> this laptop is the server, every browser is a client
  * TCP                  -> HTTP runs on top of TCP (reliable, ordered byte stream)
  * Application protocol -> HTTP requests/responses + a tiny JSON API
  * Server push          -> Server-Sent Events keep one TCP connection open and push messages
  * Multithreading       -> ThreadingHTTPServer gives every TCP connection its own thread
  * Integrity check      -> SHA-256 of every uploaded file
"""

import hashlib
import json
import mimetypes
import os
import queue
import re
import shutil
import sys
import threading
import time
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlparse

import qr
from network import OFFLINE_AFTER

CHUNK_SIZE = 64 * 1024        # read/write files in 64 KB pieces (never whole file in RAM)
HISTORY_LIMIT = 200           # messages kept in memory per conversation (no database)
PING_EVERY = 3                # seconds between SSE keep-alive pings
MAX_TEXT = 4000               # max characters per chat message


def resource_dir():
    """Folder with our bundled files (works for normal Python and the PyInstaller .exe)."""
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def app_dir():
    """Folder next to main.py / the .exe - where received files are stored."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


WEB_DIR = os.path.join(resource_dir(), "web")
FILES_DIR = os.path.join(app_dir(), "received_files")


def safe_filename(name):
    """Never trust a filename from the network: keep only the base name and safe characters."""
    name = os.path.basename(name.replace("\\", "/")).strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    return name[:150] or "file"


def log(text):
    """Print a timestamped line to the host's console (handy to show in the viva)."""
    print(time.strftime("[%H:%M:%S]"), text, flush=True)


def fmt_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024


def cleanup_partial_files():
    """Delete half-received files left over from a crash or power cut."""
    if os.path.isdir(FILES_DIR):
        for name in os.listdir(FILES_DIR):
            if name.endswith(".part"):
                try:
                    os.remove(os.path.join(FILES_DIR, name))
                except OSError:
                    pass


def unique_path(folder, filename):
    """Don't overwrite: notes.pdf -> notes (1).pdf -> notes (2).pdf ..."""
    base, ext = os.path.splitext(filename)
    path = os.path.join(folder, filename)
    n = 1
    while os.path.exists(path):
        path = os.path.join(folder, f"{base} ({n}){ext}")
        n += 1
    return path


class Hub:
    """Keeps track of connected users and delivers messages to them (all in memory)."""

    def __init__(self, room_name):
        self.room_name = room_name
        self.lock = threading.Lock()
        self.users = {}       # uid -> {"name", "ip", "streams": [Queue], "last_seen"}
        self.history = {}     # conversation key -> deque of messages
        self.files = {}       # file_id -> {"path", "filename", "size", "from", "to"}
        threading.Thread(target=self._janitor, daemon=True).start()

    # ---------- helpers ----------
    @staticmethod
    def conv_key(a, b):
        """Conversation key: 'all' for Everyone, otherwise the two user ids sorted."""
        return "all" if b == "all" else "|".join(sorted((a, b)))

    def user_list(self):
        return [{"id": uid, "name": u["name"], "ip": u["ip"]} for uid, u in self.users.items()]

    def _push(self, uid, event):
        """Put an event on every open browser tab of this user (caller holds the lock)."""
        u = self.users.get(uid)
        if u:
            for q in u["streams"]:
                q.put(event)

    def _broadcast(self, event):
        for uid in self.users:
            self._push(uid, event)

    # ---------- users ----------
    def connect(self, uid, name, ip):
        """A browser opened its live event stream. Returns a queue to read events from."""
        q = queue.Queue()
        with self.lock:
            is_new = uid not in self.users
            if is_new:
                self.users[uid] = {"name": name, "ip": ip, "streams": [], "last_seen": time.time()}
            u = self.users[uid]
            u["name"], u["ip"], u["last_seen"] = name, ip, time.time()
            u["streams"].append(q)
            # Send this user its starting state: who is online + recent messages it may see.
            history = []
            for key, msgs in self.history.items():
                if key == "all" or uid in key.split("|"):
                    history.extend(msgs)
            history.sort(key=lambda m: m["ts"])
            q.put({"type": "hello", "you": uid, "room": self.room_name,
                   "users": self.user_list(), "history": history})
            if is_new:
                log(f"[join]  {name} connected from {ip}")
                self._broadcast({"type": "users", "users": self.user_list(),
                                 "joined": name})
            else:
                self._broadcast({"type": "users", "users": self.user_list()})
        return q

    def disconnect(self, uid, q):
        """A browser tab closed its stream. The user stays 'online' for OFFLINE_AFTER seconds
        (so a page refresh or a short Wi-Fi hiccup does not kick them out)."""
        with self.lock:
            u = self.users.get(uid)
            if u and q in u["streams"]:
                u["streams"].remove(q)
                u["last_seen"] = time.time()

    def touch(self, uid):
        with self.lock:
            if uid in self.users:
                self.users[uid]["last_seen"] = time.time()

    def _janitor(self):
        """Every 2 s remove users that have had no open connection for OFFLINE_AFTER seconds."""
        while True:
            time.sleep(2)
            now = time.time()
            with self.lock:
                gone = [uid for uid, u in self.users.items()
                        if not u["streams"] and now - u["last_seen"] > OFFLINE_AFTER]
                for uid in gone:
                    name = self.users.pop(uid)["name"]
                    log(f"[leave] {name} went offline (no connection for {OFFLINE_AFTER}s)")
                    self._broadcast({"type": "users", "users": self.user_list(), "left": name})

    # ---------- messages ----------
    def deliver(self, msg):
        """Store a message in history and push it to the right people. Returns error text or None."""
        with self.lock:
            sender, to = msg["from"], msg["to"]
            if sender not in self.users:
                return "You are not connected. Refresh the page."
            if to != "all" and to not in self.users:
                return "That user went offline."
            msg["from_name"] = self.users[sender]["name"]
            key = self.conv_key(sender, to)
            self.history.setdefault(key, deque(maxlen=HISTORY_LIMIT)).append(msg)
            if to == "all":
                self._broadcast(msg)
            else:
                self._push(sender, msg)
                if to != sender:
                    self._push(to, msg)
            return None

    def can_download(self, file_id, uid):
        f = self.files.get(file_id)
        return f is not None and (f["to"] == "all" or uid in (f["from"], f["to"]))


class Handler(BaseHTTPRequestHandler):
    """One instance per HTTP request; runs in its own thread."""

    server_version = "NetLessChat/1.0"
    timeout = 60          # TCP socket timeout: drop clients that stop responding
    hub: Hub = None       # set in make_server()
    share_info = None     # function returning share links + discovered servers

    # Quieter console: only log errors
    def log_message(self, fmt, *args):
        pass

    # ---------- small response helpers ----------
    def send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > 64 * 1024:
            return None
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return None

    # ---------- routing ----------
    def do_GET(self):
        url = urlparse(self.path)
        qs = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/api/events":
            return self.handle_events(qs)
        if url.path == "/api/info":
            return self.send_json(self.share_info())
        if url.path == "/api/qr.svg":
            return self.handle_qr(qs.get("text", "")[:150])
        if url.path.startswith("/files/"):
            return self.handle_download(url.path[len("/files/"):], qs)
        return self.serve_static(url.path)

    def do_POST(self):
        url = urlparse(self.path)
        qs = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/api/send":
            return self.handle_send()
        if url.path == "/api/upload":
            return self.handle_upload(qs)
        self.send_json({"error": "Not found"}, 404)

    # ---------- static web files ----------
    def serve_static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        full = os.path.realpath(os.path.join(WEB_DIR, unquote(path).lstrip("/")))
        # Block path traversal like /../../secret.txt
        if not full.startswith(os.path.realpath(WEB_DIR)) or not os.path.isfile(full):
            return self.send_json({"error": "Not found"}, 404)
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if full.endswith(".js"):
            ctype = "application/javascript"
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith(("text", "application/javascript")) else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    # ---------- QR code of the share link ----------
    def handle_qr(self, text):
        if not text:
            return self.send_json({"error": "text required"}, 400)
        body = qr.to_svg(qr.make(text)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "image/svg+xml")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=3600")
        self.end_headers()
        self.wfile.write(body)

    # ---------- live events (Server-Sent Events) ----------
    def handle_events(self, qs):
        uid = re.sub(r"[^a-f0-9]", "", qs.get("id", ""))[:32]
        name = qs.get("name", "").strip()[:30]
        if not uid or not name:
            return self.send_json({"error": "id and name required"}, 400)

        # SSE = one HTTP response that never ends. The TCP connection stays open
        # and the server writes "data: {...}\n\n" whenever there is something new.
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        q = self.hub.connect(uid, name, self.client_address[0])
        try:
            while True:
                try:
                    event = q.get(timeout=PING_EVERY)
                except queue.Empty:
                    event = {"type": "ping"}   # keep-alive: also detects dead TCP connections
                    self.hub.touch(uid)
                self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                self.wfile.flush()
        except (OSError, ValueError):
            pass  # browser closed the tab or the network dropped
        finally:
            self.hub.disconnect(uid, q)

    # ---------- chat message ----------
    def handle_send(self):
        data = self.read_json()
        if not data or not str(data.get("text", "")).strip():
            return self.send_json({"error": "Empty message"}, 400)
        msg = {
            "type": "msg",
            "id": uuid.uuid4().hex[:12],
            "from": str(data.get("id", "")),
            "to": str(data.get("to", "all")),
            "text": str(data["text"])[:MAX_TEXT],
            "ts": time.time(),
        }
        err = self.hub.deliver(msg)
        if err:
            return self.send_json({"error": err}, 409)
        self.send_json({"ok": True})

    # ---------- file upload ----------
    def handle_upload(self, qs):
        uid, to = qs.get("id", ""), qs.get("to", "all")
        filename = safe_filename(qs.get("name", "file"))
        try:
            size = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self.send_json({"error": "Missing Content-Length"}, 411)
        if uid not in self.hub.users:
            return self.send_json({"error": "You are not connected. Refresh the page."}, 409)
        if to != "all" and to not in self.hub.users:
            return self.send_json({"error": "That user went offline."}, 409)

        os.makedirs(FILES_DIR, exist_ok=True)
        # Refuse early if the host's disk can't hold the file (keep 100 MB spare)
        if shutil.disk_usage(FILES_DIR).free - size < 100 * 1024 * 1024:
            self.close_connection = True   # don't try to read the huge body
            return self.send_json({"error": "Host computer's disk is full"}, 507)

        sender_name = self.hub.users.get(uid, {}).get("name", "?")
        log(f"[file]  receiving '{filename}' ({fmt_size(size)}) from {sender_name} @ {self.client_address[0]}")
        started = time.time()
        file_id = uuid.uuid4().hex
        temp_path = os.path.join(FILES_DIR, f".{file_id}.part")
        sha = hashlib.sha256()
        received = 0
        try:
            # Read the body in chunks: TCP delivers a byte stream, we rebuild the file piece by piece.
            with open(temp_path, "wb") as out:
                while received < size:
                    chunk = self.rfile.read(min(CHUNK_SIZE, size - received))
                    if not chunk:
                        break  # sender disconnected mid-transfer
                    out.write(chunk)
                    sha.update(chunk)
                    received += len(chunk)
                    if received % (CHUNK_SIZE * 32) == 0:
                        self.hub.touch(uid)
        except OSError:
            pass

        if received != size:
            # Incomplete transfer: delete the partial file, never keep broken data.
            log(f"[file]  '{filename}' INTERRUPTED at {fmt_size(received)} / {fmt_size(size)} - partial file deleted")
            try:
                os.remove(temp_path)
            except OSError:
                pass
            try:
                return self.send_json({"error": "Upload interrupted"}, 400)
            except OSError:
                return

        final_path = unique_path(FILES_DIR, filename)
        os.replace(temp_path, final_path)
        digest = sha.hexdigest()
        self.hub.files[file_id] = {"path": final_path, "filename": filename,
                                   "size": size, "from": uid, "to": to}
        msg = {
            "type": "file",
            "id": uuid.uuid4().hex[:12],
            "from": uid, "to": to,
            "file_id": file_id, "filename": filename, "size": size, "sha256": digest,
            "ts": time.time(),
        }
        secs = max(time.time() - started, 0.001)
        log(f"[file]  '{os.path.basename(final_path)}' done in {secs:.1f}s "
            f"({fmt_size(size / secs)}/s), SHA-256 {digest[:16]}...")
        err = self.hub.deliver(msg)
        if err:
            # Recipient left while we were receiving: nobody can download it, so delete it.
            self.hub.files.pop(file_id, None)
            try:
                os.remove(final_path)
            except OSError:
                pass
            return self.send_json({"error": err}, 409)
        self.send_json({"ok": True, "sha256": digest})

    # ---------- file download ----------
    def handle_download(self, file_id, qs):
        file_id = re.sub(r"[^a-f0-9]", "", file_id)
        if not self.hub.can_download(file_id, qs.get("id", "")):
            return self.send_json({"error": "File not found"}, 404)
        info = self.hub.files[file_id]
        if not os.path.isfile(info["path"]):
            return self.send_json({"error": "File was deleted on the host"}, 410)
        size = os.path.getsize(info["path"])
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(info["filename"])[0] or "application/octet-stream")
        self.send_header("Content-Length", str(size))   # lets the browser show download progress
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(info['filename'])}")
        self.end_headers()
        try:
            with open(info["path"], "rb") as f:
                while chunk := f.read(CHUNK_SIZE):
                    self.wfile.write(chunk)
        except OSError:
            pass  # receiver cancelled / disconnected


class ChatServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        """A client vanishing (Wi-Fi off, tab closed) is normal on a LAN - don't print a traceback."""
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def make_server(port, hub, share_info):
    cleanup_partial_files()
    Handler.hub = hub
    Handler.share_info = staticmethod(share_info)
    server = ChatServer(("0.0.0.0", port), Handler)   # 0.0.0.0 = listen on every network interface
    return server
