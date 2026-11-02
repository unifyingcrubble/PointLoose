"""
pointloose_wifi_plus.py - PointLoose engine: phone-as-trackpad for Windows over Wi-Fi.

Run on the PC:   python pointloose_wifi_plus.py
Then open the printed URL on your phone (same Wi-Fi). No phone app needed.
Python 3.8+ for Windows, standard library only (tkinter, bundled with the
python.org installer, is used for the optional laser-pointer overlay).

Features
  Touchpad  : 1-finger move (with acceleration), tap = click, 2-finger tap = right click,
              3-finger tap = middle click, double-tap + hold = drag
  Scrolling : 2-finger vertical + horizontal scroll, pinch = zoom (Ctrl + wheel)
  Gestures  : 3-finger swipe up = Task View, down = Show desktop,
              left/right = switch virtual desktop
  Buttons   : left / middle / right, browser back / forward
  Keys      : sticky Ctrl / Alt / Shift / Win, navigation keys, one-tap shortcuts
              (copy, paste, undo, Alt+Tab, lock, screenshot, ...)
  Clipboard : paste phone text on the PC, or pull the PC clipboard to the phone
  Present   : slide prev/next, start/end show, black/white screen, media + volume keys,
              session timer, laser pointer (multi-monitor, color + size)
  Settings  : speed, scroll speed, natural scroll, tap-to-click, haptics (saved on the phone)

Low-latency design: one WebSocket, TCP_NODELAY, no send backlog, auto-reconnect,
heartbeat, stuck-button release on disconnect, console QuickEdit disabled.
"""
import base64
import ctypes
import hashlib
import hmac
import math
import os
import re
import secrets
import socket
import struct
import sys
import threading
import time
from ctypes import wintypes as wt
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from pointloose_version import VERSION

if sys.platform != "win32":
    sys.exit("This tool only runs on Windows.")

PORT = 8765
IDLE_TIMEOUT = 20              # seconds without any message (phone pings every 4s)
MAX_CLIP = 20000               # characters moved through the clipboard bridge
TOKEN_BYTES = 16               # 128-bit secret in the link
BAD_AUTH_LIMIT = 10            # wrong links from one address within BAD_AUTH_WINDOW ...
BAD_AUTH_WINDOW = 60           # ... seconds ...
BAD_AUTH_BLOCK = 300           # ... block that address for this many seconds
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
try:
    user32.SetProcessDPIAware()          # real pixel coordinates
except Exception:
    pass
try:
    ctypes.windll.winmm.timeBeginPeriod(1)   # 1 ms timer resolution (smoother overlay)
except Exception:
    pass


def disable_quickedit():
    """Clicking inside a console window pauses the process; turn that off."""
    try:
        kernel32.GetStdHandle.restype = wt.HANDLE
        kernel32.GetConsoleMode.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
        kernel32.SetConsoleMode.argtypes = [wt.HANDLE, wt.DWORD]
        h = kernel32.GetStdHandle(-10)   # STD_INPUT_HANDLE
        mode = wt.DWORD()
        if kernel32.GetConsoleMode(h, ctypes.byref(mode)):
            kernel32.SetConsoleMode(h, (mode.value | 0x80) & ~0x40)  # EXTENDED_FLAGS on, QUICK_EDIT off
    except Exception:
        pass


# ---------- Windows input ----------
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP = 0x0020, 0x0040
MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL = 0x0800, 0x1000
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x1, 0x2, 0x4
EXTENDED_VKS = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5C}
VK_CONTROL = 0x11

KEYS = {
    "ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B,
    "enter": 0x0D, "esc": 0x1B, "tab": 0x09, "backspace": 0x08, "delete": 0x2E, "space": 0x20,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "mute": 0xAD, "voldown": 0xAE, "volup": 0xAF,
    "nexttrack": 0xB0, "prevtrack": 0xB1, "playpause": 0xB3,
}
KEYS.update({"f%d" % i: 0x6F + i for i in range(1, 13)})


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _INPUT_UNION)]


_lock = threading.Lock()
_rx = _ry = _rs = _rh = _rz = 0.0     # sub-pixel / sub-notch remainders


def move_cursor(dx, dy):
    global _rx, _ry
    with _lock:
        _rx += dx
        _ry += dy
        ix, iy = int(_rx), int(_ry)
        _rx -= ix
        _ry -= iy
        if ix or iy:
            p = wt.POINT()
            user32.GetCursorPos(ctypes.byref(p))
            user32.SetCursorPos(p.x + ix, p.y + iy)


def key_event(vk, up=False):
    flags = (KEYEVENTF_EXTENDEDKEY if vk in EXTENDED_VKS else 0) | (KEYEVENTF_KEYUP if up else 0)
    user32.keybd_event(vk, 0, flags, 0)


def tap_key(vk):
    key_event(vk, False)
    key_event(vk, True)


def wheel(flag, amount, attr):
    """Accumulate fractional notches, send whole ones. Positive = up / right."""
    with _lock:
        total = globals()[attr] + amount
        notches = int(total)
        globals()[attr] = total - notches
    return notches


def scroll(amount):
    n = wheel(MOUSEEVENTF_WHEEL, amount, "_rs")
    if n:
        user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, n * 120, 0)


def hscroll(amount):
    n = wheel(MOUSEEVENTF_HWHEEL, amount, "_rh")
    if n:
        user32.mouse_event(MOUSEEVENTF_HWHEEL, 0, 0, n * 120, 0)


def zoom(amount):
    """Pinch zoom = Ctrl + mouse wheel (works in browsers, Office, maps, Explorer...)."""
    n = wheel(MOUSEEVENTF_WHEEL, amount, "_rz")
    if n:
        key_event(VK_CONTROL, False)
        try:
            user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, n * 120, 0)
        finally:
            key_event(VK_CONTROL, True)


def mouse_button(button, down):
    flag = {("l", True): MOUSEEVENTF_LEFTDOWN, ("l", False): MOUSEEVENTF_LEFTUP,
            ("r", True): MOUSEEVENTF_RIGHTDOWN, ("r", False): MOUSEEVENTF_RIGHTUP,
            ("m", True): MOUSEEVENTF_MIDDLEDOWN, ("m", False): MOUSEEVENTF_MIDDLEUP}.get((button, down))
    if flag:
        user32.mouse_event(flag, 0, 0, 0, 0)


def resolve_key(tok):
    if tok in KEYS:
        return KEYS[tok]
    if len(tok) == 1 and tok.isascii() and tok.isalnum():
        return ord(tok.upper())
    return None


def hotkey(spec):
    """'ctrl+shift+s' -> press in order, release in reverse. Whitelisted names only."""
    toks = [t for t in spec.lower().split("+") if t]
    if not 1 <= len(toks) <= 5:
        return False
    vks = [resolve_key(t) for t in toks]
    if None in vks:
        return False
    pressed = []
    try:
        for vk in vks:
            key_event(vk, False)
            pressed.append(vk)
    finally:
        for vk in reversed(pressed):
            key_event(vk, True)
    return True


def type_text(text):
    for ch in text[:MAX_CLIP]:
        if ch in "\r\n":
            tap_key(0x0D)
            continue
        data = ch.encode("utf-16-le")
        for i in range(0, len(data), 2):
            unit = int.from_bytes(data[i:i + 2], "little")
            pair = (INPUT * 2)()
            for j, flags in enumerate((KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)):
                pair[j].type = 1
                pair[j].ki = KEYBDINPUT(0, unit, flags, 0, 0)
            user32.SendInput(2, pair, ctypes.sizeof(INPUT))


# ---------- Clipboard ----------
CF_UNICODETEXT, GMEM_MOVEABLE = 13, 0x0002


def _clipboard_setup():
    user32.OpenClipboard.argtypes = [wt.HWND]
    user32.OpenClipboard.restype = wt.BOOL
    user32.CloseClipboard.restype = wt.BOOL
    user32.EmptyClipboard.restype = wt.BOOL
    user32.SetClipboardData.argtypes = [wt.UINT, wt.HANDLE]
    user32.SetClipboardData.restype = wt.HANDLE
    user32.GetClipboardData.argtypes = [wt.UINT]
    user32.GetClipboardData.restype = wt.HANDLE
    kernel32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wt.HANDLE
    kernel32.GlobalLock.argtypes = [wt.HANDLE]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wt.HANDLE]
    kernel32.GlobalFree.argtypes = [wt.HANDLE]


def _open_clipboard():
    for _ in range(15):                      # another app may hold it briefly
        if user32.OpenClipboard(None):
            return True
        time.sleep(0.02)
    return False


def set_clipboard(text):
    data = (text[:MAX_CLIP] + "\0").encode("utf-16-le")
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not handle:
        return False
    ptr = kernel32.GlobalLock(handle)
    ctypes.memmove(ptr, data, len(data))
    kernel32.GlobalUnlock(handle)
    if not _open_clipboard():
        kernel32.GlobalFree(handle)
        return False
    try:
        user32.EmptyClipboard()
        if user32.SetClipboardData(CF_UNICODETEXT, handle):
            handle = None                    # the system owns the memory now
            return True
        return False
    finally:
        user32.CloseClipboard()
        if handle:
            kernel32.GlobalFree(handle)


def get_clipboard():
    if not _open_clipboard():
        return ""
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            return ctypes.wstring_at(ptr)[:MAX_CLIP]
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


try:
    _clipboard_setup()
except Exception:
    pass


# ---------- Laser pointer (presentation mode) ----------
class Laser:
    """While on, phone movement drives a dot (any monitor) instead of the real cursor,
    and clicks are ignored, so you can point without disturbing the slides."""

    def __init__(self):
        self.on = False
        self.x = self.y = 0.0
        self.color = "#ff2a2a"
        self.size = 11
        vx, vy = int(user32.GetSystemMetrics(76)), int(user32.GetSystemMetrics(77))
        vw, vh = int(user32.GetSystemMetrics(78)), int(user32.GetSystemMetrics(79))
        if vw <= 0 or vh <= 0:               # fall back to the primary monitor
            vx, vy = 0, 0
            vw, vh = int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
        self.vx, self.vy = vx, vy
        self.vw, self.vh = max(vw, 1), max(vh, 1)

    def set(self, on):
        if on and not self.on:
            p = wt.POINT()
            user32.GetCursorPos(ctypes.byref(p))
            self.x, self.y = float(p.x), float(p.y)
        self.on = on

    def move(self, dx, dy):
        self.x = min(max(self.x + dx, self.vx), self.vx + self.vw - 1.0)
        self.y = min(max(self.y + dy, self.vy), self.vy + self.vh - 1.0)


laser = Laser()


def _mix(rgb, other, t):
    return tuple(int(rgb[i] * (1 - t) + other[i] * t) for i in range(3))


def _hex(rgb):
    if rgb == (0, 0, 0):                     # black is the transparent key color
        rgb = (1, 0, 0)
    return "#%02x%02x%02x" % rgb


def laser_colors(color):
    rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    return _hex(_mix(rgb, (0, 0, 0), 0.55)), _hex(rgb), _hex(_mix(rgb, (255, 255, 255), 0.75))


def run_overlay(parent=None):
    """Laser overlay (tkinter, must run on the main thread). Returns False if unavailable.
    Standalone (parent=None): creates its own Tk root and blocks in mainloop().
    Embedded (parent=Tk root): creates a Toplevel and returns immediately; the caller
    owns the mainloop."""
    try:
        import tkinter as tk
    except Exception:
        print("  (tkinter not available: laser pointer disabled)")
        return False
    try:
        root = tk.Tk() if parent is None else tk.Toplevel(parent)
        root.withdraw()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-transparentcolor", "black")
        root.configure(bg="black")
        root.geometry("%dx%d%+d%+d" % (laser.vw, laser.vh, laser.vx, laser.vy))
        canvas = tk.Canvas(root, bg="black", highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        glow = canvas.create_oval(0, 0, 0, 0, outline="")
        core = canvas.create_oval(0, 0, 0, 0, outline="")
        spot = canvas.create_oval(0, 0, 0, 0, outline="")
    except Exception as e:
        print("  (laser overlay unavailable: %s)" % e)
        return False

    state = {"shown": False, "style": None}

    def make_click_through():
        try:
            user32.GetParent.restype = wt.HWND
            user32.GetParent.argtypes = [wt.HWND]
            user32.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
            user32.GetWindowLongW.restype = ctypes.c_long
            user32.SetWindowLongW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_long]
            wid = root.winfo_id()
            hwnd = user32.GetParent(wid) or wid
            ex = user32.GetWindowLongW(hwnd, -20)   # GWL_EXSTYLE
            # layered | transparent (click-through) | toolwindow | noactivate
            user32.SetWindowLongW(hwnd, -20, ex | 0x80000 | 0x20 | 0x80 | 0x08000000)
        except Exception:
            pass

    def tick():
        try:
            if laser.on and not state["shown"]:
                root.deiconify()
                root.update_idletasks()
                make_click_through()
                state["shown"] = True
            elif not laser.on and state["shown"]:
                root.withdraw()
                state["shown"] = False
            if state["shown"]:
                style = (laser.color, laser.size)
                if style != state["style"]:
                    g_col, c_col, s_col = laser_colors(laser.color)
                    canvas.itemconfig(glow, fill=g_col)
                    canvas.itemconfig(core, fill=c_col)
                    canvas.itemconfig(spot, fill=s_col)
                    state["style"] = style
                s = laser.size
                x, y = laser.x - laser.vx, laser.y - laser.vy
                canvas.coords(glow, x - 1.8 * s, y - 1.8 * s, x + 1.8 * s, y + 1.8 * s)
                canvas.coords(core, x - s, y - s, x + s, y + s)
                canvas.coords(spot, x - 0.35 * s, y - 0.35 * s, x + 0.35 * s, y + 0.35 * s)
        finally:
            root.after(8, tick)

    root.after(8, tick)
    if parent is None:
        root.mainloop()
    return True


# ---------- Web page ----------
PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#0f1216">
<title>PointLoose</title>
<style>
  *{box-sizing:border-box;-webkit-tap-highlight-color:transparent;user-select:none}
  [hidden]{display:none!important}
  html,body{margin:0;height:100%;background:#0f1216;color:#e8edf2;font:16px system-ui,sans-serif;overscroll-behavior:none}
  body{display:flex;flex-direction:column;padding:env(safe-area-inset-top) 8px env(safe-area-inset-bottom)}
  #bar{display:flex;align-items:center;gap:8px;margin:8px 2px 0;font-size:13px;color:#8fa0b3}
  #dot{width:10px;height:10px;border-radius:50%;background:#d33}
  #dot.ok{background:#3c3}
  #timer{margin-left:auto;flex:none;padding:5px 10px;font-size:13px;border-radius:10px}
  #pad{flex:1;min-height:110px;margin:8px 0;border-radius:18px;background:#1a2028;border:1px solid #2a3340;
       touch-action:none;display:flex;align-items:center;justify-content:center;color:#52606f;text-align:center;padding:12px;font-size:14px}
  #pad.laser{border-color:#e33;background:#241517;color:#a66}
  #pad.paused{border-color:#b8860b;background:#221d10;color:#b8a060}
  #dot.paused{background:#e0a800}
  .about{text-align:center;font-size:12px;color:#6b7b8c;padding:8px 4px 4px}
  #tabs{display:flex;gap:4px;margin-bottom:6px}
  #tabs button{padding:9px 2px;font-size:13px;background:#1a2028;color:#8fa0b3}
  #tabs button.on{background:#2f6feb;color:#fff}
  #panels{max-height:36vh;overflow-y:auto;overscroll-behavior:contain}
  .row{display:flex;gap:6px;margin-bottom:6px}
  button{flex:1;padding:13px 4px;border:0;border-radius:12px;background:#27313d;color:#e8edf2;font-size:15px}
  button:active{background:#3b4a5c}
  button.on{background:#c62828}
  button.mod.on{background:#2f6feb}
  .big{padding:18px 4px}
  .sw{flex:none;width:38px;height:38px;border-radius:50%;border:2px solid #2a3340}
  .sw.sel{border-color:#fff}
  input[type=text]{flex:3;padding:12px;border-radius:12px;border:1px solid #2a3340;background:#1a2028;color:#e8edf2;font-size:16px;user-select:text;min-width:0}
  .set{display:flex;align-items:center;justify-content:space-between;padding:10px 4px;font-size:15px}
  .set input[type=range]{width:55%}
  .set input[type=checkbox]{width:22px;height:22px}
</style></head><body>
<div id="bar"><span id="dot"></span><span id="st">Connecting...</span><button id="timer">&#9201; 0:00</button></div>
<div id="pad"><span id="hint"></span></div>
<div id="tabs">
  <button data-tab="mouse" class="on">Mouse</button><button data-tab="keys">Keys</button>
  <button data-tab="present">Present</button><button data-tab="more">Settings</button>
</div>
<div id="panels">
  <div class="panel" id="p-mouse">
    <div class="row"><button class="big" data-click="l">Left</button><button class="big" data-click="m">Middle</button><button class="big" data-click="r">Right</button></div>
    <div class="row"><button data-hk="alt+left">&#9664; Back</button><button data-hk="alt+right">Forward &#9654;</button><button class="laserbtn">Laser</button></div>
  </div>
  <div class="panel" id="p-keys" hidden>
    <div class="row"><button class="mod" data-mod="ctrl">Ctrl</button><button class="mod" data-mod="alt">Alt</button><button class="mod" data-mod="shift">Shift</button><button class="mod" data-mod="win">Win</button></div>
    <div class="row"><button data-key="esc">Esc</button><button data-key="tab">Tab</button><button data-key="enter">Enter</button><button data-key="backspace">&#9003;</button><button data-key="delete">Del</button><button data-key="space">Space</button></div>
    <div class="row"><button data-key="left">&#9664;</button><button data-key="up">&#9650;</button><button data-key="down">&#9660;</button><button data-key="right">&#9654;</button><button data-key="home">Home</button><button data-key="end">End</button></div>
    <div class="row"><button data-hk="ctrl+c">Copy</button><button data-hk="ctrl+v">Paste</button><button data-hk="ctrl+x">Cut</button><button data-hk="ctrl+z">Undo</button><button data-hk="ctrl+y">Redo</button></div>
    <div class="row"><button data-hk="ctrl+a">All</button><button data-hk="ctrl+s">Save</button><button data-hk="ctrl+f">Find</button><button data-hk="alt+tab">Alt+Tab</button><button data-hk="win">Win</button></div>
    <div class="row"><button data-hk="win+tab">Task view</button><button data-hk="win+d">Desktop</button><button data-hk="win+shift+s">Snip</button><button data-hk="win+l">Lock</button><button id="close">Close</button></div>
    <div class="row"><input id="txt" type="text" placeholder="Type or paste text..." autocomplete="off" autocapitalize="off"></div>
    <div class="row"><button id="typeit">Type</button><button id="pasteit">Paste on PC</button><button id="getclip">Get PC clipboard</button></div>
  </div>
  <div class="panel" id="p-present" hidden>
    <div class="row"><button class="big" data-hk="left">&#9664; Prev</button><button class="big" data-hk="right">Next &#9654;</button></div>
    <div class="row"><button data-hk="f5">Start</button><button data-hk="shift+f5">From here</button><button data-hk="esc">End</button><button data-hk="b">Black</button><button data-hk="w">White</button></div>
    <div class="row"><button data-hk="prevtrack">&#9198;</button><button data-hk="playpause">&#9199;</button><button data-hk="nexttrack">&#9197;</button><button data-hk="voldown">Vol&minus;</button><button data-hk="mute">Mute</button><button data-hk="volup">Vol+</button></div>
    <div class="row" style="align-items:center"><button class="laserbtn">Laser</button>
      <button class="sw" data-color="#ff2a2a" style="background:#ff2a2a"></button><button class="sw" data-color="#22dd44" style="background:#22dd44"></button>
      <button class="sw" data-color="#3c8cff" style="background:#3c8cff"></button><button class="sw" data-color="#ffd400" style="background:#ffd400"></button>
      <button class="sw" data-color="#ffffff" style="background:#ffffff"></button></div>
    <div class="set"><span>Laser size</span><input id="lsize" type="range" min="6" max="30" step="1"></div>
  </div>
  <div class="panel" id="p-more" hidden>
    <div class="set"><span>Pointer speed</span><input id="speed" type="range" min="0.6" max="3" step="0.1"></div>
    <div class="set"><span>Scroll speed</span><input id="scrollspd" type="range" min="0.4" max="3" step="0.1"></div>
    <div class="set"><span>Natural scrolling</span><input id="natural" type="checkbox"></div>
    <div class="set"><span>Tap to click</span><input id="tap" type="checkbox"></div>
    <div class="set"><span>Vibrate on actions (Android)</span><input id="haptic" type="checkbox"></div>
    <div class="set" style="font-size:12px;color:#6b7b8c">3-finger swipe: up Task view &middot; down Desktop &middot; left/right switch desktop &middot; 3-finger tap = middle click &middot; pinch = zoom</div>
    <div class="about">PointLoose __VERSION__ &middot; No data leaves your network<br>Only control computers you own or are allowed to use.</div>
  </div>
</div>
<script>
const $ = id => document.getElementById(id);
const DEF = {sens:1.4, scroll:1, natural:true, tap:true, haptic:true, lcolor:'#ff2a2a', lsize:11};
let cfg = Object.assign({}, DEF);
try{ Object.assign(cfg, JSON.parse(localStorage.getItem('cfg') || '{}')); }catch(e){}
const save = () => { try{ localStorage.setItem('cfg', JSON.stringify(cfg)); }catch(e){} };
const buzz = () => { if(cfg.haptic && navigator.vibrate) navigator.vibrate(8); };
document.addEventListener('click', e => { if(e.target.closest('button')) buzz(); });

const T = new URLSearchParams(location.search).get('t') || '';
const BASE_SCROLL = 0.14;
let ws = null, open = false, laser = false, paused = false, retry = 0, note = null;
const q = {dx:0, dy:0, sy:0, sx:0, z:0};

const idleText = () => open ? (paused ? 'Paused on the PC' : 'Connected') : 'Reconnecting...';
function setStatus(ok, text){ $('dot').className = ok ? (paused ? 'paused' : 'ok') : ''; $('st').textContent = text; }
function toast(t){ setStatus(open, t); clearTimeout(note); note = setTimeout(() => setStatus(open, idleText()), 1800); }
function setPaused(p){
  if(p === paused) return;
  paused = p; $('pad').classList.toggle('paused', paused); syncLaserUI(); setStatus(open, idleText());
}

function connect(){
  const proto = location.protocol === 'https:' ? 'wss://' : 'ws://';
  ws = new WebSocket(proto + location.host + '/ws?t=' + encodeURIComponent(T));
  ws.onopen = () => {
    open = true; retry = 0; setStatus(true, idleText());
    laser = false; syncLaserUI(); tx('L,0'); tx('lc,' + cfg.lcolor); tx('ls,' + cfg.lsize); tx('p');
  };
  ws.onmessage = e => {
    if(typeof e.data !== 'string') return;
    if(e.data.startsWith('c,')){ $('txt').value = e.data.slice(2); toast('PC clipboard received'); }
    else if(e.data.startsWith('P,')) setPaused(e.data === 'P,1');
  };
  ws.onclose = () => {
    open = false; q.dx = q.dy = q.sy = q.sx = q.z = 0; setStatus(false, 'Reconnecting...');
    setTimeout(connect, Math.min(500 + retry++ * 300, 3000));
  };
  ws.onerror = () => { try{ ws.close(); }catch(e){} };
}
const tx = s => { if(open && ws.readyState === 1) ws.send(s); };
connect();
setInterval(() => tx('p'), 4000);                          // heartbeat

// Send motion only when the socket has drained: no backlog, no replayed lag.
function flush(force){
  if(!open) return;
  if(!force && ws.bufferedAmount > 0) return;
  if(q.dx || q.dy){ tx('m,' + q.dx.toFixed(2) + ',' + q.dy.toFixed(2)); q.dx = q.dy = 0; }
  if(q.sy){ tx('s,' + q.sy.toFixed(3)); q.sy = 0; }
  if(q.sx){ tx('x,' + q.sx.toFixed(3)); q.sx = 0; }
  if(q.z){ tx('z,' + q.z.toFixed(3)); q.z = 0; }
}
setInterval(() => flush(false), 8);
function cmd(s){ flush(true); tx(s); }                     // keep ordering: motion first, then the action
const hk = s => cmd('h,' + s);

if(navigator.wakeLock){                                    // keep the phone screen on (HTTPS only; ignored otherwise)
  const lock = () => navigator.wakeLock.request('screen').catch(() => {});
  lock(); document.addEventListener('visibilitychange', () => { if(!document.hidden) lock(); });
}

// ---- touchpad ----
const pad = $('pad');
let g = null, lastTap = 0;
const centroid = ts => { let x = 0, y = 0; for(const t of ts){ x += t.clientX; y += t.clientY; } return {x:x/ts.length, y:y/ts.length}; };
const dist = ts => Math.hypot(ts[0].clientX - ts[1].clientX, ts[0].clientY - ts[1].clientY);

pad.addEventListener('touchstart', e => {
  e.preventDefault();
  const n = e.touches.length, c = centroid(e.touches);
  if(!g){
    g = {max:n, t0:Date.now(), moved:0, drag:false, x:c.x, y:c.y, d:0, cd:0, cm:0, mode:null, s3:null, l3:null};
    if(n === 1 && !laser && Date.now() - lastTap < 300){ g.drag = true; cmd('d,l'); }
  }
  g.max = Math.max(g.max, n); g.x = c.x; g.y = c.y;
  if(n === 2) g.d = dist(e.touches);
  if(n >= 3){ g.mode = 'swipe3'; if(!g.s3) g.s3 = {x:c.x, y:c.y}; g.l3 = {x:c.x, y:c.y}; }
}, {passive:false});

pad.addEventListener('touchmove', e => {
  e.preventDefault();
  if(!g) return;
  const n = e.touches.length, c = centroid(e.touches);
  const dx = c.x - g.x, dy = c.y - g.y;
  g.x = c.x; g.y = c.y; g.moved += Math.abs(dx) + Math.abs(dy);
  if(n === 1){
    const k = cfg.sens * (1 + Math.min(Math.hypot(dx, dy), 40) * 0.05);   // light acceleration
    q.dx += dx * k; q.dy += dy * k;
  } else if(n === 2){
    const d = dist(e.touches), dd = d - g.d;
    g.d = d; g.cd += dd; g.cm += Math.hypot(dx, dy);
    if(!g.mode && Math.abs(g.cd) + g.cm > 12) g.mode = Math.abs(g.cd) > g.cm ? 'pinch' : 'scroll';
    if(g.mode === 'pinch'){ q.z += dd * 0.08; }
    else if(g.mode === 'scroll'){
      const k = BASE_SCROLL * cfg.scroll * (cfg.natural ? 1 : -1);
      q.sy += dy * k; q.sx += -dx * k;
    }
  } else {
    g.l3 = {x:c.x, y:c.y};
  }
}, {passive:false});

function endTouch(e){
  e.preventDefault();
  if(!g) return;
  if(e.touches.length){
    const c = centroid(e.touches); g.x = c.x; g.y = c.y;
    if(e.touches.length === 2) g.d = dist(e.touches);
    return;
  }
  const tap = !g.drag && (Date.now() - g.t0) < 250 && g.moved < 10;
  if(g.mode === 'swipe3' && g.s3 && g.l3){
    const dx = g.l3.x - g.s3.x, dy = g.l3.y - g.s3.y;
    if(Math.max(Math.abs(dx), Math.abs(dy)) > 50){
      buzz();
      if(Math.abs(dx) > Math.abs(dy)) hk('ctrl+win+' + (dx > 0 ? 'right' : 'left'));
      else hk(dy < 0 ? 'win+tab' : 'win+d');
    }
  }
  if(tap && !laser && cfg.tap){
    if(g.max === 1){ cmd('c,l'); lastTap = Date.now(); buzz(); }
    else if(g.max === 2){ cmd('c,r'); buzz(); }
    else if(g.max === 3){ cmd('c,m'); buzz(); }
  }
  if(g.drag) cmd('u,l');
  g = null;
}
pad.addEventListener('touchend', endTouch, {passive:false});
pad.addEventListener('touchcancel', endTouch, {passive:false});
document.addEventListener('visibilitychange', () => { if(document.hidden && g && g.drag){ cmd('u,l'); g = null; } });

// ---- laser ----
function syncLaserUI(){
  document.querySelectorAll('.laserbtn').forEach(b => b.classList.toggle('on', laser));
  pad.classList.toggle('laser', laser);
  $('hint').innerHTML = paused
    ? 'PAUSED<br>Control was paused in the PointLoose window on the PC.'
    : laser
    ? 'LASER MODE: swipe to move the dot<br>(clicks are off; keys and gestures still work)'
    : '1 finger: move &middot; tap: click &middot; 2-finger tap: right click<br>2-finger drag: scroll &middot; pinch: zoom &middot; 3 fingers: gestures<br>double-tap + hold: drag';
}
document.querySelectorAll('.laserbtn').forEach(b => b.onclick = () => { laser = !laser; syncLaserUI(); cmd('L,' + (laser ? 1 : 0)); });
function syncSwatches(){ document.querySelectorAll('.sw').forEach(s => s.classList.toggle('sel', s.dataset.color === cfg.lcolor)); }
document.querySelectorAll('.sw').forEach(s => s.onclick = () => { cfg.lcolor = s.dataset.color; save(); syncSwatches(); tx('lc,' + cfg.lcolor); });
$('lsize').oninput = e => { cfg.lsize = +e.target.value; save(); tx('ls,' + cfg.lsize); };

// ---- buttons, keys, modifiers ----
const mods = new Set();
function refreshMods(){ document.querySelectorAll('.mod').forEach(b => b.classList.toggle('on', mods.has(b.dataset.mod))); }
function takeMods(){ const m = [...mods]; mods.clear(); refreshMods(); return m; }
document.querySelectorAll('.mod').forEach(b => b.onclick = () => { const m = b.dataset.mod; mods.has(m) ? mods.delete(m) : mods.add(m); refreshMods(); });
document.querySelectorAll('[data-click]').forEach(b => b.onclick = () => { if(!laser) cmd('c,' + b.dataset.click); });
document.querySelectorAll('[data-key]').forEach(b => b.onclick = () => hk(takeMods().concat(b.dataset.key).join('+')));
document.querySelectorAll('[data-hk]').forEach(b => b.onclick = () => hk(b.dataset.hk));
$('close').onclick = () => { if(confirm('Close the active window on the PC (Alt+F4)?')) hk('alt+f4'); };

// ---- text + clipboard ----
const txt = $('txt');
function typeIt(){
  const v = txt.value; if(!v) return;
  if(mods.size && /^[a-z0-9]$/i.test(v)) hk(takeMods().concat(v.toLowerCase()).join('+'));   // e.g. Ctrl + "c"
  else cmd('t,' + v);
  txt.value = '';
}
$('typeit').onclick = typeIt;
txt.addEventListener('keydown', e => { if(e.key === 'Enter'){ e.preventDefault(); typeIt(); } });
$('pasteit').onclick = () => { if(txt.value){ cmd('cp,' + txt.value); hk('ctrl+v'); txt.value = ''; } };
$('getclip').onclick = () => cmd('cg');

// ---- timer ----
let tState = 0, tStart = 0, tElapsed = 0, tInt = null;   // 0 idle, 1 running, 2 paused
const fmt = ms => { const s = Math.floor(ms / 1000); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); };
const paint = () => $('timer').innerHTML = '&#9201; ' + fmt(tElapsed + (tState === 1 ? Date.now() - tStart : 0));
$('timer').onclick = () => {
  if(tState === 0){ tState = 1; tStart = Date.now(); tInt = setInterval(paint, 500); }
  else if(tState === 1){ tElapsed += Date.now() - tStart; tState = 2; clearInterval(tInt); }
  else { tState = 0; tElapsed = 0; }
  paint();
};

// ---- tabs + settings ----
document.querySelectorAll('#tabs button').forEach(b => b.onclick = () => {
  document.querySelectorAll('#tabs button').forEach(x => x.classList.toggle('on', x === b));
  document.querySelectorAll('.panel').forEach(p => p.hidden = p.id !== 'p-' + b.dataset.tab);
});
$('speed').value = cfg.sens;        $('speed').oninput = e => { cfg.sens = +e.target.value; save(); };
$('scrollspd').value = cfg.scroll;  $('scrollspd').oninput = e => { cfg.scroll = +e.target.value; save(); };
for(const k of ['natural', 'tap', 'haptic']){ $(k).checked = cfg[k]; $(k).onchange = e => { cfg[k] = e.target.checked; save(); }; }
$('lsize').value = cfg.lsize; syncSwatches(); syncLaserUI();
</script></body></html>
"""


PAGE_BYTES = PAGE.replace("__VERSION__", VERSION).encode("utf-8")


# ---------- Server ----------
def token_path():
    return os.path.join(os.path.expanduser("~"), ".pointloose_token")


def save_token(tok):
    try:
        with open(token_path(), "w") as f:
            f.write(tok)
    except OSError:
        pass


def load_token():
    """Stable token (saved) so a bookmark / home-screen shortcut keeps working.
    Start with --new-token to rotate it."""
    if "--new-token" not in sys.argv:
        try:
            with open(token_path()) as f:
                tok = f.read().strip()
            if len(tok) >= 20:                 # older, shorter tokens are replaced
                return tok
        except OSError:
            pass
    tok = secrets.token_urlsafe(TOKEN_BYTES)
    save_token(tok)
    return tok


TOKEN = load_token()


def rotate_token():
    """New secret link (used by the GUI's 'New link' button)."""
    global TOKEN
    TOKEN = secrets.token_urlsafe(TOKEN_BYTES)
    save_token(TOKEN)
    return TOKEN


# Number of phones currently connected (the GUI shows this).
active_clients = 0
_clients_lock = threading.Lock()

# "Pause control" in the GUI: while True every input command from any phone is ignored.
paused = False


class AuthLimiter:
    """Blocks an address for a while after too many wrong links (stops token guessing)."""

    def __init__(self):
        self._fails = {}               # ip -> times of recent failures
        self._blocked = {}             # ip -> unblock time
        self._lock = threading.Lock()

    def blocked(self, ip):
        with self._lock:
            until = self._blocked.get(ip)
            if until and time.monotonic() < until:
                return True
            self._blocked.pop(ip, None)
            return False

    def fail(self, ip):
        now = time.monotonic()
        with self._lock:
            recent = [t for t in self._fails.get(ip, []) if now - t < BAD_AUTH_WINDOW]
            recent.append(now)
            if len(recent) >= BAD_AUTH_LIMIT:
                self._blocked[ip] = now + BAD_AUTH_BLOCK
                recent = []
            self._fails[ip] = recent


auth_limiter = AuthLimiter()


def finite(s, limit):
    v = float(s)
    if not math.isfinite(v):
        raise ValueError
    return max(-limit, min(limit, v))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def handle(self):
        try:
            super().handle()
        except OSError:      # phone slept / Wi-Fi dropped: routine, not an error
            pass

    # --- helpers ---
    def _authed(self):
        supplied = parse_qs(urlparse(self.path).query).get("t", [""])[0]
        return hmac.compare_digest(supplied.encode(), TOKEN.encode())

    def _security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                         "connect-src 'self' ws: wss:; frame-ancestors 'none'")

    def _send(self, code, body=b"", ctype="text/plain"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        ip = self.client_address[0]
        if auth_limiter.blocked(ip):
            return self._send(429, b"Too many wrong links. Try again in a few minutes.")
        if not self._authed():
            auth_limiter.fail(ip)
            return self._send(403, b"Forbidden")
        if path == "/":
            return self._send(200, PAGE_BYTES, "text/html; charset=utf-8")
        if path == "/ws":
            return self._websocket()
        self._send(404, b"Not found")

    # --- WebSocket (RFC 6455, enough for text messages) ---
    def _read_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.rfile.read(n - len(buf))
            if not chunk:
                raise ConnectionError("closed")
            buf += chunk
        return buf

    def _read_frame(self):
        b0, b1 = self._read_exact(2)
        fin, op = bool(b0 & 0x80), b0 & 0x0F
        ln = b1 & 0x7F
        if ln == 126:
            ln = struct.unpack(">H", self._read_exact(2))[0]
        elif ln == 127:
            ln = struct.unpack(">Q", self._read_exact(8))[0]
        if ln > 131072:
            raise ValueError("frame too large")
        mask = self._read_exact(4) if b1 & 0x80 else None
        payload = self._read_exact(ln) if ln else b""
        if mask:
            payload = bytes(b ^ mask[i & 3] for i, b in enumerate(payload))
        return fin, op, payload

    def _write_frame(self, op, payload=b""):
        n = len(payload)
        if n < 126:
            head = bytes([0x80 | op, n])
        elif n < 65536:
            head = bytes([0x80 | op, 126]) + struct.pack(">H", n)
        else:
            head = bytes([0x80 | op, 127]) + struct.pack(">Q", n)
        self.wfile.write(head + payload)

    def _websocket(self):
        key = self.headers.get("Sec-WebSocket-Key")
        if "websocket" not in self.headers.get("Upgrade", "").lower() or not key:
            return self._send(400, b"Bad request")
        accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        self.close_connection = True
        self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.connection.settimeout(IDLE_TIMEOUT)
        self.left_down = False
        self.token = TOKEN                          # dropped when the GUI makes a new link
        global active_clients
        with _clients_lock:
            active_clients += 1
        buf = bytearray()
        try:
            while True:
                fin, op, payload = self._read_frame()
                if self.token != TOKEN:             # link was replaced: disconnect
                    break
                if op == 0x8:                       # close
                    self._write_frame(0x8, payload[:2])
                    break
                if op == 0x9:                       # ping
                    self._write_frame(0xA, payload)
                elif op in (0x0, 0x1):              # continuation / text
                    buf += payload
                    if len(buf) > 131072:
                        break
                    if fin:
                        msg = buf.decode("utf-8", "ignore")
                        buf.clear()
                        self._dispatch(msg)
        except (OSError, ValueError):
            pass
        finally:
            with _clients_lock:
                active_clients -= 1
            if self.left_down:                      # never leave a drag stuck
                mouse_button("l", False)
            laser.set(False)

    def _dispatch(self, msg):
        cmd, _, rest = msg.partition(",")
        if cmd == "p":                              # heartbeat: report the pause state
            return self._write_frame(0x1, b"P,1" if paused else b"P,0")
        if paused and cmd != "u":                   # paused: only allow releasing a held button
            return
        try:
            if cmd == "m":
                sx, sy = rest.split(",")
                dx, dy = finite(sx, 600), finite(sy, 600)
                if laser.on:
                    laser.move(dx, dy)
                else:
                    move_cursor(dx, dy)
            elif cmd == "s":
                scroll(finite(rest, 100))
            elif cmd == "x":
                hscroll(finite(rest, 100))
            elif cmd == "z":
                zoom(finite(rest, 100))
            elif cmd == "c" and not laser.on and rest in ("l", "r", "m"):
                mouse_button(rest, True)
                mouse_button(rest, False)
            elif cmd == "d" and not laser.on:
                mouse_button("l", True)
                self.left_down = True
            elif cmd == "u":
                if self.left_down:
                    mouse_button("l", False)
                    self.left_down = False
            elif cmd == "h":
                hotkey(rest)
            elif cmd == "k":                        # raw virtual-key code (kept for compatibility)
                vk = int(rest)
                if 1 <= vk <= 254:
                    tap_key(vk)
            elif cmd == "t":
                type_text(rest)
            elif cmd == "cp":
                set_clipboard(rest)
            elif cmd == "cg":
                self._write_frame(0x1, ("c," + get_clipboard()).encode("utf-8"))
            elif cmd == "L":
                laser.set(rest == "1")
            elif cmd == "lc" and re.fullmatch(r"#[0-9a-fA-F]{6}", rest):
                laser.color = rest
            elif cmd == "ls":
                laser.size = int(max(6, min(30, finite(rest, 1000))))
            # unknown commands are ignored
        except (ValueError, OSError):
            pass


def set_paused(on):
    """Pause or resume control from every phone (Wi-Fi and Bluetooth)."""
    global paused
    paused = bool(on)
    if paused:
        laser.set(False)


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))   # no packet is actually sent
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    disable_quickedit()
    server = None
    for port in range(PORT, PORT + 10):
        try:
            server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
            break
        except OSError:
            continue
    if server is None:
        sys.exit("Could not open a port (8765-8774 all busy).")

    url = "http://%s:%d/?t=%s" % (lan_ip(), port, TOKEN)
    print("\n  PointLoose %s (Wi-Fi) running. On your phone, same Wi-Fi, open:\n" % VERSION)
    print("    %s\n" % url)
    try:  # optional QR code: pip install qrcode
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.print_ascii(invert=True)
    except Exception:
        print("  (tip: 'pip install qrcode' shows a QR code here)")
    print("\n  Tip: add the page to your phone's home screen for a one-tap shortcut.")
    print("  Anyone with this link can control this PC (and read its clipboard).")
    print("  Run with --new-token to rotate the link. Close this window to stop.\n")

    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        if not run_overlay():           # tkinter mainloop blocks until closed
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
