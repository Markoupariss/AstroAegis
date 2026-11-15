"""AstroAegis desktop entry point. Requires pywebview for a native window."""
from pathlib import Path
import threading
import time
import webbrowser

from server import create_server

HOST, PORT = "127.0.0.1", 8765
state_dir = Path.home() / "Library" / "Application Support" / "AstroAegis"
state_dir.mkdir(parents=True, exist_ok=True)
server = create_server(HOST, PORT, state_path=state_dir / "state.json")
threading.Thread(target=server.serve_forever, daemon=True).start()
url = f"http://{HOST}:{PORT}"

try:
    import webview
    webview.create_window("AstroAegis | Crew Health Intelligence", url, width=1440, height=920,
                          min_size=(1024, 700), background_color="#07111f")
    webview.start()
except ImportError:
    print("pywebview is not installed; opening AstroAegis in your default browser.")
    webbrowser.open(url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
finally:
    server.shutdown()
