// A multi-line field of a fixed height that scrolls: the text can be as long as it needs to be.
// resizable: a grip in the bottom-right corner drags its height (the width follows the layout); sizeKey: a setting
// that remembers the height you chose, e.g. Area { resizable: true; sizeKey: "synopsis_box_height" }
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ScrollView {
    id: root
    property alias text: field.text
    property alias placeholderText: field.placeholderText
    readonly property bool editing: field.activeFocus     // false again once you click away: save then
    property bool resizable: false
    property string sizeKey: ""
    property real minHeight: 72
    property real maxHeight: 640
    property real implicitDefault: 104       // where a double-click on the grip puts it back
    Component.onCompleted: {
        var h = sizeKey ? parseFloat(Backend.setting(sizeKey)) : NaN
        if (resizable && h > 0) Layout.preferredHeight = Math.max(minHeight, Math.min(maxHeight, h))
    }
    clip: true
    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
    // the wheel scrolls the page around this box, not the text, unless you are typing in it (then the text scrolls).
    // Its scroll bar always works.
    Binding { target: root.contentItem; property: "interactive"; value: root.editing }
    wheelEnabled: root.editing
    SmoothWheel { view: root.contentItem; step: 90; enabled: root.editing }
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

    // the grip: three short diagonal lines; drag it up or down
    Item {
        id: grip
        parent: root
        visible: root.resizable
        z: 10
        width: 18; height: 18
        anchors { right: parent.right; bottom: parent.bottom; rightMargin: 2; bottomMargin: 2 }
        Canvas {
            anchors.fill: parent
            opacity: gripArea.containsMouse || gripArea.pressed ? 1 : 0.55
            Behavior on opacity { NumberAnimation { duration: 120 * Theme.motion } }
            onPaint: {
                var c = getContext("2d"); c.reset()
                c.strokeStyle = Theme.muted; c.lineWidth = 1.3; c.lineCap = "round"
                for (var i = 1; i <= 3; i++) { c.beginPath(); c.moveTo(width - 3, height - 3 - i * 4); c.lineTo(width - 3 - i * 4, height - 3); c.stroke() }
            }
        }
        MouseArea {
            id: gripArea
            anchors.fill: parent; anchors.margins: -4
            hoverEnabled: true
            cursorShape: Qt.SizeVerCursor
            preventStealing: true                   // the page must not scroll instead
            property real startY: 0
            property real startH: 0
            onPressed: (m) => { startY = mapToItem(null, m.x, m.y).y; startH = root.height }
            onPositionChanged: (m) => {
                if (!pressed) return
                var h = startH + mapToItem(null, m.x, m.y).y - startY
                root.Layout.preferredHeight = Math.round(Math.max(root.minHeight, Math.min(root.maxHeight, h)))
            }
            onReleased: if (root.sizeKey) Backend.setSetting(root.sizeKey, String(root.Layout.preferredHeight))
            onDoubleClicked: { root.Layout.preferredHeight = root.implicitDefault; if (root.sizeKey) Backend.setSetting(root.sizeKey, "") }
        }
        Tip { visible: gripArea.containsMouse && !gripArea.pressed; delay: 600; text: "Drag to resize \u00B7 double-click to reset" }
    }
}
