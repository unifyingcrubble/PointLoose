POINTLOOSE - use your phone as a wireless trackpad for a Windows PC
=================================================================

FOR EVERYONE (using PointLoose.exe)
--------------------------------
1. Double-click PointLoose.exe.
   - Windows may show a blue "Windows protected your PC" screen because the app
     is not code-signed. Click "More info", then "Run anyway".
   - When the Windows Firewall pop-up appears, tick "Private networks" and
     click "Allow access". (Without this the phone cannot connect.)
2. Make sure your phone is on the same Wi-Fi as the PC.
3. Scan the QR code in the PointLoose window with your phone's camera and open the link.
   (No app to install on the phone.) Tip: use "Add to Home Screen" for a shortcut.
4. Use your phone screen as a trackpad. Close the PointLoose window to stop.

PHONE CONTROLS
  1 finger        move the pointer          tap              left click
  2-finger tap    right click               3-finger tap     middle click
  2-finger drag   scroll (up/down/sideways) pinch            zoom
  3-finger swipe  up: Task view, down: Show desktop, left/right: switch desktop
  double-tap + hold   drag
  Tabs below the pad: Mouse buttons, Keys and shortcuts, Present (slides, laser pointer,
  timer, media keys), Settings (speed, natural scroll, vibration).

SAFETY
  Anyone who has your link can control your PC and read its clipboard.
  Don't share the QR code or link. Press "New link" in the window to replace it.
  Only use PointLoose on networks you trust.

TROUBLESHOOTING
  - Phone can't open the link: same Wi-Fi? Firewall allowed on Private networks?
    Guest Wi-Fi networks often block device-to-device traffic.
  - Several addresses in the "PC address" box: try the others (VPN and virtual
    adapters can confuse the first one).
  - Laggy: use 5 GHz Wi-Fi and stay near the router.
  - Antivirus complains about PointLoose.exe: it is a small Python program packaged with
    PyInstaller, and such files are sometimes flagged by mistake. If you built it
    yourself from this source, you can trust it; if not, ask the person who sent it.
  - Errors are logged to  %APPDATA%\PointLoose\pointloose.log

FOR THE PERSON BUILDING THE EXE
-------------------------------
Option A - on a Windows PC:
  Install Python 3.9+ from python.org (tick "Add python.exe to PATH"), then
  double-click build_exe.bat. The result is  dist\PointLoose.exe  (send that one file).

Option B - without installing anything (GitHub):
  Put these files in a GitHub repository, open the Actions tab, run "Build PointLoose.exe",
  and download the "PointLoose-windows" artifact. Pushing a tag like v1.0 also publishes
  PointLoose.exe as a Release your friends can download.

Files
  pointloose_app.py        window + QR code (this becomes PointLoose.exe)
  pointloose_wifi_plus.py  the engine (server, input, laser pointer)
  pointloose.ico           app icon
  build_exe.bat         one-click build
  requirements.txt      pyinstaller, segno
  .github/workflows/    optional automatic build on GitHub

You can also run it without building:  python pointloose_app.py   (needs: pip install segno)


BLUETOOTH + IPHONE APP (new)
============================
The iPhone app (ios/ folder) talks to the PC over Bluetooth LE instead of Wi-Fi.
The Wi-Fi/QR web version above still works as before.

Important: iOS cannot pose as a Bluetooth mouse. So the PC must run PointLoose.exe
(or "python pointloose_app.py") to receive the phone's Bluetooth messages.

PC setup
  1. Turn Bluetooth on (PC needs Bluetooth 4.0+ / LE). Do NOT pair the iPhone in Windows settings.
  2. Run PointLoose. The "Bluetooth (iPhone app)" box shows an 8-character pairing code.
  3. From source: pip install bleak segno   then   python pointloose_app.py
     Console only: python pointloose_ble.py

iPhone setup
  1. Build the IPA: put this folder in a GitHub repo, Actions tab, run "Build PointLoose.ipa",
     download PointLoose.ipa (artifact, or the Release it creates).
  2. The IPA is unsigned. Install it with a sideloading tool (AltStore, Sideloadly, ...).
  3. Open the app, allow Bluetooth, type the PC's pairing code in Settings.
  4. Status turns green: "Connected to PC". Use the pad like on the web version.

iPhone controls
  1 finger move, tap = left click, 2-finger tap = right click, 3-finger tap = middle click,
  2-finger drag = scroll, pinch = zoom, tap then touch-and-hold + drag = drag,
  Left/Middle/Right buttons, Keyboard (live typing), Keys (shortcuts, media keys).
  3-finger swipe: up = Task view, down = Show desktop, left/right = switch desktop.
  Laser button: red-dot pointer on the PC screen (colour and size in Settings). Finger moves the
  laser, clicks are off while it is on.
  Present: Previous/Next slide, Start (F5), From current, Black/White screen, End, laser, timer.
  Clipboard: send phone clipboard to PC, or fetch PC clipboard (text, up to a few thousand characters).
  Settings: pointer speed, scroll speed, natural scroll, haptics, laser colour/size.

Security
  Phone and PC prove they both know the pairing code (HMAC) before any command is accepted.
  The Bluetooth link itself is NOT encrypted, so someone close by could read what you type.
  Use it for trackpad work, not passwords. "New code" in the PC window replaces the code.

Troubleshooting
  - "Looking for your phone...": keep the iPhone app open on screen (iOS stops advertising in background).
  - "wrong code": retype the code in the iPhone app Settings (letters/numbers only).
  - Laggy: stay within a few metres. Bluetooth LE is slower than 5 GHz Wi-Fi.
  - PointLoose.exe has no Bluetooth: build it from source / run "python pointloose_app.py" (see above).

New files
  pointloose_ble.py                    PC Bluetooth receiver (uses "bleak")
  ios/                              iPhone app source (Swift, SwiftUI, XcodeGen project.yml)
  .github/workflows/build-ios-ipa.yml   builds the unsigned IPA on a GitHub Mac runner
