// One line of text. When it does not fit it ends in "…"; while `active` (hovered) it glides left to reveal the
// rest, rests, and glides back, again and again. With reduce motion on, the full text shows in a tooltip instead.
import QtQuick
import QtQuick.Controls

Item {
    id: root
    property alias text: label.text
    property alias color: label.color
    property alias font: label.font
    property bool active: false
    // natural width from TextMetrics: an eliding Text reports its clipped width, not the full one
    readonly property real natural: metrics.advanceWidth
    readonly property bool overflows: natural > width + 1
    readonly property bool scrolling: active && overflows && Theme.motion > 0
    implicitWidth: natural
    implicitHeight: label.implicitHeight
    clip: true

    TextMetrics { id: metrics; font: label.font; text: label.text }
    Text {
        id: label
        width: root.scrolling ? root.natural + 2 : root.width
        elide: root.scrolling ? Text.ElideNone : Text.ElideRight
    }
    SequentialAnimation {
        running: root.scrolling
        loops: Animation.Infinite
        PauseAnimation { duration: 600 }
        // ~45 px a second: readable, like the Apple TV app's long titles
        NumberAnimation { target: label; property: "x"; to: root.width - root.natural
            duration: Math.max(700, (root.natural - root.width) / 45 * 1000); easing.type: Easing.InOutSine }
        PauseAnimation { duration: 1400 }
        NumberAnimation { target: label; property: "x"; to: 0; duration: 500; easing.type: Easing.InOutCubic }
    }
    onScrollingChanged: if (!scrolling) label.x = 0
    Tip { visible: root.active && root.overflows && Theme.motion === 0; delay: 300; text: label.text }
}
