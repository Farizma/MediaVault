// Hue / saturation wheel with a brightness slider. Drag on the wheel (or click) to pick; `color` follows.
// Set `color` from outside to move the knob there.
import QtQuick
import QtQuick.Controls

Item {
    id: root
    property color color: "#007AFF"
    signal picked(color c)                  // while dragging and on release
    property real hue: 0.6
    property real sat: 1
    property real val: 1
    property bool _internal: false
    implicitWidth: 196
    implicitHeight: wheel.height + 34

    onColorChanged: if (!_internal) { hue = Math.max(0, color.hsvHue); sat = color.hsvSaturation; val = color.hsvValue; wheel.requestPaint() }
    function emitColor() {
        _internal = true
        color = Qt.hsva(hue, sat, val, 1)
        _internal = false
        picked(color)
    }

    Canvas {
        id: wheel
        width: root.width; height: width
        property real r: width / 2 - 2
        onPaint: {
            var c = getContext("2d"), cx = width / 2, cy = height / 2
            c.reset()
            // hue around the rim: conical gradient (Qt's angle is counter-clockwise from 3 o'clock, like Qt.hsva)
            var g = c.createConicalGradient(cx, cy, 0)
            for (var i = 0; i <= 12; i++) g.addColorStop(i / 12, Qt.hsva((i % 12) / 12, 1, root.val, 1))
            c.fillStyle = g
            c.beginPath(); c.arc(cx, cy, r, 0, Math.PI * 2); c.fill()
            // saturation: white in the middle fading out to the rim
            var w = c.createRadialGradient(cx, cy, 0, cx, cy, r)
            w.addColorStop(0, Qt.hsva(0, 0, root.val, 1))
            w.addColorStop(1, Qt.hsva(0, 0, root.val, 0))
            c.fillStyle = w
            c.beginPath(); c.arc(cx, cy, r, 0, Math.PI * 2); c.fill()
        }
        function pickAt(x, y) {
            var dx = x - width / 2, dy = y - height / 2
            var a = Math.atan2(-dy, dx)                       // screen y points down
            root.hue = ((a < 0 ? a + 2 * Math.PI : a) / (2 * Math.PI)) % 1
            root.sat = Math.min(1, Math.sqrt(dx * dx + dy * dy) / r)
            root.emitColor()
        }
        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.CrossCursor
            preventStealing: true
            onPressed: (m) => wheel.pickAt(m.x, m.y)
            onPositionChanged: (m) => wheel.pickAt(m.x, m.y)
        }
        // knob
        Rectangle {
            readonly property real a: root.hue * 2 * Math.PI
            width: 18; height: 18; radius: 9
            x: wheel.width / 2 + Math.cos(a) * root.sat * wheel.r - width / 2
            y: wheel.height / 2 - Math.sin(a) * root.sat * wheel.r - height / 2
            color: root.color
            border.color: "#FFFFFF"; border.width: 3
            Rectangle { anchors.fill: parent; anchors.margins: -1; radius: width / 2; color: "transparent"; border.color: "#66000000" }
        }
    }
    // brightness
    Slider {
        id: bright
        anchors { left: parent.left; right: parent.right; top: wheel.bottom; topMargin: 8 }
        from: 0.25; to: 1; value: root.val
        onMoved: { root.val = value; wheel.requestPaint(); root.emitColor() }
        background: Rectangle {
            x: bright.leftPadding; y: bright.topPadding + bright.availableHeight / 2 - height / 2
            width: bright.availableWidth; height: 8; radius: 4
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0; color: Qt.hsva(root.hue, root.sat, 0.25, 1) }
                GradientStop { position: 1; color: Qt.hsva(root.hue, root.sat, 1, 1) }
            }
        }
        handle: Rectangle {
            x: bright.leftPadding + bright.visualPosition * (bright.availableWidth - width)
            y: bright.topPadding + bright.availableHeight / 2 - height / 2
            width: 16; height: 16; radius: 8; color: "#FFFFFF"; border.color: "#66000000"
        }
    }
}
