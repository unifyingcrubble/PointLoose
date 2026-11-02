# Security Policy

## Supported versions

Only the latest release receives security fixes.

## How PointLoose protects your PC

- **Secret link (Wi-Fi):** every request must carry a random 128-bit token. Without
  it, the PC answers `403 Forbidden` and does nothing.
- **Guessing protection:** a network address that sends 10 wrong links within a
  minute is blocked for 5 minutes.
- **Pairing code (Bluetooth):** the phone and PC prove to each other that they know
  the 8-character code (HMAC-SHA256 challenge/response) before any command runs.
- **Pause switch:** **Pause control** in the PC window ignores every phone command
  until you resume.
- **Command allow-list:** only known mouse, key and clipboard commands are accepted;
  key names are checked against a fixed list and values are range-limited.
- **No stuck input:** a held mouse button is released when the phone disconnects.

## Known limitations

- The Wi-Fi link is plain HTTP inside your local network. Someone who can capture
  traffic on the same network could see what you type and the link itself.
- The Bluetooth link is not encrypted at the radio level. Someone nearby with the
  right equipment could read the commands.
- Anyone who has the link or code can control the PC while PointLoose is running.

So: use trusted networks, do not type passwords through PointLoose on shared
networks, and press **New link** / **New code** if a link may have leaked.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's **Report a vulnerability** button
(Security tab of the repository) to send a private report. Include the version,
steps to reproduce and the impact. We aim to reply within 7 days.
