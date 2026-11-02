import SwiftUI
import UIKit

/// Full-area touch pad. Gestures:
///   1 finger drag = move        tap = left click
///   2-finger tap = right click  3-finger tap = middle click
///   2-finger drag = scroll      pinch = zoom
///   tap, then touch and hold + drag = drag (hold the left button)
///   3-finger swipe = Task view / Show desktop / switch desktop
struct TrackpadView: UIViewRepresentable {
    let ble: BLEPeripheral
    let sensitivity: Double
    let naturalScroll: Bool
    let haptics: Bool
    let scrollSpeed: Double

    func makeCoordinator() -> Coordinator {
        Coordinator(ble: ble)
    }

    func makeUIView(context: Context) -> UIView {
        let view = UIView()
        view.backgroundColor = UIColor.secondarySystemBackground
        view.isMultipleTouchEnabled = true

        let hint = UILabel()
        hint.text = "Trackpad"
        hint.textColor = UIColor.tertiaryLabel
        hint.font = UIFont.preferredFont(forTextStyle: .title3)
        hint.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(hint)
        NSLayoutConstraint.activate([
            hint.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            hint.centerYAnchor.constraint(equalTo: view.centerYAnchor)
        ])

        context.coordinator.install(on: view)
        return view
    }

    func updateUIView(_ uiView: UIView, context: Context) {
        let c = context.coordinator
        c.sensitivity = sensitivity
        c.naturalScroll = naturalScroll
        c.haptics = haptics
        c.scrollSpeed = scrollSpeed
    }

    final class Coordinator: NSObject, UIGestureRecognizerDelegate {
        let ble: BLEPeripheral
        var sensitivity = 1.4
        var naturalScroll = true
        var haptics = true
        var scrollSpeed = 1.0

        private let impact = UIImpactFeedbackGenerator(style: .light)
        private var lastScale: CGFloat = 1
        private var dragActive = false
        private var dragEnded = Date.distantPast
        private var dragRecognizer: UILongPressGestureRecognizer?

        init(ble: BLEPeripheral) {
            self.ble = ble
        }

        func install(on view: UIView) {
            let pan1 = UIPanGestureRecognizer(target: self, action: #selector(onMove(_:)))
            pan1.minimumNumberOfTouches = 1
            pan1.maximumNumberOfTouches = 1

            let pan2 = UIPanGestureRecognizer(target: self, action: #selector(onScroll(_:)))
            pan2.minimumNumberOfTouches = 2
            pan2.maximumNumberOfTouches = 2

            let pinch = UIPinchGestureRecognizer(target: self, action: #selector(onPinch(_:)))

            let tap1 = UITapGestureRecognizer(target: self, action: #selector(onTap1(_:)))
            tap1.numberOfTouchesRequired = 1
            let tap2 = UITapGestureRecognizer(target: self, action: #selector(onTap2(_:)))
            tap2.numberOfTouchesRequired = 2
            let tap3 = UITapGestureRecognizer(target: self, action: #selector(onTap3(_:)))
            tap3.numberOfTouchesRequired = 3

            let drag = UILongPressGestureRecognizer(target: self, action: #selector(onDrag(_:)))
            drag.numberOfTapsRequired = 1
            drag.numberOfTouchesRequired = 1
            drag.minimumPressDuration = 0.12
            drag.allowableMovement = 10000
            dragRecognizer = drag

            // 3-finger swipes: up = Task view, down = Show desktop, left/right = switch desktop.
            for direction in [UISwipeGestureRecognizer.Direction.up, .down, .left, .right] {
                let swipe = UISwipeGestureRecognizer(target: self, action: #selector(onSwipe3(_:)))
                swipe.direction = direction
                swipe.numberOfTouchesRequired = 3
                swipe.delegate = self
                view.addGestureRecognizer(swipe)
            }

            for g in [pan1, pan2, pinch, tap1, tap2, tap3, drag] as [UIGestureRecognizer] {
                g.delegate = self
                view.addGestureRecognizer(g)
            }
        }

        func gestureRecognizer(_ gestureRecognizer: UIGestureRecognizer,
                               shouldRecognizeSimultaneouslyWith other: UIGestureRecognizer) -> Bool {
            // Only the hold-to-drag gesture runs together with others (it needs the 1-finger pan).
            return gestureRecognizer === dragRecognizer || other === dragRecognizer
        }

        private func tick() {
            if haptics { impact.impactOccurred() }
        }

        @objc func onMove(_ g: UIPanGestureRecognizer) {
            switch g.state {
            case .began, .changed:
                let t = g.translation(in: g.view)
                g.setTranslation(.zero, in: g.view)
                let v = g.velocity(in: g.view)
                let speed = Double(hypot(v.x, v.y))
                let gain = sensitivity * (1.0 + min(speed / 2500.0, 1.5))
                ble.move(Double(t.x) * gain, Double(t.y) * gain)
            case .ended, .cancelled, .failed:
                ble.flushPending(force: true)
            default:
                break
            }
        }

        @objc func onScroll(_ g: UIPanGestureRecognizer) {
            switch g.state {
            case .began, .changed:
                let t = g.translation(in: g.view)
                g.setTranslation(.zero, in: g.view)
                let dir: Double = naturalScroll ? 1 : -1
                ble.scroll(Double(t.y) / 24.0 * scrollSpeed * dir)
                ble.hscroll(Double(t.x) / 24.0 * scrollSpeed * -dir)
            case .ended, .cancelled, .failed:
                ble.flushPending(force: true)
            default:
                break
            }
        }

        @objc func onPinch(_ g: UIPinchGestureRecognizer) {
            switch g.state {
            case .began:
                lastScale = 1
            case .changed:
                let delta = g.scale - lastScale
                lastScale = g.scale
                ble.zoom(Double(delta) * 8.0)
            case .ended, .cancelled, .failed:
                ble.flushPending(force: true)
            default:
                break
            }
        }

        @objc func onTap1(_ g: UITapGestureRecognizer) {
            guard g.state == .ended else { return }
            // A touch-and-hold drag also ends with a tap event: ignore that one.
            if dragActive || Date().timeIntervalSince(dragEnded) < 0.2 { return }
            tick()
            ble.click("l")
        }

        @objc func onTap2(_ g: UITapGestureRecognizer) {
            guard g.state == .ended else { return }
            tick()
            ble.click("r")
        }

        @objc func onTap3(_ g: UITapGestureRecognizer) {
            guard g.state == .ended else { return }
            tick()
            ble.click("m")
        }

        @objc func onSwipe3(_ g: UISwipeGestureRecognizer) {
            guard g.state == .ended else { return }
            tick()
            switch g.direction {
            case .up: ble.hotkey("win+tab")
            case .down: ble.hotkey("win+d")
            case .left: ble.hotkey("ctrl+win+right")
            case .right: ble.hotkey("ctrl+win+left")
            default: break
            }
        }

        @objc func onDrag(_ g: UILongPressGestureRecognizer) {
            switch g.state {
            case .began:
                dragActive = true
                tick()
                ble.dragDown()
            case .ended, .cancelled, .failed:
                if dragActive {
                    dragActive = false
                    dragEnded = Date()
                    ble.dragUp()
                }
            default:
                break
            }
        }
    }
}
