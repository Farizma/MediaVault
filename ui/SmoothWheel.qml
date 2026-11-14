// Mouse-wheel scrolling for a Flickable. The wheel moves a target; every frame the view closes part of the gap
// (an exponential glide), so a burst of notches, a free-spinning wheel or the small steps many Windows mice and
// touchpads send all blend into one steady motion instead of restarting an animation each time. Touchpads that
// report pixels scroll 1:1 with the fingers. Dragging the scroll bar or flicking takes over at once.
// Put it inside the Flickable: SmoothWheel { view: grid }
import QtQuick

WheelHandler {
    id: root
    required property Flickable view
    property real step: 220                 // pixels per wheel notch (120 units)
    signal scrolled()
    target: null
    acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad

    readonly property real top: view.originY - view.topMargin
    readonly property real bottom: view.originY + Math.max(0, view.contentHeight + view.bottomMargin - view.height)
    function clamp(y) { return Math.max(top, Math.min(bottom, y)) }

    property real goal: 0                   // where the glide is heading
    property real placed: 0                 // the last contentY the glide set: anything else moved the view
    readonly property bool gliding: frame.running

    property FrameAnimation frame: FrameAnimation {
        onTriggered: {
            var v = root.view
            if (Math.abs(v.contentY - root.placed) > 1 || v.dragging || v.flicking) { stop(); return }   // someone else is scrolling
            var gap = root.clamp(root.goal) - v.contentY
            if (Math.abs(gap) < 0.5) { v.contentY = root.clamp(root.goal); stop(); return }
            // ~90 % of the way in 130 ms, whatever the frame rate
            var y = v.contentY + gap * (1 - Math.exp(-Math.min(frameTime, 0.05) * 18))
            v.contentY = y
            root.placed = y
        }
    }

    onWheel: (ev) => {
        var v = view
        var d = ev.pixelDelta.y !== 0 ? ev.pixelDelta.y : ev.angleDelta.y / 120 * step
        if (d === 0) return
        var from = gliding ? goal : v.contentY
        var to = clamp(from - d)
        if (to === clamp(from) && !gliding) return              // already at that end
        if (ev.pixelDelta.y !== 0 || Theme.motion === 0) {     // touchpad pixels (or reduced motion): no glide
            frame.stop()
            v.contentY = to
        } else {
            if (!gliding) placed = v.contentY
            goal = to
            frame.start()
        }
        scrolled()
    }
}
