// Button. Responds on press (dips to 97 %), 120 ms, ease-out. No animation on keyboard use.
// primary = white on black (Watch Now / Play), otherwise white/10 glass with a white/15 edge.
import QtQuick
import QtQuick.Controls

Rectangle {
    id: root
    property string label: ""
    property string glyph: ""                 // optional leading symbol, e.g. "▶"
    property string iconKind: ""              // optional line icon from HudIcon (airplay, snapshot, ...), instead of a glyph
    property color glyphColor: primary ? "#000000" : Theme.text
    property bool primary: false
    property bool small: false                // header / toolbar size
    property bool active: false               // toggled on (Insights, an open HUD picker)
    property string tip: ""                   // hover help (shown after a moment)
    signal clicked()

    implicitWidth: row.implicitWidth + (small ? 26 : 40)
    implicitHeight: small ? 32 : 42
    radius: small ? 10 : 12
    color: primary ? (area.containsMouse ? "#E6FFFFFF" : "#FFFFFF")
                   : Qt.rgba(1, 1, 1, (active ? 0.12 : 0) + (area.containsMouse ? 0.20 : 0.10))
    border.color: primary ? "transparent" : Theme.lineStrong
    scale: area.pressed ? 0.97 : 1
    Behavior on scale { NumberAnimation { duration: 120 * Theme.motion; easing.type: Easing.OutCubic } }
    Behavior on color { ColorAnimation { duration: 120 * Theme.motion } }

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 7
        HudIcon {
            visible: root.iconKind !== ""
            anchors.verticalCenter: parent.verticalCenter
            kind: root.iconKind
            color: root.glyphColor
            width: root.small ? 15 : 18; height: width
        }
        Text {
            visible: root.glyph !== "" && root.iconKind === ""
            anchors.verticalCenter: parent.verticalCenter
            text: root.glyph
            color: root.glyphColor
            font.pixelSize: root.small ? 12 : 13
        }
        Text {
            visible: root.label !== ""
            anchors.verticalCenter: parent.verticalCenter
            text: root.label
            color: root.primary ? "#000000" : Theme.text
            font.pixelSize: root.small ? 12 : 14
            font.weight: root.primary ? Font.ExtraBold : Font.DemiBold
        }
    }
    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
    Tip { visible: root.tip !== "" && area.containsMouse && !area.pressed; text: root.tip }
}
