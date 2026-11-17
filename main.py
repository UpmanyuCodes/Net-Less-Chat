"""
main.py - start Net-Less Chat.

    python main.py                  # start with default settings
    python main.py --name "CN Lab"  # custom room name
    python main.py --port 9000      # custom TCP port

Then open the printed link on any device connected to the same Wi-Fi / hotspot.
"""

import argparse
import socket
import threading
import webbrowser

from network import Discovery, find_free_port, get_my_ips, WEB_PORT
from server import FILES_DIR, Hub, make_server


def main():
    parser = argparse.ArgumentParser(description="Net-Less Chat - LAN chat & file share without internet")
    parser.add_argument("--name", default=f"{socket.gethostname()}'s room", help="room name shown to everyone")
    parser.add_argument("--port", type=int, default=WEB_PORT, help="TCP port for the web server")
    parser.add_argument("--no-browser", action="store_true", help="don't open the browser automatically")
    args = parser.parse_args()

    port = find_free_port(args.port)
    discovery = Discovery(args.name, port)
    hub = Hub(args.name)

    def share_info():
        return {
            "room": args.name,
            "links": [f"http://{ip}:{port}" for ip in get_my_ips()],
            "servers": discovery.get_peers(),
        }

    server = make_server(port, hub, share_info)
    discovery.start()

    links = share_info()["links"]
    line = "=" * 60
    print(line)
    print("  Net-Less Chat is running  (no internet needed)")
    print(f"  Room: {args.name}")
    print(line)
    print("  Share this link with devices on the same Wi-Fi / hotspot:")
    for link in links:
        print(f"     {link}")
    print(f"\n  On this computer: http://localhost:{port}")
    print(f"  Received files are saved in: {FILES_DIR}")
    print("  If others can't connect: set Wi-Fi to 'Private' and allow the app in Windows Firewall.")
    print("  Press Ctrl+C to stop.")
    print(line)

    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{port}")).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        discovery.stop()
        server.server_close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # In the .exe the console window would close instantly - keep the error visible.
        print(f"\nError: {e}")
        input("Press Enter to close...")
