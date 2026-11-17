"""
network.py - low-level networking helpers for Net-Less Chat.

CN concepts used here:
  * IP addressing      -> find this laptop's LAN IPv4 address(es)
  * UDP broadcast      -> announce "a chat server is running here" to the whole LAN
  * Ports              -> 50000 for UDP discovery, 8000 for the web (HTTP over TCP) server
"""

import json
import socket
import threading
import time
import uuid

# ---------------- Fixed settings ----------------
DISCOVERY_PORT = 50000      # UDP port used for broadcast discovery
WEB_PORT = 8000             # TCP port for the HTTP server (tries next ports if busy)
BROADCAST_EVERY = 3         # seconds between "I'm online" broadcasts
OFFLINE_AFTER = 10          # seconds of silence -> treat as offline
APP_TAG = "netless-chat"    # so we ignore UDP packets from other apps


def get_my_ips():
    """
    Return a list of this machine's LAN IPv4 addresses (no internet needed).

    We ask the OS for every address bound to our hostname and keep only
    private ranges (RFC 1918): 10.x, 172.16-31.x, 192.168.x.
    Windows Mobile Hotspot is usually 192.168.137.1, so we put that first.
    """
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except socket.gaierror:
        pass

    # Fallback trick: "connecting" a UDP socket sends no packet, it only asks
    # the OS routing table which local IP would be used for that destination.
    for probe in ("10.255.255.255", "192.168.255.255", "172.31.255.255"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((probe, 1))
                ips.add(s.getsockname()[0])
        except OSError:
            pass

    def is_private(ip):
        a, b = (int(x) for x in ip.split(".")[:2])
        return a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168)

    good = [ip for ip in ips if is_private(ip)]
    # Hotspot address first, then the rest sorted
    good.sort(key=lambda ip: (not ip.startswith("192.168.137."), ip))
    return good or ["127.0.0.1"]


def find_free_port(start=WEB_PORT, tries=20):
    """Find a free TCP port starting at `start` (a port can be used by one server only)."""
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free port found")


class Discovery:
    """
    UDP broadcast discovery.

    Every BROADCAST_EVERY seconds we send a small JSON packet to the broadcast
    address 255.255.255.255:50000. Every device on the same Wi-Fi/hotspot
    (same subnet / broadcast domain) receives it. Routers do NOT forward
    broadcasts, so this only works on the local network - exactly what we want.

    We also listen on port 50000 and keep a table of other chat servers
    that were heard recently.
    """

    def __init__(self, name, web_port):
        self.id = uuid.uuid4().hex[:12]     # random id so we can ignore our own packets
        self.name = name
        self.web_port = web_port
        self.peers = {}                     # id -> {"name", "ip", "port", "last_seen"}
        self.lock = threading.Lock()
        self.running = False

    # ---------- public ----------
    def start(self):
        self.running = True
        threading.Thread(target=self._broadcast_loop, daemon=True).start()
        threading.Thread(target=self._listen_loop, daemon=True).start()

    def stop(self):
        self.running = False

    def get_peers(self):
        """Other servers heard in the last OFFLINE_AFTER seconds."""
        now = time.time()
        with self.lock:
            for pid in [p for p, v in self.peers.items() if now - v["last_seen"] > OFFLINE_AFTER]:
                del self.peers[pid]
            return [
                {"name": v["name"], "ip": v["ip"], "port": v["port"],
                 "url": f"http://{v['ip']}:{v['port']}"}
                for v in self.peers.values()
            ]

    # ---------- threads ----------
    def _broadcast_loop(self):
        packet = json.dumps({
            "app": APP_TAG, "id": self.id, "name": self.name, "port": self.web_port,
        }).encode()
        while self.running:
            # Send from every local interface, so both Wi-Fi and hotspot networks hear us.
            for ip in get_my_ips():
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                        # SO_BROADCAST must be enabled before sending to a broadcast address
                        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                        s.bind((ip, 0))
                        s.sendto(packet, ("255.255.255.255", DISCOVERY_PORT))
                except OSError:
                    pass  # interface down / no network - just try again later
            time.sleep(BROADCAST_EVERY)

    def _listen_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", DISCOVERY_PORT))
        except OSError:
            print(f"[discovery] UDP port {DISCOVERY_PORT} busy - other servers won't be listed")
            sock.close()
            return
        sock.settimeout(1.0)
        with sock:
            while self.running:
                try:
                    data, addr = sock.recvfrom(2048)    # UDP: one datagram = one message
                except socket.timeout:
                    continue
                except OSError:
                    continue
                try:
                    msg = json.loads(data.decode())
                except (ValueError, UnicodeDecodeError):
                    continue
                if msg.get("app") != APP_TAG or msg.get("id") == self.id:
                    continue
                with self.lock:
                    self.peers[msg["id"]] = {
                        "name": str(msg.get("name", "?"))[:40],
                        "ip": addr[0],                       # sender IP comes from the IP header
                        "port": int(msg.get("port", WEB_PORT)),
                        "last_seen": time.time(),
                    }


if __name__ == "__main__":
    # Quick terminal test: run on two laptops on the same hotspot.
    print("My IPs:", get_my_ips())
    d = Discovery(socket.gethostname(), WEB_PORT)
    d.start()
    print("Broadcasting... (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(3)
            print("Servers found:", d.get_peers())
    except KeyboardInterrupt:
        pass
