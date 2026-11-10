// Hover help in the app's style: a small dark label above its item that rises in.
import QtQuick
import QtQuick.Controls

ToolTip {
    id: tip
    delay: 650
    padding: 8
    y: -implicitHeight - 8
    x: parent ? (parent.width - implicitWidth) / 2 : 0
    enter: Transition { ParallelAnimation {
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 140 * Theme.motion }
        NumberAnimation { property: "y"; from: -tip.implicitHeight - 2; to: -tip.implicitHeight - 8; duration: 180 * Theme.motion; easing.type: Easing.OutCubic } } }
    exit: Transition { NumberAnimation { property: "opacity"; to: 0; duration: 100 * Theme.motion } }
    contentItem: Text { text: tip.text; color: "#FFFFFF"; font.pixelSize: 11; font.weight: Font.Medium }
    background: Rectangle { radius: 7; color: "#F21C1C1E"; border.color: "#33FFFFFF" }
}
