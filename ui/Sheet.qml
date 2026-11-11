// A window inside the app: grows out of the button that opened it and warps back into it; Esc, the close button or
// a click outside closes it. Content goes in as children (it scrolls when taller than the window).
//   Sheet { id: s; title: "Configure"; sub: "..."; Column { ... } }     s.open(button)
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    property string title: ""
    property string sub: ""
    property int maxWidth: 820
    property int maxHeight: 760
    property bool scrolls: true                 // false: the content fills the panel and handles its own scrolling
    property rect from: Qt.rect(width / 2, height / 2, 0, 0)
    property real shown: 0
    default property alias content: holder.data
    signal closed()
    function open(source) {
        if (source) { var p = source.mapToItem(root, 0, 0); from = Qt.rect(p.x, p.y, source.width, source.height) }
        else from = Qt.rect(width / 2, height / 2, 0, 0)
        shown = 1
        panel.forceActiveFocus()
    }
    function close() { if (shown > 0) { shown = 0; closed() } }
    readonly property bool isOpen: shown > 0.001
    visible: isOpen
    z: 36
    Behavior on shown { NumberAnimation { duration: (root.shown < 0.5 ? 380 : 220) * Theme.motion; easing.type: root.shown < 0.5 ? Easing.OutQuint : Easing.InCubic } }

    Rectangle { anchors.fill: parent; color: Theme.scrim; opacity: root.shown
        MouseArea { anchors.fill: parent; onClicked: root.close(); onWheel: (w) => w.accepted = true } }

    Rectangle {
        id: panel
        anchors.centerIn: parent
        width: Math.min(root.maxWidth, root.width - 48)
        height: Math.min(root.maxHeight, root.height - 48)
        radius: 18
        color: Theme.panel
        border.color: Theme.lineStrong
        clip: true
        opacity: Math.min(1, root.shown * 1.6)
        transform: Scale { origin.x: root.from.x + root.from.width / 2 - panel.x; origin.y: root.from.y + root.from.height / 2 - panel.y
                           xScale: 0.05 + 0.95 * root.shown; yScale: 0.05 + 0.95 * root.shown }
        Keys.onEscapePressed: root.close()
        MouseArea { anchors.fill: parent }

        Item {
            id: head
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 24 }
            height: Math.max(40, headCol.implicitHeight)
            ColumnLayout {
                id: headCol
                anchors { left: parent.left; right: closeBtn.left; rightMargin: 16; verticalCenter: parent.verticalCenter }
                spacing: 3
                Text { Layout.fillWidth: true; text: root.title; color: Theme.text; font.pixelSize: 22; font.weight: Font.ExtraBold; font.letterSpacing: -0.4; elide: Text.ElideRight }
                Text { Layout.fillWidth: true; visible: root.sub !== ""; text: root.sub; color: Theme.faint; font.pixelSize: 12; wrapMode: Text.Wrap }
            }
            Rectangle {
                id: closeBtn
                anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                width: 34; height: 34; radius: 17
                color: xArea.containsMouse ? Theme.fillHover : Theme.fill
                border.color: Theme.line
                Text { anchors.centerIn: parent; text: "✕"; color: Theme.muted; font.pixelSize: 14 }
                MouseArea { id: xArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.close() }
            }
        }
        Flickable {
            id: flick
            anchors { left: parent.left; right: parent.right; top: head.bottom; bottom: parent.bottom; topMargin: 16; leftMargin: 24; rightMargin: 14; bottomMargin: 20 }
            contentHeight: root.scrolls ? holder.childrenRect.height : height
            interactive: root.scrolls
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { visible: root.scrolls }
            SmoothWheel { view: flick; step: 160; enabled: root.scrolls }
            Item { id: holder; width: flick.width - 10; height: root.scrolls ? childrenRect.height : flick.height }
        }
    }
}
