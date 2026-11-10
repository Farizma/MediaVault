import QtQuick
import QtQuick.Controls

TextArea {
    color: Theme.text
    placeholderTextColor: Theme.faint
    selectionColor: Theme.blue
    font.pixelSize: 13
    wrapMode: TextEdit.Wrap
    leftPadding: 12
    rightPadding: 12
    topPadding: 10
    bottomPadding: 10
    background: Rectangle {
        radius: 10
        color: Theme.slate
        border.color: parent.activeFocus ? Theme.blue : Theme.line
    }
}
