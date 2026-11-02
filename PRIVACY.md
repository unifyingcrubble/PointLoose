# PointLoose Privacy Policy

_Last updated: 2 November 2026_

**Short version: PointLoose collects nothing. Everything stays on your PC and your
phone.**

## What we collect

Nothing. PointLoose has no accounts, no analytics, no advertising, no crash
reporting and no servers of ours. It never connects to the internet; the PC and
phone talk to each other directly over your local network or Bluetooth.

## What is stored on your devices

| Where | What | Why |
|---|---|---|
| PC: `%USERPROFILE%\.pointloose_token` | Secret part of the Wi-Fi link | So a saved shortcut keeps working |
| PC: `%USERPROFILE%\.pointloose_ble_code` | Bluetooth pairing code | So the iPhone app stays paired |
| PC: `%APPDATA%\PointLoose\settings.json` | Your app preferences and agreement acceptance | Remember choices between runs |
| PC: `%APPDATA%\PointLoose\pointloose.log` | Error details only (no keystrokes, no clipboard) | Troubleshooting; capped at 512 KB |
| Phone browser storage / iPhone app settings | Pointer speed, scroll, laser colour, pairing code | Remember your settings |

You can delete any of these at any time. Uninstalling the app and deleting these
files removes every trace of PointLoose.

## What passes between phone and PC

Touch movements, clicks, keys, text you type, and clipboard text when you press
**Paste on PC** or **Get PC clipboard**. This data is used only to control the PC
in that moment. It is not logged or saved.

## Permissions

- **Windows Firewall (private networks):** lets your phone reach the PC on your Wi-Fi.
- **Bluetooth (iPhone app):** sends your touches to the PC over Bluetooth LE.

## Children

PointLoose does not knowingly collect any data from anyone, including children.

## Changes

If this policy changes, the new version ships with the app and appears in this
file with a new date.

## Contact

Open an issue in the PointLoose repository.
