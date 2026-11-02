# Changelog

All notable changes to PointLoose are listed here. Versions follow
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-11-02

First release under the PointLoose name.

### Added
- **Pause control** in the PC window: phones stay connected but their input is
  ignored; the phone page shows a paused state.
- **Settings menu:** Start with Windows, Open log folder.
- **Help menu:** user guide, license agreement, privacy policy, security policy,
  open-source license, third-party notices and an About box, all readable offline.
- First-launch license agreement, asked again on each major version.
- Window status shows how many phones are connected.
- Version shown in the PC window, on the phone page and in the iPhone app's new
  About section; `PointLoose.exe` carries name, version and copyright in its file
  properties.
- MIT licence, End User License Agreement, Privacy Policy, Security Policy,
  third-party notices and a Markdown README.

### Security
- Wi-Fi link secret raised from 64 to 128 bits. Links from earlier builds stop
  working; scan the new QR code once.
- An address that sends 10 wrong links within a minute is blocked for 5 minutes.
- Phone page served with a strict Content Security Policy, anti-framing and
  no-referrer headers.
- **New link** / **New code** now disconnect phones still using the old secret.

### Changed
- Log file is capped at 512 KB (one previous log is kept).
- Builds install dependencies from `requirements.txt`.
