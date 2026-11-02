import SwiftUI
import UIKit

struct ContentView: View {
    @StateObject private var ble = BLEPeripheral()
    @AppStorage("pcCode") private var pcCode = ""
    @AppStorage("sensitivity") private var sensitivity = 1.4
    @AppStorage("scrollSpeed") private var scrollSpeed = 1.0
    @AppStorage("naturalScroll") private var naturalScroll = true
    @AppStorage("haptics") private var haptics = true
    @AppStorage("laserColor") private var laserColor = "#ff2020"
    @AppStorage("laserSize") private var laserSize = 16.0

    @State private var showKeys = false
    @State private var showPresent = false
    @State private var showSettings = false
    @State private var keyboardOn = false

    var body: some View {
        VStack(spacing: 10) {
            HStack(spacing: 8) {
                Image("Logo")
                    .resizable()
                    .frame(width: 26, height: 26)
                Circle().fill(statusColor).frame(width: 10, height: 10)
                VStack(alignment: .leading, spacing: 2) {
                    Text(ble.detail).font(.footnote).lineLimit(2)
                    if let notice = ble.notice {
                        Text(notice).font(.caption2).foregroundColor(.secondary)
                    }
                }
                Spacer()
            }

            if ble.laserOn {
                Text("Laser pointer ON: finger moves the laser, clicks are off")
                    .font(.caption)
                    .foregroundColor(.white)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 4)
                    .background(Capsule().fill(Color.red))
            }

            ZStack {
                TrackpadView(ble: ble, sensitivity: sensitivity, naturalScroll: naturalScroll,
                             haptics: haptics, scrollSpeed: scrollSpeed)
                    .clipShape(RoundedRectangle(cornerRadius: 18))
                KeyCatcher(active: $keyboardOn, ble: ble)
                    .frame(width: 1, height: 1)
                    .opacity(0.01)
                    .allowsHitTesting(false)
            }

            HStack(spacing: 10) {
                Button("Left") { ble.click("l") }
                    .buttonStyle(.borderedProminent)
                    .frame(maxWidth: .infinity)
                Button("Middle") { ble.click("m") }
                    .buttonStyle(.bordered)
                    .frame(maxWidth: .infinity)
                Button("Right") { ble.click("r") }
                    .buttonStyle(.borderedProminent)
                    .frame(maxWidth: .infinity)
            }
            .controlSize(.large)

            HStack(spacing: 0) {
                ToolButton(title: "Keyboard", icon: "keyboard", active: keyboardOn) {
                    keyboardOn.toggle()
                }
                ToolButton(title: "Keys", icon: "command", active: false) {
                    showKeys = true
                }
                ToolButton(title: "Present", icon: "play.rectangle", active: false) {
                    showPresent = true
                }
                ToolButton(title: "Laser", icon: "dot.radiowaves.left.and.right", active: ble.laserOn) {
                    ble.setLaser(!ble.laserOn, colorHex: laserColor, size: laserSize)
                }
                Menu {
                    Button("Send phone clipboard to PC") { ble.sendClipboardToPC() }
                    Button("Get PC clipboard") { ble.requestPCClipboard() }
                } label: {
                    ToolLabel(title: "Clipboard", icon: "doc.on.clipboard", active: false)
                }
                .frame(maxWidth: .infinity)
                ToolButton(title: "Settings", icon: "gearshape", active: false) {
                    showSettings = true
                }
            }
        }
        .padding()
        .onAppear {
            ble.setCode(pcCode)
            UIApplication.shared.isIdleTimerDisabled = true
            if pcCode.isEmpty { showSettings = true }
        }
        .onChange(of: pcCode) { newValue in
            ble.setCode(newValue)
        }
        .onChange(of: laserColor) { newValue in
            ble.updateLaserStyle(colorHex: newValue, size: laserSize)
        }
        .onChange(of: laserSize) { newValue in
            ble.updateLaserStyle(colorHex: laserColor, size: newValue)
        }
        .sheet(isPresented: $showKeys) {
            KeysSheet(ble: ble)
        }
        .sheet(isPresented: $showPresent) {
            PresentSheet(ble: ble, laserColor: laserColor, laserSize: laserSize)
        }
        .sheet(isPresented: $showSettings) {
            SettingsSheet(code: $pcCode, sensitivity: $sensitivity, scrollSpeed: $scrollSpeed,
                          naturalScroll: $naturalScroll, haptics: $haptics,
                          laserColor: $laserColor, laserSize: $laserSize)
        }
    }

    private var statusColor: Color {
        switch ble.phase {
        case .live: return .green
        case .verifying: return .orange
        case .advertising, .starting: return .blue
        default: return .red
        }
    }
}

struct ToolLabel: View {
    let title: String
    let icon: String
    let active: Bool

    var body: some View {
        VStack(spacing: 3) {
            Image(systemName: icon).font(.title3)
            Text(title).font(.caption2)
        }
        .foregroundColor(active ? .red : .accentColor)
        .frame(maxWidth: .infinity)
    }
}

struct ToolButton: View {
    let title: String
    let icon: String
    let active: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            ToolLabel(title: title, icon: icon, active: active)
        }
        .frame(maxWidth: .infinity)
    }
}

// MARK: - Keyboard capture

final class KeyCatcherView: UIView, UIKeyInput {
    var onText: ((String) -> Void)?
    var onBackspace: (() -> Void)?

    var autocorrectionType: UITextAutocorrectionType = .no
    var autocapitalizationType: UITextAutocapitalizationType = .none
    var spellCheckingType: UITextSpellCheckingType = .no

    override var canBecomeFirstResponder: Bool { true }
    var hasText: Bool { true }

    func insertText(_ text: String) {
        onText?(text)
    }

    func deleteBackward() {
        onBackspace?()
    }
}

struct KeyCatcher: UIViewRepresentable {
    @Binding var active: Bool
    let ble: BLEPeripheral

    func makeUIView(context: Context) -> KeyCatcherView {
        let view = KeyCatcherView()
        view.onText = { text in
            if text == "\n" {
                ble.hotkey("enter")
            } else {
                ble.typeText(text)
            }
        }
        view.onBackspace = {
            ble.hotkey("backspace")
        }
        return view
    }

    func updateUIView(_ view: KeyCatcherView, context: Context) {
        let wantActive = active
        DispatchQueue.main.async {
            if wantActive {
                if !view.isFirstResponder { _ = view.becomeFirstResponder() }
            } else if view.isFirstResponder {
                _ = view.resignFirstResponder()
            }
        }
    }
}

// MARK: - Sheets

struct KeysSheet: View {
    let ble: BLEPeripheral
    @Environment(\.dismiss) private var dismiss

    private let keys: [(String, String)] = [
        ("Esc", "esc"), ("Tab", "tab"), ("Enter", "enter"), ("Backspace", "backspace"),
        ("Delete", "delete"), ("Space", "space"),
        ("Left", "left"), ("Up", "up"), ("Down", "down"), ("Right", "right"),
        ("Home", "home"), ("End", "end"), ("Page Up", "pageup"), ("Page Down", "pagedown"),
        ("Alt+Tab", "alt+tab"), ("Task view", "win+tab"), ("Show desktop", "win+d"),
        ("Desktop left", "ctrl+win+left"), ("Desktop right", "ctrl+win+right"),
        ("Copy", "ctrl+c"), ("Paste", "ctrl+v"), ("Cut", "ctrl+x"),
        ("Undo", "ctrl+z"), ("Redo", "ctrl+y"), ("Select all", "ctrl+a"), ("Save", "ctrl+s"),
        ("F5", "f5"), ("F11", "f11"),
        ("Vol +", "volup"), ("Vol -", "voldown"), ("Mute", "mute"),
        ("Play/Pause", "playpause"), ("Prev track", "prevtrack"), ("Next track", "nexttrack")
    ]

    var body: some View {
        NavigationView {
            ScrollView {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 100), spacing: 10)], spacing: 10) {
                    ForEach(keys, id: \.0) { item in
                        Button(item.0) { ble.hotkey(item.1) }
                            .buttonStyle(.bordered)
                            .frame(maxWidth: .infinity)
                    }
                }
                .padding()
            }
            .navigationTitle("Keys")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }
}

struct SettingsSheet: View {
    @Binding var code: String
    @Binding var sensitivity: Double
    @Binding var scrollSpeed: Double
    @Binding var naturalScroll: Bool
    @Binding var haptics: Bool
    @Binding var laserColor: String
    @Binding var laserSize: Double
    @Environment(\.dismiss) private var dismiss

    private let laserColors: [(String, String)] = [
        ("Red", "#ff2020"), ("Green", "#20ff40"), ("Blue", "#3080ff"), ("Yellow", "#ffd400")
    ]

    var body: some View {
        NavigationView {
            Form {
                Section(header: Text("PC pairing code"),
                        footer: Text("Shown in the PointLoose window on your PC, under Bluetooth.")) {
                    TextField("Example: K7M2QX9P", text: $code)
                        .textInputAutocapitalization(.characters)
                        .disableAutocorrection(true)
                }
                Section(header: Text("Pointer speed")) {
                    Slider(value: $sensitivity, in: 0.5...4.0)
                }
                Section(header: Text("Scroll speed")) {
                    Slider(value: $scrollSpeed, in: 0.4...3.0)
                }
                Section(header: Text("Laser pointer")) {
                    Picker("Color", selection: $laserColor) {
                        ForEach(laserColors, id: \.1) { item in
                            Text(item.0).tag(item.1)
                        }
                    }
                    .pickerStyle(.segmented)
                    Slider(value: $laserSize, in: 6...30, step: 2)
                }
                Section {
                    Toggle("Natural scrolling", isOn: $naturalScroll)
                    Toggle("Haptic feedback", isOn: $haptics)
                }
                Section(header: Text("Gestures")) {
                    Text("1 finger: move. Tap: left click. 2-finger tap: right click. 3-finger tap: middle click.")
                    Text("2-finger drag: scroll. Pinch: zoom. Tap, then hold and drag: drag.")
                    Text("3-finger swipe: up Task view, down Show desktop, left/right switch desktop.")
                }
                .font(.footnote)
            }
            .navigationTitle("Settings")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }
}

struct PresentSheet: View {
    @ObservedObject var ble: BLEPeripheral
    let laserColor: String
    let laserSize: Double
    @Environment(\.dismiss) private var dismiss

    @State private var elapsed = 0
    @State private var running = false
    private let ticker = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    var body: some View {
        NavigationView {
            VStack(spacing: 14) {
                HStack(spacing: 12) {
                    Button { ble.hotkey("left") } label: {
                        Label("Previous", systemImage: "chevron.left").frame(maxWidth: .infinity, minHeight: 70)
                    }
                    .buttonStyle(.bordered)
                    Button { ble.hotkey("right") } label: {
                        Label("Next", systemImage: "chevron.right").frame(maxWidth: .infinity, minHeight: 70)
                    }
                    .buttonStyle(.borderedProminent)
                }
                .font(.title3)

                LazyVGrid(columns: [GridItem(.adaptive(minimum: 110), spacing: 10)], spacing: 10) {
                    Button("Start (F5)") { ble.hotkey("f5") }
                    Button("From current") { ble.hotkey("shift+f5") }
                    Button("Black screen") { ble.hotkey("b") }
                    Button("White screen") { ble.hotkey("w") }
                    Button("End (Esc)") { ble.hotkey("esc") }
                    Button("Play/Pause") { ble.hotkey("playpause") }
                    Button("Vol -") { ble.hotkey("voldown") }
                    Button("Vol +") { ble.hotkey("volup") }
                }
                .buttonStyle(.bordered)

                Button {
                    ble.setLaser(!ble.laserOn, colorHex: laserColor, size: laserSize)
                } label: {
                    Label(ble.laserOn ? "Laser pointer: ON" : "Laser pointer: OFF",
                          systemImage: "dot.radiowaves.left.and.right")
                        .frame(maxWidth: .infinity, minHeight: 44)
                }
                .buttonStyle(.borderedProminent)
                .tint(ble.laserOn ? .red : .gray)

                VStack(spacing: 8) {
                    Text(timeText)
                        .font(.system(size: 44, weight: .semibold, design: .monospaced))
                    HStack(spacing: 12) {
                        Button(running ? "Pause" : "Start timer") { running.toggle() }
                        Button("Reset") { running = false; elapsed = 0 }
                    }
                    .buttonStyle(.bordered)
                }
                .padding(.top, 6)

                Spacer()
            }
            .padding()
            .onReceive(ticker) { _ in
                if running { elapsed += 1 }
            }
            .navigationTitle("Present")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }

    private var timeText: String {
        let h = elapsed / 3600
        let m = (elapsed % 3600) / 60
        let s = elapsed % 60
        return h > 0 ? String(format: "%d:%02d:%02d", h, m, s) : String(format: "%02d:%02d", m, s)
    }
}
