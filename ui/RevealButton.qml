// Player bar button: a large icon at rest. On hover the box widens, the icon slides left and shrinks,
// and the label fades in beside it. Every part animates from where it is, so quick hovers never jump.
import QtQuick

Rectangle {
    id: root
    property string iconKind: ""                // HudIcon kind
    property string label: ""
    property color iconColor: Theme.text
    property bool active: false
    property bool toggled: false              // an on/off switch that is on (Black Out): accent tint and ring
    property color onColor: Theme.green
    // Switching: the label fades out, "On" / "Off" fades in, then the label comes back. Opens the box while it plays,
    // so a keyboard shortcut shows it too.
    property bool flashing: false
    property bool ready: false
    Timer { running: true; interval: 1500; onTriggered: root.ready = true }    // the player's first state is not a switch
    onToggledChanged: if (ready) { flashing = true; flashTimer.restart() }
    Timer { id: flashTimer; interval: 1100; onTriggered: root.flashing = false }
    property string tip: ""
    signal clicked()

    readonly property bool open: area.containsMouse || flashing
    readonly property int pad: 12
    readonly property real restIcon: 24
    readonly property real openIcon: 18

    implicitHeight: 48
    implicitWidth: open ? pad + openIcon + 8 + label_.implicitWidth + pad + 2 : 52
    radius: 14
    clip: true
    color: Qt.rgba(1, 1, 1, (active ? 0.12 : 0) + (open ? 0.20 : 0.10))
    border.color: toggled ? onColor : Theme.lineStrong
    border.width: toggled ? 1.5 : 1
    scale: area.pressed ? 0.96 : 1
    Behavior on implicitWidth { NumberAnimation { duration: 260 * Theme.motion; easing.type: Easing.OutQuint } }
    Behavior on scale { NumberAnimation { duration: 120 * Theme.motion; easing.type: Easing.OutCubic } }
    Behavior on color { ColorAnimation { duration: 150 * Theme.motion } }

    Rectangle { anchors.fill: parent; radius: parent.radius; color: root.onColor; opacity: root.toggled ? 0.22 : 0
        Behavior on opacity { NumberAnimation { duration: 160 * Theme.motion } } }
    HudIcon {
        id: ico
        kind: root.iconKind
        color: root.toggled ? root.onColor : root.iconColor
        width: root.restIcon; height: root.restIcon
        anchors.verticalCenter: parent.verticalCenter
        // centred at rest; at the left edge (and shrunk to openIcon) when open
        x: root.open ? root.pad - (root.restIcon - root.openIcon) / 2 : (root.width - width) / 2
        scale: root.open ? root.openIcon / root.restIcon : 1
        Behavior on x { NumberAnimation { duration: 260 * Theme.motion; easing.type: Easing.OutQuint } }
        Behavior on scale { NumberAnimation { duration: 260 * Theme.motion; easing.type: Easing.OutQuint } }
    }
    Text {
        id: label_
        text: root.label
        color: Theme.text
        font.pixelSize: 14; font.weight: Font.DemiBold
        anchors.verticalCenter: parent.verticalCenter
        x: root.pad + root.openIcon + 8 + (root.open ? 0 : 10)
        opacity: root.open && !root.flashing ? 1 : 0
        Behavior on x { NumberAnimation { duration: 260 * Theme.motion; easing.type: Easing.OutQuint } }
        // fade in a beat after the box starts opening; fade out fast so it never spills while closing
        Behavior on opacity { NumberAnimation { duration: (root.open ? 220 : 90) * Theme.motion; easing.type: Easing.OutCubic } }
    }
    Text {          // "On" / "Off" while switching, in the label's place
        text: root.toggled ? "On" : "Off"
        color: root.toggled ? root.onColor : Theme.muted
        font: label_.font
        anchors.verticalCenter: parent.verticalCenter
        x: label_.x + (root.flashing ? 0 : 6)
        opacity: root.open && root.flashing ? 1 : 0
        Behavior on x { NumberAnimation { duration: 260 * Theme.motion; easing.type: Easing.OutQuint } }
        Behavior on opacity { NumberAnimation { duration: 180 * Theme.motion; easing.type: Easing.OutCubic } }
    }
    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
    Tip { visible: root.tip !== "" && area.containsMouse && !area.pressed; delay: 900; text: root.tip }
}
