"""
PointLoose Bluetooth LE receiver (Windows).

The iPhone app is the BLE *peripheral*: it advertises a custom PointLoose service.
This PC is the BLE *central*: it finds the phone, connects, proves it knows the
shared pairing code (mutual HMAC check), then runs the same text commands the
Wi-Fi version uses ("m,dx,dy", "c,l", "h,ctrl+c", ...), one per line.

Needs:  pip install bleak
"""
import asyncio
import hashlib
import hmac
import os
import secrets
import sys
import threading
import time
import re
from urllib.parse import quote, unquote

import pointloose_wifi_plus as core      # exits with a message if not on Windows

SERVICE_UUID = "18d37d68-bdc2-406b-b2b8-42bb1fa94562"
TX_UUID = "4ab237d1-7713-47eb-99ba-5cb1addbd29a"   # phone -> PC (notify)
RX_UUID = "ab423fbc-f230-44e1-be31-18d4fd25b347"   # PC -> phone (write)

IDLE_TIMEOUT = 20            # seconds without any message (phone pings every 4 s)
MAX_BUFFER = 131072
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O/1/I


# ---------- pairing code ----------
def code_path():
    return os.path.join(os.path.expanduser("~"), ".pointloose_ble_code")


def _new_code():
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))


def load_code():
    try:
        with open(code_path()) as f:
            code = f.read().strip().upper()
        if len(code) >= 6:
            return code
    except OSError:
        pass
    code = _new_code()
    save_code(code)
    return code


def save_code(code):
    try:
        with open(code_path(), "w") as f:
            f.write(code)
    except OSError:
        pass


# ---------- command dispatch (same commands as the Wi-Fi version) ----------
class Session:
    def __init__(self):
        self.left_down = False


def dispatch(msg, session):
    cmd, _, rest = msg.partition(",")
    try:
        if cmd == "m":
            sx, sy = rest.split(",")
            dx, dy = core.finite(sx, 600), core.finite(sy, 600)
            if core.laser.on:
                core.laser.move(dx, dy)
            else:
                core.move_cursor(dx, dy)
        elif cmd == "s":
            core.scroll(core.finite(rest, 100))
        elif cmd == "x":
            core.hscroll(core.finite(rest, 100))
        elif cmd == "z":
            core.zoom(core.finite(rest, 100))
        elif cmd == "c" and not core.laser.on and rest in ("l", "r", "m"):
            core.mouse_button(rest, True)
            core.mouse_button(rest, False)
        elif cmd == "d" and not core.laser.on:
            core.mouse_button("l", True)
            session.left_down = True
        elif cmd == "u":
            if session.left_down:
                core.mouse_button("l", False)
                session.left_down = False
        elif cmd == "h":
            core.hotkey(rest)
        elif cmd == "t":                       # text is percent-encoded (no newlines on the wire)
            core.type_text(unquote(rest))
        elif cmd == "cp":
            core.set_clipboard(unquote(rest))
        elif cmd == "L":
            core.laser.set(rest == "1")
        elif cmd == "lc" and re.fullmatch(r"#[0-9a-fA-F]{6}", rest):
            core.laser.color = rest
        elif cmd == "ls":
            core.laser.size = int(max(6, min(30, core.finite(rest, 1000))))
        # "p" (heartbeat) and unknown commands are ignored
    except (ValueError, OSError):
        pass


def mac(code, message):
    return hmac.new(code.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


# ---------- receiver ----------
class BleReceiver:
    def __init__(self):
        self.code = load_code()
        self.status = "Bluetooth not started"
        self.connected = False
        self._stop = threading.Event()
        self._thread = None
        self._bad = {}                          # device address -> time of failed code check

    def rotate_code(self):
        self.code = _new_code()
        save_code(self.code)
        return self.code

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="pointloose-ble", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        try:
            asyncio.run(self._main())
        except Exception as exc:               # never take the app down
            self.connected = False
            self.status = "Bluetooth stopped: %s" % exc

    async def _main(self):
        try:
            from bleak import BleakClient, BleakScanner
        except Exception:
            self.status = "Bluetooth unavailable (install bleak)"
            return
        while not self._stop.is_set():
            try:
                self.status = "Looking for your phone..."
                now = time.time()
                bad = {a for a, t in self._bad.items() if now - t < 60}

                def wanted(device, adv):
                    uuids = [u.lower() for u in (adv.service_uuids or [])]
                    return SERVICE_UUID in uuids and device.address not in bad

                device = await BleakScanner.find_device_by_filter(wanted, timeout=5.0)
                if device is None:
                    continue
                await self._session(BleakClient, device)
            except Exception as exc:
                self.connected = False
                self.status = "Bluetooth problem: %s" % (str(exc) or exc.__class__.__name__)
                await asyncio.sleep(3)
            await asyncio.sleep(0.5)

    async def _write(self, client, text):
        data = text.encode("utf-8")
        size = 20
        try:
            size = max(20, int(client.mtu_size) - 3)
        except Exception:
            pass
        for i in range(0, len(data), size):
            await client.write_gatt_char(RX_UUID, data[i:i + size], response=True)

    async def _session(self, BleakClient, device):
        lines = asyncio.Queue()
        buf = bytearray()
        state = Session()

        def on_disconnect(_client):
            lines.put_nowait(None)

        def on_data(_char, data):
            buf.extend(data)
            if len(buf) > MAX_BUFFER:
                lines.put_nowait(None)
                return
            while True:
                i = buf.find(b"\n")
                if i < 0:
                    break
                line = bytes(buf[:i]).decode("utf-8", "ignore")
                del buf[:i + 1]
                lines.put_nowait(line)

        self.status = "Phone found, connecting..."
        try:
            async with BleakClient(device, disconnected_callback=on_disconnect, timeout=15.0) as client:
                self.status = "Checking pairing code..."
                await client.start_notify(TX_UUID, on_data)
                n1 = secrets.token_hex(8)
                await self._write(client, "n,%s\n" % n1)
                authed = False
                while not self._stop.is_set():
                    try:
                        line = await asyncio.wait_for(lines.get(), timeout=IDLE_TIMEOUT)
                    except asyncio.TimeoutError:
                        break
                    if line is None:
                        break
                    if not authed:
                        parts = line.split(",")
                        ok = (len(parts) == 3 and parts[0] == "a" and len(parts[2]) <= 64
                              and hmac.compare_digest(parts[1], mac(self.code, "P" + n1)))
                        if not ok:
                            self._bad[device.address] = time.time()
                            self.status = "Phone sent a wrong code. Check it in the iPhone app."
                            try:
                                await self._write(client, "x\n")
                            except Exception:
                                pass
                            break
                        await self._write(client, "v,%s\n" % mac(self.code, "C" + parts[2]))
                        authed = True
                        self.connected = True
                        self.status = "Phone connected (Bluetooth)"
                    elif line == "cg":                   # phone asks for the PC clipboard
                        try:
                            text = core.get_clipboard() or ""
                        except Exception:
                            text = ""
                        await self._write(client, "c,%s\n" % quote(text[:1500], safe=""))
                    else:
                        dispatch(line, state)
        finally:
            self.connected = False
            if state.left_down:                  # never leave a drag stuck
                core.mouse_button("l", False)
            core.laser.set(False)
            if not self.status.startswith("Phone sent"):
                self.status = "Looking for your phone..."


receiver = BleReceiver()


def main():
    print("\n  PointLoose Bluetooth receiver")
    print("  Pairing code (type it into the iPhone app):  %s\n" % receiver.code)
    receiver.start()
    last = None
    try:
        while True:
            if receiver.status != last:
                last = receiver.status
                print("  " + last)
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
