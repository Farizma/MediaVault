import QtQuick
import QtQuick.Controls

TextField {
    color: Theme.text
    placeholderTextColor: Theme.faint
    selectionColor: Theme.blue
    passwordCharacter: "\u2022"
    font.pixelSize: 13
    onTextChanged: if (!activeFocus) cursorPosition = 0      // long values show their start, not their end
    leftPadding: 12
    rightPadding: 12
    topPadding: 9
    bottomPadding: 9
    background: Rectangle {
        radius: 10
        color: Theme.slate
        border.color: parent.activeFocus ? Theme.blue : Theme.line
    }
}
