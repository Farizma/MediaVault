// Mouse-wheel scrolling for a Flickable: a notch moves a fixed distance with a short ease-out, notches in a row add
// up (the glide keeps going instead of restarting from where it is), and touchpads scroll 1:1 with their fingers.
// Put it inside the Flickable: SmoothWheel { view: grid }
import QtQuick

WheelHandler {
    id: root
    required property Flickable view
    property real step: 220                 // pixels per wheel notch
    signal scrolled()
    target: null
    acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad

    readonly property real top: view.originY - view.topMargin
    readonly property real bottom: view.originY + Math.max(0, view.contentHeight + view.bottomMargin - view.height)

    property NumberAnimation glide: NumberAnimation {
        target: root.view; property: "contentY"
        duration: 280 * Math.max(Theme.motion, 0.01); easing.type: Easing.OutCubic
    }
    onWheel: (ev) => {
        var to
        if (ev.pixelDelta.y !== 0) {              // touchpad: follow the fingers exactly
            glide.stop()
            to = view.contentY - ev.pixelDelta.y
            view.contentY = Math.max(top, Math.min(bottom, to))
        } else {
            var from = glide.running ? glide.to : view.contentY
            to = Math.max(top, Math.min(bottom, from - ev.angleDelta.y / 120 * step))
            if (to === from) return
            glide.stop()
            glide.to = to
            glide.start()
        }
        ev.accepted = true
        scrolled()
    }
}
