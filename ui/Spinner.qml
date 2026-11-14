// Loading: an arc that turns. Turning runs on the render thread (RotationAnimator), so it keeps moving while the app is
// busy. With reduced motion it stands still and breathes instead.
//   Spinner { running: busy; size: 18 }
import QtQuick

Item {
    id: root
    property bool running: true
    property real size: 18
    property color color: Theme.text
    implicitWidth: size; implicitHeight: size
    visible: running
    opacity: running ? 1 : 0

    Canvas {
        id: arc
        anchors.fill: parent
        antialiasing: true
        onPaint: {
            var c = getContext("2d"), r = width / 2, w = Math.max(2, width / 9)
            c.reset()
            c.lineWidth = w; c.lineCap = "round"
            c.strokeStyle = Qt.rgba(1, 1, 1, 0.14)
            c.beginPath(); c.arc(r, r, r - w / 2, 0, Math.PI * 2); c.stroke()      // the track
            c.strokeStyle = root.color
            c.beginPath(); c.arc(r, r, r - w / 2, -Math.PI / 2, Math.PI * 0.35); c.stroke()
        }
        onWidthChanged: requestPaint()
        RotationAnimator on rotation {
            from: 0; to: 360; duration: 800; loops: Animation.Infinite
            running: root.running && root.visible && Theme.motion > 0
        }
    }
    SequentialAnimation on opacity {      // reduced motion: no turning, a slow fade in and out
        running: root.running && root.visible && Theme.motion === 0
        loops: Animation.Infinite
        NumberAnimation { to: 0.35; duration: 700 }
        NumberAnimation { to: 1; duration: 700 }
    }
    onColorChanged: arc.requestPaint()
}
