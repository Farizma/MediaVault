// A multi-line field of a fixed height that scrolls: the text can be as long as it needs to be.
import QtQuick
import QtQuick.Controls

ScrollView {
    id: root
    property alias text: field.text
    property alias placeholderText: field.placeholderText
    readonly property bool editing: field.activeFocus     // false again once you click away: save then
    clip: true
    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
    background: Rectangle {
        radius: 10
        color: Theme.slate
        border.color: field.activeFocus ? Theme.blue : Theme.line
    }
    TextArea {
        id: field
        color: Theme.text
        placeholderTextColor: Theme.faint
        selectionColor: Theme.blue
        font.pixelSize: 13
        wrapMode: TextEdit.Wrap
        leftPadding: 12
        rightPadding: 16
        topPadding: 10
        bottomPadding: 10
        background: null
    }
}
