# Third-Party Notices

PointLoose builds on the following open-source software. Each component is
licensed by its own authors under the licence shown; the full licence texts are
available at the linked projects.

| Component | Used for | Licence |
|---|---|---|
| [Python](https://www.python.org/) runtime and standard library | Windows app | Python Software Foundation License 2.0 |
| [Tcl/Tk](https://www.tcl.tk/) (via tkinter) | Windows window and laser overlay | Tcl/Tk License (BSD-style) |
| [segno](https://github.com/heuer/segno) | QR code in the Windows window | BSD 3-Clause |
| [bleak](https://github.com/hbldh/bleak) | Bluetooth LE on Windows | MIT |
| [pywinrt](https://github.com/pywinrt/pywinrt) (`winrt-*` packages, pulled in by bleak) | Windows Bluetooth APIs | MIT |
| [PyInstaller](https://pyinstaller.org/) bootloader | Packaging `PointLoose.exe` | GPL 2.0 with the PyInstaller bootloader exception, which allows distributing the packaged app under its own licence |
| [XcodeGen](https://github.com/yonaskolb/XcodeGen) | Generating the iOS project at build time (not shipped) | MIT |

The iPhone app uses only Apple system frameworks (SwiftUI, CoreBluetooth, UIKit).
