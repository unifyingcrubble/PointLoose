"""
PointLoose - turn your phone into a wireless trackpad for this PC.

This is the launcher that gets built into PointLoose.exe. It opens a small window with a
QR code: scan it with your phone's camera (same Wi-Fi) and you're connected.
The engine (server, input, laser pointer) lives in pointloose_wifi_plus.py.
"""
import ctypes
import json
import os
import socket
import sys
import threading
import time
import traceback
import tkinter as tk
from tkinter import messagebox, ttk

try:
    import segno                      # tiny pure-Python QR generator
except Exception:                     # app still works: the link is shown as text
    segno = None

import pointloose_wifi_plus as core      # exits with a message if not on Windows
import pointloose_ble as ble             # Bluetooth LE link for the iPhone app
from pointloose_version import APP_NAME, COPYRIGHT, DESCRIPTION, VERSION

QR_SIZE = 250
LOG_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), APP_NAME)
LOG_MAX_BYTES = 512 * 1024
SETTINGS_PATH = os.path.join(LOG_DIR, "settings.json")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
GREEN, GREY, AMBER = "#1b8a2e", "#777777", "#b07800"
DOCS = [("User guide", "README.md"), ("License agreement", "EULA.md"), ("Privacy policy", "PRIVACY.md"),
        ("Security", "SECURITY.md"), ("Open-source license", "LICENSE"),
        ("Third-party notices", "THIRD_PARTY_NOTICES.md")]
_mutex_handle = None                  # keep a reference so the single-instance lock lives on


def resource_path(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def write_log(text):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        path = os.path.join(LOG_DIR, "pointloose.log")
        if os.path.exists(path) and os.path.getsize(path) > LOG_MAX_BYTES:
            os.replace(path, path + ".old")          # keep one previous log, drop older ones
        with open(path, "a", encoding="utf-8") as f:
            f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + VERSION + "\n" + text + "\n")
        return path
    except OSError:
        return "(could not write a log file)"


# ---------- settings ----------
def load_settings():
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(settings):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except OSError:
        pass


def launch_command():
    """Command line that starts this app (the .exe, or pythonw + script when run from source)."""
    if getattr(sys, "frozen", False):
        return '"%s"' % sys.executable
    exe = sys.executable
    windowless = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(windowless):
        exe = windowless
    return '"%s" "%s"' % (exe, os.path.abspath(__file__))


def startup_enabled():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
        return True
    except OSError:
        return False


def set_startup(on):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if on:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


def already_running():
    """True if another PointLoose window is open (named mutex)."""
    global _mutex_handle
    try:
        kernel32 = ctypes.windll.kernel32
        _mutex_handle = kernel32.CreateMutexW(None, False, "Local\\PointLoosePhoneTrackpad")
        return kernel32.GetLastError() == 183          # ERROR_ALREADY_EXISTS
    except Exception:
        return False


def candidate_ips():
    """LAN addresses this PC has; the first one is the one Windows uses for the internet."""
    ips = []
    primary = core.lan_ip()
    if primary != "127.0.0.1":
        ips.append(primary)
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if not ip.startswith(("127.", "169.254.")) and ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    return ips or ["127.0.0.1"]


def start_server():
    server = None
    for port in range(core.PORT, core.PORT + 10):
        try:
            server = core.ThreadingHTTPServer(("0.0.0.0", port), core.Handler)
            break
        except OSError:
            continue
    if server is None:
        raise RuntimeError("Could not open a network port (8765-8774 are all busy).")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return port


# ---------- documents (license, privacy, ...) ----------
def read_doc(name):
    try:
        with open(resource_path(name), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return "%s is not included in this build.\nSee the PointLoose repository for the full text." % name


def doc_window(parent, title, name, accept=None):
    """Read-only text viewer. With accept=callback it becomes the first-run agreement dialog."""
    win = tk.Toplevel(parent)
    win.title("%s - %s" % (APP_NAME, title))
    if parent.winfo_viewable():           # a transient of a hidden window would stay hidden too
        win.transient(parent)
    try:
        win.iconbitmap(resource_path("pointloose.ico"))
    except tk.TclError:
        pass
    frm = ttk.Frame(win, padding=12)
    frm.pack(fill="both", expand=True)
    if accept:
        ttk.Label(frm, text="Please read and accept the license agreement to use %s." % APP_NAME,
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 8))
    body = ttk.Frame(frm)
    body.pack(fill="both", expand=True)
    text = tk.Text(body, wrap="word", width=78, height=26, font=("Segoe UI", 9), relief="flat",
                   padx=10, pady=8, background="#ffffff")
    bar = ttk.Scrollbar(body, command=text.yview)
    text.configure(yscrollcommand=bar.set)
    text.pack(side="left", fill="both", expand=True)
    bar.pack(side="right", fill="y")
    text.insert("1.0", read_doc(name))
    text.configure(state="disabled")

    buttons = ttk.Frame(frm)
    buttons.pack(fill="x", pady=(10, 0))
    if accept:
        def decline():
            win.destroy()
            accept(False)

        def agree():
            win.destroy()
            accept(True)
        ttk.Button(buttons, text="Decline", command=decline).pack(side="right")
        ttk.Button(buttons, text="I agree", command=agree).pack(side="right", padx=(0, 6))
        win.protocol("WM_DELETE_WINDOW", decline)
        win.grab_set()
    else:
        ttk.Button(buttons, text="Close", command=win.destroy).pack(side="right")
    win.focus_set()
    return win


# ---------- main window ----------
class App:
    def __init__(self, root, port, settings):
        self.root = root
        self.port = port
        self.settings = settings
        self.ips = candidate_ips()
        self.ip = tk.StringVar(value=self.ips[0])
        self.url = tk.StringVar()
        self.startup = tk.BooleanVar(value=startup_enabled())

        root.title(APP_NAME)
        root.resizable(False, False)
        try:
            root.iconbitmap(resource_path("pointloose.ico"))
        except tk.TclError:
            pass
        try:
            ttk.Style().theme_use("vista")
        except tk.TclError:
            pass
        self.build_menu()

        frm = ttk.Frame(root, padding=16)
        frm.grid()
        ttk.Label(frm, text=APP_NAME, font=("Segoe UI", 18, "bold")).grid(row=0, column=0, columnspan=2)
        ttk.Label(frm, text="Scan with your phone's camera to use it as a trackpad",
                  wraplength=QR_SIZE + 20, justify="center").grid(row=1, column=0, columnspan=2, pady=(2, 10))

        self.canvas = tk.Canvas(frm, width=QR_SIZE, height=QR_SIZE, bg="white",
                                highlightthickness=1, highlightbackground="#bbbbbb")
        self.canvas.grid(row=2, column=0, columnspan=2)

        self.status = tk.Label(frm, text="", font=("Segoe UI", 10, "bold"))
        self.status.grid(row=3, column=0, columnspan=2, pady=(10, 4))
        self.pause_btn = ttk.Button(frm, text="Pause control", command=self.toggle_pause)
        self.pause_btn.grid(row=4, column=0, columnspan=2, pady=(0, 8))

        if len(self.ips) > 1:
            row = ttk.Frame(frm)
            row.grid(row=5, column=0, columnspan=2, pady=(0, 6))
            ttk.Label(row, text="PC address:").pack(side="left", padx=(0, 6))
            box = ttk.Combobox(row, textvariable=self.ip, values=self.ips, state="readonly", width=16)
            box.pack(side="left")
            box.bind("<<ComboboxSelected>>", lambda e: self.refresh())

        entry = ttk.Entry(frm, textvariable=self.url, state="readonly", width=38)
        entry.grid(row=6, column=0, columnspan=2, sticky="ew")
        entry.bind("<FocusIn>", lambda e: entry.selection_range(0, "end"))

        self.copy_btn = ttk.Button(frm, text="Copy link", command=self.copy_link)
        self.copy_btn.grid(row=7, column=0, sticky="ew", padx=(0, 4), pady=(8, 0))
        ttk.Button(frm, text="New link", command=self.new_link).grid(row=7, column=1, sticky="ew",
                                                                     padx=(4, 0), pady=(8, 0))

        bt = ttk.LabelFrame(frm, text="Bluetooth (iPhone app)", padding=8)
        bt.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Label(bt, text="Pairing code:").grid(row=0, column=0, sticky="w")
        self.ble_code = tk.StringVar(value=ble.receiver.code)
        ttk.Entry(bt, textvariable=self.ble_code, state="readonly", width=12,
                  font=("Consolas", 12, "bold")).grid(row=0, column=1, padx=(6, 6))
        ttk.Button(bt, text="New code", command=self.new_ble_code).grid(row=0, column=2)
        self.ble_status = tk.Label(bt, text="", font=("Segoe UI", 9), anchor="w", justify="left",
                                   wraplength=QR_SIZE - 10)
        self.ble_status.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))

        ttk.Label(frm, wraplength=QR_SIZE + 20, justify="center", foreground="#666666", font=("Segoe UI", 8),
                  text="Phone and PC must be on the same Wi-Fi. If it won't connect, allow PointLoose in the "
                       "Windows Firewall pop-up (tick 'Private networks'). "
                       "Anyone with this link can control this PC, so keep it private."
                  ).grid(row=9, column=0, columnspan=2, pady=(12, 0))
        ttk.Label(frm, text="v%s" % VERSION, foreground="#999999", font=("Segoe UI", 8)
                  ).grid(row=10, column=0, columnspan=2, pady=(6, 0))

        self.refresh()
        self.poll()

    def build_menu(self):
        bar = tk.Menu(self.root)
        app_menu = tk.Menu(bar, tearoff=False)
        app_menu.add_checkbutton(label="Start with Windows", variable=self.startup, command=self.toggle_startup)
        app_menu.add_separator()
        app_menu.add_command(label="Open log folder", command=self.open_log_folder)
        app_menu.add_separator()
        app_menu.add_command(label="Exit", command=self.root.destroy)
        bar.add_cascade(label="Settings", menu=app_menu)

        help_menu = tk.Menu(bar, tearoff=False)
        for title, name in DOCS:
            help_menu.add_command(label=title, command=lambda t=title, n=name: doc_window(self.root, t, n))
        help_menu.add_separator()
        help_menu.add_command(label="About %s" % APP_NAME, command=self.about)
        bar.add_cascade(label="Help", menu=help_menu)
        self.root.configure(menu=bar)

    # --- actions ---
    def make_url(self):
        return "http://%s:%d/?t=%s" % (self.ip.get(), self.port, core.TOKEN)

    def refresh(self):
        url = self.make_url()
        self.url.set(url)
        self.draw_qr(url)

    def draw_qr(self, url):
        c = self.canvas
        c.delete("all")
        if segno is None:
            c.create_text(QR_SIZE // 2, QR_SIZE // 2, justify="center",
                          text="QR code unavailable.\nType the link below\ninto your phone's browser.")
            return
        matrix = segno.make(url, error="m", micro=False).matrix
        n, quiet = len(matrix), 2
        cell = max(1, QR_SIZE // (n + 2 * quiet))
        offset = (QR_SIZE - cell * (n + 2 * quiet)) // 2 + quiet * cell
        for r, row in enumerate(matrix):
            for col, dark in enumerate(row):
                if dark:
                    x, y = offset + col * cell, offset + r * cell
                    c.create_rectangle(x, y, x + cell, y + cell, fill="black", outline="")

    def copy_link(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.url.get())
        self.root.update()
        self.copy_btn.configure(text="Copied!")
        self.root.after(1500, lambda: self.copy_btn.configure(text="Copy link"))

    def new_link(self):
        if messagebox.askyesno("New link", "Create a new link?\n\nPhones using the old link are disconnected "
                                           "and need to scan the new QR code."):
            core.rotate_token()
            self.refresh()

    def new_ble_code(self):
        if messagebox.askyesno("New code", "Create a new Bluetooth code?\n\nA connected iPhone is disconnected "
                                           "and you need to type the new code into the app."):
            self.ble_code.set(ble.receiver.rotate_code())

    def toggle_pause(self):
        core.set_paused(not core.paused)
        self.pause_btn.configure(text="Resume control" if core.paused else "Pause control")
        self.poll(reschedule=False)

    def toggle_startup(self):
        try:
            set_startup(self.startup.get())
        except OSError as exc:
            self.startup.set(startup_enabled())
            messagebox.showerror(APP_NAME, "Could not change the startup setting:\n%s" % exc)

    def open_log_folder(self):
        os.makedirs(LOG_DIR, exist_ok=True)
        os.startfile(LOG_DIR)

    def about(self):
        messagebox.showinfo("About %s" % APP_NAME,
                            "%s %s\n%s\n\n%s\n\nOpen source under the MIT License. "
                            "Use of this build is subject to the PointLoose License Agreement "
                            "(Help > License agreement)." % (APP_NAME, VERSION, DESCRIPTION, COPYRIGHT))

    def poll(self, reschedule=True):
        self.ble_status.configure(text=ble.receiver.status, fg=GREEN if ble.receiver.connected else GREY)
        phones = core.active_clients + (1 if ble.receiver.connected else 0)
        if core.paused:
            self.status.configure(text="⏸ Paused: phone input is ignored", fg=AMBER)
        elif phones > 1:
            self.status.configure(text="● %d phones connected" % phones, fg=GREEN)
        elif phones == 1:
            self.status.configure(text="● Phone connected", fg=GREEN)
        else:
            self.status.configure(text="○ Waiting for your phone...", fg=GREY)
        if reschedule:
            self.root.after(500, self.poll)


def ask_agreement(root, settings):
    """First run (or new agreement version): show the EULA and record acceptance. Returns True if accepted."""
    if settings.get("eula_accepted") == VERSION.split(".")[0]:
        return True
    result = {"ok": False}

    def done(ok):
        result["ok"] = ok
        root.quit()

    doc_window(root, "License agreement", "EULA.md", accept=done)
    root.mainloop()
    if result["ok"]:
        settings["eula_accepted"] = VERSION.split(".")[0]        # ask again on the next major version
        settings["eula_accepted_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        save_settings(settings)
    return result["ok"]


def main():
    if already_running():
        messagebox.showinfo(APP_NAME, "%s is already running. Look for its window in the taskbar." % APP_NAME)
        return
    try:
        root = tk.Tk()
        root.report_callback_exception = lambda *a: write_log("".join(traceback.format_exception(*a)))
        settings = load_settings()
        root.withdraw()
        if not ask_agreement(root, settings):
            root.destroy()
            return
        port = start_server()
        App(root, port, settings)
        root.deiconify()
        ble.receiver.start()
        core.run_overlay(root)            # laser pointer overlay (hidden until you switch Laser on)
        root.mainloop()
    except Exception:
        path = write_log(traceback.format_exc())
        messagebox.showerror(APP_NAME, "%s couldn't start.\n\nDetails were saved to:\n%s" % (APP_NAME, path))


if __name__ == "__main__":
    main()
