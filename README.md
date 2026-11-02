<p align="center"><img src="ios/PointLoose/Assets.xcassets/Logo.imageset/logo.png" width="96" alt="PointLoose logo"></p>

<h1 align="center">PointLoose</h1>

<p align="center">Use your phone as a wireless trackpad, keyboard and presenter for your Windows PC.<br>
No phone app needed: scan a QR code and go.</p>

---

## Features

- **Trackpad:** pointer acceleration, tap to click, two-finger right click, three-finger middle click, double-tap-and-hold to drag.
- **Scroll and zoom:** two-finger scrolling in both directions, natural scrolling option, pinch to zoom.
- **Windows gestures:** three-finger swipe up for Task View, down for Show Desktop, left/right to switch virtual desktops.
- **Keyboard:** sticky Ctrl / Alt / Shift / Win, arrow and navigation keys, one-tap shortcuts (copy, paste, undo, snip, lock, Alt+Tab).
- **Clipboard bridge:** send phone text to the PC clipboard, or pull the PC clipboard to the phone.
- **Presenter:** previous/next slide, start/end show, black/white screen, media and volume keys, session timer, and an on-screen laser pointer that works across monitors.
- **Two ways to connect:** Wi-Fi from any phone browser, or Bluetooth LE with the iPhone app.
- **Private by design:** no accounts, no cloud, no tracking. See [PRIVACY.md](PRIVACY.md).

## Quick start (Windows)

1. Download `PointLoose.exe` from the [Releases](../../releases) page and open it.
   - If Windows SmartScreen appears, choose **More info → Run anyway** (the app is not code-signed yet).
   - When the firewall asks, allow **Private networks**. Without this your phone cannot connect.
2. Read and accept the licence agreement (first launch only).
3. Make sure your phone is on the same Wi-Fi as the PC.
4. Scan the QR code with your phone camera and open the link. Tip: **Add to Home Screen** for a one-tap shortcut.

## Phone controls

| Gesture | Action |
|---|---|
| 1 finger | Move the pointer |
| Tap | Left click |
| 2-finger tap | Right click |
| 3-finger tap | Middle click |
| Double-tap + hold | Drag |
| 2-finger drag | Scroll (vertical and horizontal) |
| Pinch | Zoom (Ctrl + wheel) |
| 3-finger swipe up / down | Task View / Show Desktop |
| 3-finger swipe left / right | Switch virtual desktop |

The tabs below the pad hold **Mouse** buttons, **Keys** and shortcuts, **Present** tools and **Settings**.

## PC window

- **Pause control:** ignore the phone until you resume, without disconnecting.
- **New link / New code:** replace the Wi-Fi link or Bluetooth pairing code, disconnecting anyone using the old one.
- **Settings → Start with Windows:** launch PointLoose when you sign in.
- **Help:** user guide, licence agreement, privacy policy and version information.

## iPhone app (Bluetooth)

iOS cannot act as a Bluetooth mouse, so the PC must run PointLoose to receive commands.

1. On the PC, turn Bluetooth on (Bluetooth 4.0 / LE). Do **not** pair the iPhone in Windows settings.
2. Note the 8-character pairing code in the PointLoose window.
3. Install `PointLoose.ipa` (unsigned; use a sideloading tool such as AltStore or Sideloadly).
4. Open the app, allow Bluetooth, and enter the pairing code in **Settings**. The status turns green when connected.

Keep the app on screen; iOS stops Bluetooth advertising in the background.

## Security

Anyone with your link or pairing code can control the PC while PointLoose runs.
Keep them private and press **New link** / **New code** if they may have leaked.
Use trusted networks only. Details and how to report a vulnerability: [SECURITY.md](SECURITY.md).

## Troubleshooting

| Problem | Fix |
|---|---|
| Phone cannot open the link | Same Wi-Fi? Firewall allowed on Private networks? Guest networks often block device-to-device traffic. |
| Several addresses in **PC address** | Try the others; VPNs and virtual adapters can confuse the first one. |
| Laggy pointer | Use 5 GHz Wi-Fi and stay near the router. |
| Antivirus warning | PyInstaller apps are sometimes flagged by mistake. Build it yourself from source if unsure. |
| "Phone sent a wrong code" | Re-enter the pairing code in the iPhone app (letters and digits only). |

Error details are written to `%APPDATA%\PointLoose\pointloose.log`.

## Building from source

**Windows, local:** install Python 3.9+ (tick *Add python.exe to PATH*) and run `build_exe.bat`. The result is `dist\PointLoose.exe`.

**Run without building:** `pip install -r requirements.txt` then `python pointloose_app.py`.

**GitHub Actions:**
- **Release:** push a tag like `v1.0.0` to build `PointLoose.exe` and `PointLoose.ipa` and publish both on one Release (notes come from `CHANGELOG.md`).
- *Build PointLoose.exe* / *Build PointLoose.ipa*: test builds from the Actions tab (downloadable artifacts, no Release).

### Project layout

| Path | Purpose |
|---|---|
| `pointloose_app.py` | Windows window, QR code, settings (becomes `PointLoose.exe`) |
| `pointloose_wifi_plus.py` | Engine: web server, phone page, input, clipboard, laser overlay |
| `pointloose_ble.py` | Bluetooth LE receiver for the iPhone app |
| `pointloose_version.py` | Product name and version |
| `ios/` | iPhone app (SwiftUI, XcodeGen `project.yml`) |
| `.github/workflows/` | Automated Windows and iOS builds |

## Legal

- Source code: [MIT License](LICENSE)
- Ready-to-run builds: [End User License Agreement](EULA.md)
- [Privacy Policy](PRIVACY.md) · [Security Policy](SECURITY.md) · [Third-Party Notices](THIRD_PARTY_NOTICES.md)

PointLoose is an independent project, not affiliated with Microsoft, Apple or any other trackpad or remote-control product.
