"""
PointLoose - turn your phone into a wireless trackpad for this PC.

This is the launcher that gets built into PointLoose.exe. It opens a small window with a
QR code: scan it with your phone's camera (same Wi-Fi) and you're connected.
The engine (server, input, laser pointer) lives in pointloose_wifi_plus.py.
"""
import ctypes
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

QR_SIZE = 250
LOG_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "PointLoose")
_mutex_handle = None                  # keep a reference so the single-instance lock lives on


def resource_path(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def write_log(text):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        path = os.path.join(LOG_DIR, "pointloose.log")
        with open(path, "a", encoding="utf-8") as f:
            f.write(time.strftime("[%Y-%m-%d %H:%M:%S]\n") + text + "\n")
        return path
    except OSError:
        return "(could not write a log file)"


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


class App:
    def __init__(self, root, port):
        self.root = root
        self.port = port
        self.ips = candidate_ips()
        self.ip = tk.StringVar(value=self.ips[0])
        self.url = tk.StringVar()

        root.title("PointLoose")
        root.resizable(False, False)
        try:
            root.iconbitmap(resource_path("pointloose.ico"))
        except tk.TclError:
            pass
        try:
            ttk.Style().theme_use("vista")
        except tk.TclError:
            pass

        frm = ttk.Frame(root, padding=16)
        frm.grid()
        ttk.Label(frm, text="PointLoose", font=("Segoe UI", 18, "bold")).grid(row=0, column=0, columnspan=2)
        ttk.Label(frm, text="Scan with your phone's camera to use it as a trackpad",
                  wraplength=QR_SIZE + 20, justify="center").grid(row=1, column=0, columnspan=2, pady=(2, 10))

        self.canvas = tk.Canvas(frm, width=QR_SIZE, height=QR_SIZE, bg="white",
                                highlightthickness=1, highlightbackground="#bbbbbb")
        self.canvas.grid(row=2, column=0, columnspan=2)

        self.status = tk.Label(frm, text="", font=("Segoe UI", 10, "bold"))
        self.status.grid(row=3, column=0, columnspan=2, pady=(10, 4))

        if len(self.ips) > 1:
            row = ttk.Frame(frm)
            row.grid(row=4, column=0, columnspan=2, pady=(0, 6))
            ttk.Label(row, text="PC address:").pack(side="left", padx=(0, 6))
            box = ttk.Combobox(row, textvariable=self.ip, values=self.ips, state="readonly", width=16)
            box.pack(side="left")
            box.bind("<<ComboboxSelected>>", lambda e: self.refresh())

        entry = ttk.Entry(frm, textvariable=self.url, state="readonly", width=38)
        entry.grid(row=5, column=0, columnspan=2, sticky="ew")
        entry.bind("<FocusIn>", lambda e: entry.selection_range(0, "end"))

        self.copy_btn = ttk.Button(frm, text="Copy link", command=self.copy_link)
        self.copy_btn.grid(row=6, column=0, sticky="ew", padx=(0, 4), pady=(8, 0))
        ttk.Button(frm, text="New link", command=self.new_link).grid(row=6, column=1, sticky="ew",
                                                                     padx=(4, 0), pady=(8, 0))

        bt = ttk.LabelFrame(frm, text="Bluetooth (iPhone app)", padding=8)
        bt.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(12, 0))
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
                  ).grid(row=8, column=0, columnspan=2, pady=(12, 0))

        self.refresh()
        self.poll()

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
        if messagebox.askyesno("New link", "Create a new link?\n\nPhones using the old link will need "
                                           "to scan the new QR code to reconnect."):
            core.rotate_token()
            self.refresh()

    def new_ble_code(self):
        if messagebox.askyesno("New code", "Create a new Bluetooth code?\n\nYou will need to type it "
                                           "into the iPhone app again."):
            self.ble_code.set(ble.receiver.rotate_code())

    def poll(self):
        self.ble_status.configure(text=ble.receiver.status,
                                  fg="#1b8a2e" if ble.receiver.connected else "#777777")
        if core.active_clients > 0 or ble.receiver.connected:
            self.status.configure(text="\u25CF Phone connected", fg="#1b8a2e")
        else:
            self.status.configure(text="\u25CB Waiting for your phone...", fg="#777777")
        self.root.after(500, self.poll)


def main():
    if already_running():
        messagebox.showinfo("PointLoose", "PointLoose is already running. Look for its window in the taskbar.")
        return
    try:
        port = start_server()
        root = tk.Tk()
        root.report_callback_exception = lambda *a: write_log("".join(traceback.format_exception(*a)))
        App(root, port)
        ble.receiver.start()
        core.run_overlay(root)            # laser pointer overlay (hidden until you switch Laser on)
        root.mainloop()
    except Exception:
        path = write_log(traceback.format_exc())
        messagebox.showerror("PointLoose", "PointLoose couldn't start.\n\nDetails were saved to:\n" + path)


if __name__ == "__main__":
    main()
