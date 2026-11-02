import Foundation
import UIKit
import CoreBluetooth
import CryptoKit

/// Advertises the PointLoose BLE service and streams trackpad commands to the PC.
///
/// The phone is the BLE peripheral, the PC is the central. Wire format: UTF-8 text
/// commands, one per line ("m,dx,dy\n", "c,l\n", "h,ctrl+c\n" ...), split into
/// notification-sized chunks. Before any command is sent, phone and PC prove to each
/// other that they know the shared pairing code (HMAC-SHA256 challenge/response).
final class BLEPeripheral: NSObject, ObservableObject, CBPeripheralManagerDelegate {

    enum Phase {
        case starting, bluetoothOff, unauthorized, unsupported
        case advertising, verifying, live, rejected
    }

    static let serviceUUID = CBUUID(string: "18D37D68-BDC2-406B-B2B8-42BB1FA94562")
    static let txUUID = CBUUID(string: "4AB237D1-7713-47EB-99BA-5CB1ADDBD29A")   // phone -> PC (notify)
    static let rxUUID = CBUUID(string: "AB423FBC-F230-44E1-BE31-18D4FD25B347")   // PC -> phone (write)

    @Published private(set) var phase: Phase = .starting
    @Published private(set) var detail: String = "Starting Bluetooth..."

    @Published private(set) var laserOn = false
    @Published private(set) var notice: String?

    var isLive: Bool { phase == .live }

    private var manager: CBPeripheralManager!
    private var txChar: CBMutableCharacteristic?
    private var rxChar: CBMutableCharacteristic?
    private var central: CBCentral?
    private var serviceAdded = false

    private var code = ""
    private var myNonce = ""
    private var rxBuffer = Data()
    private var outQueue: [Data] = []
    private var heartbeat: Timer?

    // Motion is accumulated and sent at most about 60 times per second.
    private var pendingDX = 0.0
    private var pendingDY = 0.0
    private var pendingScroll = 0.0
    private var pendingHScroll = 0.0
    private var pendingZoom = 0.0
    private var lastFlush = Date.distantPast

    override init() {
        super.init()
        manager = CBPeripheralManager(delegate: self, queue: .main)
    }

    // MARK: - Pairing code

    func setCode(_ raw: String) {
        code = String(raw.uppercased().filter { $0.isLetter || $0.isNumber })
    }

    private func mac(_ message: String) -> String {
        let key = SymmetricKey(data: Data(code.utf8))
        let tag = HMAC<SHA256>.authenticationCode(for: Data(message.utf8), using: key)
        return tag.map { String(format: "%02x", $0) }.joined()
    }

    private func randomHex() -> String {
        return (0..<8).map { _ in String(format: "%02x", UInt8.random(in: 0...255)) }.joined()
    }

    // MARK: - Commands (called by the UI)

    func move(_ dx: Double, _ dy: Double) {
        guard isLive else { return }
        pendingDX += dx
        pendingDY += dy
        flushPending(force: false)
    }

    func scroll(_ amount: Double) {
        guard isLive else { return }
        pendingScroll += amount
        flushPending(force: false)
    }

    func hscroll(_ amount: Double) {
        guard isLive else { return }
        pendingHScroll += amount
        flushPending(force: false)
    }

    func zoom(_ amount: Double) {
        guard isLive else { return }
        pendingZoom += amount
        flushPending(force: false)
    }

    func click(_ button: String) {
        guard isLive else { return }
        flushPending(force: true)
        send("c,\(button)\n")
    }

    func dragDown() {
        guard isLive else { return }
        flushPending(force: true)
        send("d\n")
    }

    func dragUp() {
        guard isLive else { return }
        flushPending(force: true)
        send("u\n")
    }

    func hotkey(_ spec: String) {
        guard isLive else { return }
        flushPending(force: true)
        send("h,\(spec)\n")
    }

    func typeText(_ text: String) {
        guard isLive, !text.isEmpty else { return }
        guard let encoded = text.addingPercentEncoding(withAllowedCharacters: .alphanumerics) else { return }
        flushPending(force: true)
        send("t,\(encoded)\n")
    }

    // Laser pointer (drawn on the PC screen; while on, finger moves steer the laser, clicks are off).
    func setLaser(_ on: Bool, colorHex: String, size: Double) {
        guard isLive else { return }
        flushPending(force: true)
        if on {
            send("lc,\(colorHex)\n")
            send(String(format: "ls,%d\n", Int(size)))
        }
        send("L,\(on ? 1 : 0)\n")
        laserOn = on
    }

    func updateLaserStyle(colorHex: String, size: Double) {
        guard isLive, laserOn else { return }
        send("lc,\(colorHex)\n")
        send(String(format: "ls,%d\n", Int(size)))
    }

    // Clipboard bridge.
    func sendClipboardToPC() {
        guard isLive else { return }
        guard let text = UIPasteboard.general.string, !text.isEmpty else {
            showNotice("Phone clipboard is empty")
            return
        }
        let limited = String(text.prefix(3000))
        guard let encoded = limited.addingPercentEncoding(withAllowedCharacters: .alphanumerics) else { return }
        flushPending(force: true)
        send("cp,\(encoded)\n")
        showNotice("Sent \(limited.count) characters to PC clipboard")
    }

    func requestPCClipboard() {
        guard isLive else { return }
        flushPending(force: true)
        send("cg\n")
        showNotice("Asking PC for its clipboard...")
    }

    private func showNotice(_ text: String) {
        notice = text
        DispatchQueue.main.asyncAfter(deadline: .now() + 3) { [weak self] in
            if self?.notice == text { self?.notice = nil }
        }
    }

    func flushPending(force: Bool = true) {
        let now = Date()
        if !force {
            if now.timeIntervalSince(lastFlush) < 0.016 { return }
            if outQueue.count > 24 { return }          // link is busy: keep accumulating
        }
        lastFlush = now
        if abs(pendingDX) >= 0.05 || abs(pendingDY) >= 0.05 {
            send(String(format: "m,%.2f,%.2f\n", pendingDX, pendingDY))
            pendingDX = 0
            pendingDY = 0
        }
        if abs(pendingScroll) >= 0.01 {
            send(String(format: "s,%.3f\n", pendingScroll))
            pendingScroll = 0
        }
        if abs(pendingHScroll) >= 0.01 {
            send(String(format: "x,%.3f\n", pendingHScroll))
            pendingHScroll = 0
        }
        if abs(pendingZoom) >= 0.01 {
            send(String(format: "z,%.3f\n", pendingZoom))
            pendingZoom = 0
        }
    }

    // MARK: - Sending

    private func send(_ text: String) {
        guard central != nil else { return }
        let data = Data(text.utf8)
        let size = max(20, central?.maximumUpdateValueLength ?? 20)
        var start = 0
        while start < data.count {
            let end = min(start + size, data.count)
            outQueue.append(data.subdata(in: start..<end))
            start = end
        }
        pump()
    }

    private func pump() {
        guard let tx = txChar, let target = central else { return }
        while let first = outQueue.first {
            if manager.updateValue(first, for: tx, onSubscribedCentrals: [target]) {
                outQueue.removeFirst()
            } else {
                break
            }
        }
    }

    func peripheralManagerIsReady(toUpdateSubscribers peripheral: CBPeripheralManager) {
        pump()
    }

    // MARK: - Session handling

    private func resetSession() {
        heartbeat?.invalidate()
        heartbeat = nil
        rxBuffer.removeAll()
        outQueue.removeAll()
        myNonce = ""
        laserOn = false
        pendingDX = 0
        pendingDY = 0
        pendingScroll = 0
        pendingHScroll = 0
        pendingZoom = 0
    }

    private func setPhase(_ newPhase: Phase, _ text: String) {
        phase = newPhase
        detail = text
    }

    private func goLive() {
        setPhase(.live, "Connected to PC")
        heartbeat?.invalidate()
        let timer = Timer(timeInterval: 4, repeats: true) { [weak self] _ in
            self?.send("p\n")
        }
        RunLoop.main.add(timer, forMode: .common)
        heartbeat = timer
    }

    private func receive(_ data: Data) {
        rxBuffer.append(data)
        if rxBuffer.count > 32768 {
            rxBuffer.removeAll()
            return
        }
        while let newline = rxBuffer.firstIndex(of: 0x0A) {
            let lineData = rxBuffer[rxBuffer.startIndex..<newline]
            let line = String(decoding: lineData, as: UTF8.self)
            rxBuffer.removeSubrange(rxBuffer.startIndex...newline)
            handle(line)
        }
    }

    private func handle(_ line: String) {
        let parts = line.split(separator: ",", omittingEmptySubsequences: false).map { String($0) }
        guard let cmd = parts.first else { return }
        switch cmd {
        case "n":
            guard parts.count == 2 else { return }
            guard !code.isEmpty else {
                setPhase(.rejected, "Enter the PC pairing code in Settings.")
                return
            }
            myNonce = randomHex()
            send("a,\(mac("P" + parts[1])),\(myNonce)\n")
        case "v":
            guard parts.count == 2, !myNonce.isEmpty else { return }
            if parts[1] == mac("C" + myNonce) {
                goLive()
            } else {
                setPhase(.rejected, "This PC does not know your code. Not connected.")
            }
        case "c":
            guard parts.count == 2, isLive else { return }
            let text = parts[1].removingPercentEncoding ?? ""
            UIPasteboard.general.string = text
            showNotice(text.isEmpty ? "PC clipboard is empty" : "Copied \(text.count) characters from PC")
        case "x":
            setPhase(.rejected, "PC rejected the code. Check it in Settings.")
        default:
            break
        }
    }

    // MARK: - CBPeripheralManagerDelegate

    func peripheralManagerDidUpdateState(_ peripheral: CBPeripheralManager) {
        switch peripheral.state {
        case .poweredOn:
            setupService()
        case .poweredOff:
            resetSession()
            setPhase(.bluetoothOff, "Bluetooth is off. Turn it on in Settings.")
        case .unauthorized:
            setPhase(.unauthorized, "Bluetooth permission denied. Allow it in Settings > PointLoose.")
        case .unsupported:
            setPhase(.unsupported, "This device does not support Bluetooth LE.")
        default:
            break
        }
    }

    private func setupService() {
        if serviceAdded {
            startAdvertising()
            return
        }
        let tx = CBMutableCharacteristic(type: Self.txUUID, properties: [.notify], value: nil, permissions: [.readable])
        let rx = CBMutableCharacteristic(type: Self.rxUUID, properties: [.write], value: nil, permissions: [.writeable])
        let service = CBMutableService(type: Self.serviceUUID, primary: true)
        service.characteristics = [tx, rx]
        txChar = tx
        rxChar = rx
        manager.add(service)
    }

    func peripheralManager(_ peripheral: CBPeripheralManager, didAdd service: CBService, error: Error?) {
        if let error = error {
            setPhase(.unsupported, "Bluetooth error: \(error.localizedDescription)")
            return
        }
        serviceAdded = true
        startAdvertising()
    }

    private func startAdvertising() {
        if !manager.isAdvertising {
            manager.startAdvertising([
                CBAdvertisementDataServiceUUIDsKey: [Self.serviceUUID],
                CBAdvertisementDataLocalNameKey: "PointLoose"
            ])
        }
        if central == nil && phase != .rejected {
            setPhase(.advertising, "Waiting for PC. Start PointLoose on your PC.")
        }
    }

    func peripheralManagerDidStartAdvertising(_ peripheral: CBPeripheralManager, error: Error?) {
        if let error = error {
            setPhase(.unsupported, "Advertising failed: \(error.localizedDescription)")
        }
    }

    func peripheralManager(_ peripheral: CBPeripheralManager, central: CBCentral, didSubscribeTo characteristic: CBCharacteristic) {
        guard characteristic.uuid == Self.txUUID else { return }
        resetSession()
        self.central = central
        setPhase(.verifying, "PC found. Checking pairing code...")
    }

    func peripheralManager(_ peripheral: CBPeripheralManager, central: CBCentral, didUnsubscribeFrom characteristic: CBCharacteristic) {
        guard characteristic.uuid == Self.txUUID else { return }
        self.central = nil
        resetSession()
        startAdvertising()
        if phase != .rejected {
            setPhase(.advertising, "Waiting for PC. Start PointLoose on your PC.")
        }
    }

    func peripheralManager(_ peripheral: CBPeripheralManager, didReceiveWrite requests: [CBATTRequest]) {
        for request in requests where request.characteristic.uuid == Self.rxUUID {
            if let value = request.value {
                receive(value)
            }
        }
        if let first = requests.first {
            peripheral.respond(to: first, withResult: .success)
        }
    }
}
