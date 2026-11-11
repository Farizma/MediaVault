// A small count badge (updates waiting). Pops in when the count goes above zero and out when it is cleared.
import QtQuick

Rectangle {
    id: root
    property int count: 0
    readonly property bool on: count > 0
    implicitWidth: Math.max(16, label.implicitWidth + 9)
    implicitHeight: 16
    radius: 8
    color: Theme.red
    border.color: Theme.black; border.width: 1.5        // a ring of the page colour, so it reads on any button
    scale: on ? 1 : 0
    opacity: on ? 1 : 0
    visible: opacity > 0
    Behavior on scale { NumberAnimation { duration: 260 * Theme.motion; easing.type: Easing.OutBack; easing.overshoot: 1.6 } }
    Behavior on opacity { NumberAnimation { duration: 160 * Theme.motion } }
    Text { id: label; anchors.centerIn: parent; text: root.count > 9 ? "9+" : root.count; color: Theme.text
        font.pixelSize: 9; font.weight: Font.Black; font.family: Theme.mono }
}
