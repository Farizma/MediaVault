// iOS-style switch with a wrapping label. Replaces the Basic-style Switch / CheckBox look.
import QtQuick
import QtQuick.Controls

Switch {
    id: control
    property string hint: ""                  // optional second line under the label
    spacing: 12
    padding: 0
    indicator: Rectangle {
        x: control.leftPadding
        anchors.verticalCenter: parent.verticalCenter
        implicitWidth: 40; implicitHeight: 24; radius: 12
        color: control.checked ? Theme.green : Qt.rgba(1, 1, 1, 0.16)
        Behavior on color { ColorAnimation { duration: 150 * Theme.motion } }
        Rectangle {
            width: 20; height: 20; radius: 10; y: 2
            x: control.checked ? parent.width - width - 2 : 2
            color: "#FFFFFF"
            Behavior on x { NumberAnimation { duration: 180 * Theme.motion; easing.type: Easing.OutCubic } }
        }
    }
    // implicit size comes from the texts' natural size; actual width wraps them (no binding loop)
    contentItem: Item {
        readonly property real pad: control.indicator.width + control.spacing
        implicitWidth: pad + Math.max(main.implicitWidth, sub.visible ? sub.implicitWidth : 0)
        implicitHeight: Math.max(control.indicator.height, main.height + (sub.visible ? sub.height + 2 : 0))
        Column {
            x: parent.pad
            width: parent.width - parent.pad
            anchors.verticalCenter: parent.verticalCenter
            spacing: 2
            Text {
                id: main
                width: parent.width
                text: control.text
                color: Theme.text
                font.pixelSize: 13
                font.weight: Font.Medium
                wrapMode: Text.Wrap
            }
            Text {
                id: sub
                visible: control.hint !== ""
                width: parent.width
                text: control.hint
                color: Theme.faint
                font.pixelSize: 11
                wrapMode: Text.Wrap
            }
        }
    }
}
