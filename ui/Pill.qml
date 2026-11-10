import QtQuick

Rectangle {
    id: root
    property string label: ""
    property bool selected: true
    property color accent: Theme.green
    signal clicked()

    implicitWidth: caption.implicitWidth + 24
    implicitHeight: 28
    radius: height / 2
    color: selected ? accent : Theme.fill
    border.color: selected ? "transparent" : Theme.line
    Behavior on color { ColorAnimation { duration: 150 * Theme.motion } }
    Text {
        id: caption
        anchors.centerIn: parent
        text: root.label
        color: root.selected ? (Qt.color(root.accent).hslLightness > 0.6 ? "#000000" : "#FFFFFF") : Theme.faint
        font.pixelSize: 12
        font.weight: Font.Bold
    }
    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
}
