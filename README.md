# 📡 Net-Less Chat

**Chat and share files with nearby devices with no internet.**
One laptop runs Net-Less Chat. Every other device on the same **Wi-Fi or hotspot**
opens a link in its browser. **Python is not needed on the other devices.**
Works on laptops, phones, and tablets.

> A Computer Networks (B.Tech) project: UDP broadcast, TCP, HTTP, client-server model,
> sockets, ports, multithreading, and SHA-256 integrity checks. Built only with the Python standard library.

---

## ✨ Features
- 💬 **Everyone room** + **private 1-to-1 chats**
- 📎 **Send files** of any size with a live progress bar and speed (drag & drop or paste works too)
- 🖼️ Image previews, **SHA-256 checksum** shown on every file
- 🔗 **Share link** with Copy button + **QR code** (in the console and in the app), so phones just scan it
- 📶 **Auto-discovery** of other Net-Less Chat rooms on the LAN (UDP broadcast)
- 🟢 Online dots, unread badges, sound and toast notifications, offline detection
- 📱 Mobile-friendly dark UI, works **100% offline** (no CDN)
- 🪟 Single **`NetLessChat.exe`**: the host doesn't need Python either

---

## 🚀 How to run

### Option A: the .exe (easiest)
1. Double-click **`NetLessChat.exe`** (build it once, see below).
2. When Windows Firewall asks, tick **Private** *and* **Public** → **Allow access**.
3. The browser opens. Enter your name.
4. The console window shows a link like `http://192.168.137.1:8000` **and a QR code**.
   Others on the same Wi-Fi / hotspot scan the QR or type the link in **any browser**.
   (The **QR** button in the app's sidebar shows it again, bigger.)

### Option B: with Python (3.11+)
```bat
python main.py
python main.py --name "CN Lab"     :: custom room name
python main.py --port 9000         :: different port
python main.py --no-browser
```
No `pip install` is needed: it uses the standard library only.

### Build the .exe
```bat
build.bat
```
→ creates `dist\NetLessChat.exe` (~9 MB). Copy this one file to any Windows PC.

---

## 📶 Setting up a network without internet
| Situation | What to do |
|---|---|
| Wi-Fi router (no internet) | Connect all devices to it, run the app on one laptop |
| No router | On the host laptop: **Settings → Network → Mobile hotspot → On**. Others join that hotspot. Link is usually `http://192.168.137.1:8000` |
| Phone hotspot | Works if the phone allows devices to talk to each other (some block it; see troubleshooting) |

## 🛠️ Troubleshooting
- **Others can't open the link** → set the Wi-Fi network to **Private** (Settings → Network → Wi-Fi → your network), and allow the app in Windows Firewall.
- **Phone hotspot blocks devices** (client isolation) → use the laptop's Windows Mobile Hotspot instead.
- **Wrong IP shown** → disable VirtualBox / VPN adapters while testing.
- **Port busy** → the app automatically tries 8001, 8002, …

---

## 🧠 Computer Networks concepts used

```
 Phone (browser) ─┐                     ┌─────────────── Host laptop ───────────────┐
 Laptop (browser) ┼── Wi-Fi / hotspot ──┤ HTTP server  TCP :8000  (chat + files)   │
 Tablet (browser) ┘     (same LAN)      │ UDP discovery     :50000 (broadcast)     │
                                        └───────────────────────────────────────────┘
```

| Concept | Where it is used |
|---|---|
| **Client-server model** | The host laptop is the server; every browser is a client (`server.py`) |
| **TCP** (transport layer) | HTTP runs on TCP: reliable, ordered delivery for messages and files |
| **UDP broadcast** | Each server announces itself to `255.255.255.255:50000` every 3 s (`network.py`) |
| **HTTP** (application layer) | Our own JSON API: `/api/send`, `/api/upload`, `/files/...` |
| **Server push / persistent connection** | Server-Sent Events keep one TCP connection open; messages arrive instantly |
| **Ports & sockets** | 8000 (TCP), 50000 (UDP); `0.0.0.0` = listen on every interface |
| **IP addressing** | Detects private LAN IPs (10.x, 172.16-31.x, 192.168.x) to build the share link |
| **Chunking / flow** | Files are streamed in 64 KB chunks, never loaded fully into RAM |
| **Integrity** | `Content-Length` + **SHA-256** checksum of every file |
| **Failure handling** | Keep-alive pings every 3 s; users offline after 10 s; partial uploads deleted |
| **Multithreading** | One thread per TCP connection (`ThreadingHTTPServer`) |

### OSI / TCP-IP layer mapping
| Layer | In this project |
|---|---|
| Application | HTTP + our JSON messages, Server-Sent Events |
| Transport | TCP (chat, files), UDP (discovery) |
| Network | IPv4 private addresses, broadcast address |
| Data link / Physical | Wi-Fi (802.11) / hotspot |

### Viva quick answers
| Question | Answer |
|---|---|
| Why UDP for discovery? | Fast, supports broadcast, no connection needed |
| Why TCP for chat/files? | Reliable, ordered, no data loss |
| How do devices join without Python? | Every device has a browser, which is an HTTP client |
| How do messages arrive instantly? | Server-Sent Events: the server keeps the TCP connection open and pushes data |
| How is the file checked? | Size (Content-Length) + SHA-256 checksum |
| Why doesn't it work across the internet? | Broadcasts aren't forwarded by routers; private IPs aren't routable on the internet |

**Wireshark demo:** capture on Wi-Fi with filter `udp.port == 50000 || tcp.port == 8000`
to show the UDP broadcasts and the TCP 3-way handshake (SYN, SYN-ACK, ACK).

---

## 📁 Project structure
```
main.py          starts everything, prints share links, opens the browser
network.py       IP detection + UDP broadcast discovery
server.py        HTTP server: chat hub, live events (SSE), file upload/download
qr.py            pure-Python QR code generator (Reed-Solomon error correction)
web/             index.html, style.css, app.js, icon.svg (the UI)
assets/          icon.ico + make_icon.py
build.bat        builds dist/NetLessChat.exe with PyInstaller
received_files/  files received by the host (created automatically)
```

## 🔒 Notes
- Messages are kept **in memory only** (last 200 per chat). Restarting the host clears them.
- Files sent to *Everyone* can be downloaded by everyone; private files only by sender and receiver.
- Traffic is not encrypted (plain HTTP). Use it only on networks you trust.
