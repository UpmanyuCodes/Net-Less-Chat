# CLAUDE.md — Net-Less Chat: LAN Chat & File Share (No Internet)

## What we are building
A **good-looking web app** that lets devices on the **same Wi-Fi or hotspot**
**chat** and **send files** to each other **without internet**.
One laptop runs the Python server (or `NetLessChat.exe`). Every other device
(laptop, phone, tablet) just opens a **link** like `http://192.168.137.1:8000`
in its browser. **Python is not needed on the other devices.**
It is a Computer Networks project: keep the networking clear, keep the features few, make the UI polished.

- **Find servers on the LAN:** UDP broadcast (port 50000)
- **Chat + files:** HTTP over TCP (port 8000), our own server built on the standard library
- **Live updates:** Server-Sent Events (one long-lived TCP connection per browser)
- **UI:** plain HTML + CSS + JS (no CDN, works fully offline), dark theme
- **Platform:** Windows (host), any browser (clients)

## About me
- Beginner-friendly explanations: short, simple language.
- Build **one phase at a time**, commit to GitHub after each phase, and explain how to run and test it.

## Scope
**IN:** discover servers via UDP, "Everyone" room + 1-to-1 chat, send files with a progress bar,
nice UI, works on phones, shareable link, .exe build.
**OUT (do not build):** encryption, pause/resume, chat history database, unit tests, internet features.

## Tech stack
- Python 3.11+ — **standard library only**: `socket`, `http.server`, `threading`, `json`, `queue`, `os`, `hashlib`
- `pyinstaller` (only for the last phase, to make the `.exe`)

## Folder structure (keep it small)
```
Net-Less-Chat/
├── CLAUDE.md
├── README.md
├── main.py          # starts everything, prints the share links, opens the browser
├── network.py       # IP detection + UDP discovery
├── server.py        # HTTP server: chat hub, live events, file upload/download
├── web/             # index.html, style.css, app.js (the UI)
├── assets/          # app icon
└── received_files/  # uploaded files (git-ignored)
```

## Commands (VS Code terminal on Windows)
```
python main.py                 # start the server, browser opens automatically
python main.py --name "CN Lab" # custom room name
python main.py --port 9000     # custom port
```

## Fixed settings
| Setting | Value |
|---|---|
| UDP discovery port | 50000 |
| HTTP (TCP) port | 8000 (try next port if busy) |
| File chunk size | 64 KB |
| Broadcast every | 3 seconds |
| User goes offline after | 10 seconds of silence |

## Protocol
HTTP API (all JSON over TCP):
```
GET  /api/events?id=<uid>&name=<name>   -> SSE stream: hello, msg, file, users, ping
POST /api/send   {"id","to","text"}     -> to = "all" or a user id
POST /api/upload?id=&to=&name=          -> raw file bytes in body (streamed in chunks)
GET  /files/<file_id>?id=<uid>          -> download (sender/recipient only)
GET  /api/info                          -> share links + other servers found by UDP
```
Chat message: `{"type":"msg","from":"<uid>","from_name":"Upmanyu","to":"all","text":"hello","ts":...}`
File message: `{"type":"file", ..., "filename":"a.pdf","size":20480,"sha256":"...","file_id":"..."}`
UDP packet: `{"app":"netless-chat","id":"<random>","name":"Upmanyu's laptop","port":8000}`

---

## UI design
**Feel:** clean, modern, like a small WhatsApp/Discord web app. Dark theme, accent `#4F8EF7`.
- Sidebar: room name, "You: name", share link + Copy button, "Everyone" room, user cards
  (round initial avatar, green online dot, unread badge), other servers found on the LAN.
- Chat: bubbles (mine right/accent, theirs left/dark grey), timestamps, file bubble
  (icon, name, size, progress bar, Download button).
- Composer: 📎 button, drag & drop, Enter to send.
- Empty state "Looking for people on your network…" with animated dots.
- Toasts for errors ("Rahul went offline"). Mobile: sidebar becomes a slide-in drawer.

---

# Roadmap (5 phases)
1. **Networking core** — `.gitignore`, `get_my_ips()`, UDP discovery. Test: `python network.py` on two laptops.
2. **Web server + basic UI** — HTTP server, SSE events, send message, upload/download. Test: chat from a phone.
3. **Make it nice** — bubbles, avatars, unread badges, file bubbles, empty state, toasts, mobile layout.
4. **Stability** — offline handling, timeouts, aborted uploads cleaned up, 100 MB file test.
5. **Ship it** — `pyinstaller` exe, README with CN concepts + viva notes.

---

## Coding rules for Claude
- Simple, readable code; add a short comment wherever a CN concept is used.
- Always close sockets/files (`with ...`).
- No internet calls, no CDN, no outside servers.
- Never trust filenames: `basename` only, never overwrite.
- Don't add features outside the Scope.

## Windows troubleshooting
- Others can't open the link → Wi-Fi set to **Private**; on Firewall popup allow **Private and Public**.
- Phone hotspot blocks devices (AP/client isolation) → use a laptop's Windows Mobile Hotspot instead.
- VirtualBox / VPN adapters → disable while testing.

## Viva cheat sheet
| Question | Answer |
|---|---|
| Why UDP for discovery? | Fast, supports broadcast, no connection needed |
| Why TCP (HTTP) for chat/files? | Reliable, ordered, no data loss |
| Which layer is the app? | Application layer (HTTP); TCP/UDP = Transport; IP = Network |
| How do other devices join without Python? | Every device has a browser = HTTP client; the laptop is the server |
| How do messages arrive instantly? | Server-Sent Events: server keeps a TCP connection open and pushes data |
| How is the file checked? | Size (Content-Length) + SHA-256 checksum |
| Why threads? | One thread per TCP connection, so many clients are served at once |
