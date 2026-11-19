"""
Lab Monitor Agent — runs silently on each student PC.
Supports: Windows, Linux (Ubuntu), macOS.

FIRST RUN : python agent.py  →  will ask for server URL & token, saves to config.json
LATER RUNS: python agent.py  →  loads config.json automatically, no input needed
"""
import time, sys, platform, subprocess, re, base64, io, os, requests, json

# ── CONFIG FILE (auto-saved after first setup) ────────────────────────────────
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
INTERVAL = 5
SCREENSHOT_ON_VIOLATION = True

def load_config():
    """Load config from config.json. Never prompts — exits if config missing."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                cfg = json.load(f)
            server = cfg.get('server_url', '').strip()
            token  = cfg.get('machine_token', '').strip()
            if server and token and token != 'PASTE_TOKEN_HERE':
                return server, token
        except Exception as e:
            _log(f"Could not read config.json: {e}")
            sys.exit(1)

    # No config found — write error log and exit silently
    _log("config.json not found. Place config.json next to agent.exe and restart.")
    sys.exit(1)


def _log(msg):
    """Write log to file (since there's no console in EXE mode)."""
    try:
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'agent_log.txt')
        with open(log_path, 'a') as f:
            f.write(f"[{__import__('datetime').datetime.now()}] {msg}\n")
    except Exception:
        pass

SERVER_URL, MACHINE_TOKEN = load_config()
HEADERS = {"Authorization": f"Bearer {MACHINE_TOKEN}"}
OS           = platform.system()   # 'Windows', 'Linux', 'Darwin'
BROWSER_APPS = {"google chrome", "microsoft edge", "mozilla firefox",
                "chromium", "chromium-browser", "firefox"}

# ── Active window detection (cross-platform) ──────────────────────────────────

def get_active_window_linux():
    try:
        # Try xdotool first
        out = subprocess.check_output(
            ["xdotool", "getactivewindow", "getwindowname"],
            stderr=subprocess.DEVNULL, timeout=3
        ).decode().strip()
        return out
    except Exception:
        pass
    try:
        # Fallback: xprop
        wid = subprocess.check_output(
            ["xprop", "-root", "_NET_ACTIVE_WINDOW"],
            stderr=subprocess.DEVNULL, timeout=3
        ).decode().strip().split()[-1]
        out = subprocess.check_output(
            ["xprop", "-id", wid, "WM_NAME"],
            stderr=subprocess.DEVNULL, timeout=3
        ).decode().strip()
        m = re.search(r'"(.+)"', out)
        return m.group(1) if m else "Unknown"
    except Exception:
        return "Unknown"


def get_active_window_mac():
    try:
        script = 'tell application "System Events" to get name of first process whose frontmost is true'
        out = subprocess.check_output(
            ["osascript", "-e", script],
            stderr=subprocess.DEVNULL, timeout=3
        ).decode().strip()
        return out
    except Exception:
        return "Unknown"


def get_active_window_windows():
    try:
        import pygetwindow as gw
        win = gw.getActiveWindow()
        if win and win.title:
            return win.title.strip()
    except Exception:
        pass
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(512)
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
        return buf.value.strip() or "Unknown"
    except Exception:
        return "Unknown"


def get_active_window():
    if OS == "Windows":
        return get_active_window_windows()
    elif OS == "Linux":
        return get_active_window_linux()
    elif OS == "Darwin":
        return get_active_window_mac()
    return "Unknown"


# ── App name extraction ───────────────────────────────────────────────────────

PATTERNS = [
    (r" - Google Chrome$",    "Google Chrome"),
    (r" - Microsoft Edge$",   "Microsoft Edge"),
    (r" - Mozilla Firefox$",  "Mozilla Firefox"),
    (r"Mozilla Firefox$",     "Mozilla Firefox"),
    (r"Google Chrome$",       "Google Chrome"),
    (r" - Chromium$",         "Chromium"),
    (r" - Visual Studio Code$","Visual Studio Code"),
    (r"Visual Studio Code$",  "Visual Studio Code"),
    (r" - Notepad$",          "Notepad"),
    (r"Notepad$",             "Notepad"),
    (r"File Explorer$",       "File Explorer"),
    (r"Nautilus$",            "Files (Nautilus)"),
    (r"Discord$",             "Discord"),
    (r"Spotify$",             "Spotify"),
    (r"WhatsApp$",            "WhatsApp"),
    (r"Telegram$",            "Telegram"),
    (r"VLC media player$",    "VLC"),
    (r"Steam$",               "Steam"),
    (r"(Windows )?PowerShell","PowerShell"),
    (r"Command Prompt$",      "Command Prompt"),
    (r"Terminal$",            "Terminal"),
    (r"gedit$",               "gedit"),
    (r"kate$",                "Kate"),
]


def extract_app_name(title):
    if not title or title in ("Unknown", ""):
        return "Unknown", title
    for pattern, name in PATTERNS:
        if re.search(pattern, title, re.IGNORECASE):
            return name, title
    if " - " in title:
        parts = title.split(" - ")
        last = parts[-1].strip()
        if len(last) <= 60:
            return last, title
    return title[:50].strip() or "Unknown", title


# ── Screenshot ────────────────────────────────────────────────────────────────

def take_screenshot_b64():
    try:
        from PIL import Image, ImageGrab
        if OS == "Linux":
            # PIL ImageGrab needs DISPLAY on Linux
            os.environ.setdefault("DISPLAY", ":0")
        img = ImageGrab.grab()
        img = img.resize((960, 540), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=60)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        pass
    # Linux fallback: scrot
    if OS == "Linux":
        try:
            tmp = "/tmp/_labmonitor_shot.jpg"
            subprocess.run(["scrot", "-z", tmp], timeout=5,
                           stderr=subprocess.DEVNULL)
            with open(tmp, "rb") as f:
                return base64.b64encode(f.read()).decode()
        except Exception:
            pass
    return None


# ── Networking ────────────────────────────────────────────────────────────────

def send_heartbeat(app_name, window_title, screenshot_b64=None):
    payload = {"app_name": app_name, "window_title": window_title}
    if screenshot_b64:
        payload["screenshot"] = screenshot_b64
    try:
        r = requests.post(
            f"{SERVER_URL}/api/agent/heartbeat",
            json=payload, headers=HEADERS, timeout=6
        )
        return r.json()
    except Exception as e:
        print(f"[Agent] Heartbeat failed: {e}")
        return None


def send_offline():
    try:
        requests.post(f"{SERVER_URL}/api/agent/offline",
                      headers=HEADERS, timeout=5)
    except Exception:
        pass


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    _log(f"Agent starting on {OS} — server: {SERVER_URL}")
    last_app = None
    try:
        while True:
            try:
                raw_title = get_active_window()
                app_name, window_title = extract_app_name(raw_title)

                screenshot_b64 = None
                result = send_heartbeat(app_name, window_title)

                if result:
                    allowed = result.get("allowed", True)
                    if not allowed:
                        _log(f"VIOLATION: '{app_name}' — {window_title}")
                        if SCREENSHOT_ON_VIOLATION and app_name != last_app:
                            screenshot_b64 = take_screenshot_b64()
                            if screenshot_b64:
                                send_heartbeat(app_name, window_title, screenshot_b64)
                else:
                    _log("No response from server")

                last_app = app_name
            except Exception as e:
                _log(f"Loop error: {e}")

            time.sleep(INTERVAL)

    except KeyboardInterrupt:
        send_offline()
        sys.exit(0)
    except Exception as e:
        _log(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
