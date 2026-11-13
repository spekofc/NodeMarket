"""Wait for the local server, then open the storefront in the browser.

Used by run.bat / run.sh so the browser opens at the right moment instead of
racing the uvicorn startup. Stdlib only, no output.
"""

import socket
import sys
import time
import webbrowser

HOST = "127.0.0.1"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
URL = sys.argv[2] if len(sys.argv) > 2 else "http://%s:%d" % (HOST, PORT)

deadline = time.time() + 60
while time.time() < deadline:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        if s.connect_ex((HOST, PORT)) == 0:
            webbrowser.open(URL)
            break
    time.sleep(0.5)
