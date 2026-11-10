// Four frames grabbed from the video (10 / 30 / 50 / 70 %), served straight from RAM.
import QtQuick
import QtQuick.Layouts

Item {
    id: root
    property string itemKey: ""
    property real shown: 0
    property int count: 0
    property bool busy: false
    // frames shrink with the window so all four always fit (2:3, at most 200 x 300)
    readonly property real frameW: Math.min(200, (width - 48 - 64 - 3 * 14) / 4, (height - 48 - 190) * 2 / 3)
    visible: false
    focus: visible
    z: 30
    Keys.onEscapePressed: close()

    property real originX: width / 2
    property real originY: height / 2
    function begin(key, source) {
        if (source) { var p = source.mapToItem(root, source.width / 2, source.height / 2); originX = p.x; originY = p.y }
        itemKey = key; count = 0; busy = true; visible = true; forceActiveFocus(); hide.stop(); appear.restart(); Backend.chooseThumbnail(key) }
    function show(n) { count = n; busy = false; if (n === 0) dismiss() }
    function dismiss() { if (visible && !hide.running) { appear.stop(); hide.restart() } }
    function close() { busy = false; Backend.discardThumbnails(); dismiss() }
    NumberAnimation { id: appear; target: root; property: "shown"; to: 1; duration: 380 * Theme.motion; easing.type: Easing.OutQuint }
    NumberAnimation { id: hide; target: root; property: "shown"; to: 0; duration: 260 * Theme.motion; easing.type: Easing.InOutCubic
        onFinished: root.visible = false }

    Rectangle { anchors.fill: parent; color: Theme.scrim; opacity: root.shown }
    MouseArea { anchors.fill: parent; onClicked: root.close(); onWheel: (w) => w.accepted = true }

    Rectangle {
        anchors.centerIn: parent
        width: Math.max(420, col.implicitWidth + 64)
        height: col.implicitHeight + 56
        radius: 16
        color: Theme.panel
        border.color: Theme.lineStrong
        id: card
        opacity: Math.min(1, root.shown * 1.5)
        transform: Scale { origin.x: root.originX - card.x; origin.y: root.originY - card.y; xScale: 0.06 + 0.94 * root.shown; yScale: xScale }
        MouseArea { anchors.fill: parent }
        ColumnLayout {
            id: col
            anchors.centerIn: parent
            spacing: 18
            Column {
                Layout.alignment: Qt.AlignHCenter
                spacing: 4
                Text { anchors.horizontalCenter: parent.horizontalCenter; text: root.busy ? "Grabbing frames…" : "Pick your favourite frame"; color: "#FFFFFF"; font.pixelSize: 20; font.weight: Font.ExtraBold; font.letterSpacing: -0.3 }
                Text { anchors.horizontalCenter: parent.horizontalCenter; text: "FRAMES AT 10 · 30 · 50 · 70 %  ·  HELD IN RAM UNTIL YOU PICK"; color: Theme.faint; font.family: Theme.mono; font.pixelSize: 10 }
            }
            Row {
                Layout.alignment: Qt.AlignHCenter
                spacing: 14
                Repeater {
                    model: root.busy ? 4 : root.count
                    Rectangle {
                        id: frameCard
                        width: root.frameW; height: root.frameW * 1.5; radius: 12
                        color: Theme.slate; border.color: pick.containsMouse ? "#66FFFFFF" : Theme.line
                        clip: true
                        scale: (pick.containsMouse ? 1.03 : 1) * (0.92 + 0.08 * landed)
                        opacity: landed
                        property real landed: 0
                        Component.onCompleted: arrive.start()
                        SequentialAnimation { id: arrive; PauseAnimation { duration: index * 60 * Theme.motion }
                            NumberAnimation { target: frameCard; property: "landed"; to: 1; duration: 260 * Theme.motion; easing.type: Easing.OutCubic } }
                        Behavior on scale { NumberAnimation { duration: 150 * Theme.motion; easing.type: Easing.OutCubic } }
                        Image {
                            anchors { fill: parent; margins: 1 }
                            visible: !root.busy
                            source: root.busy ? "" : "image://frames/thumb" + index
                            fillMode: Image.PreserveAspectCrop    // centre 2:3 of the 16:9 frame
                            cache: false
                        }
                        Text { visible: !root.busy; anchors { left: parent.left; bottom: parent.bottom; margins: 8 }
                            text: [10, 30, 50, 70][index] + "%"; color: "#CCFFFFFF"; font.family: Theme.mono; font.pixelSize: 10
                            Rectangle { z: -1; anchors { fill: parent; margins: -4 } radius: 4; color: "#BF000000" } }
                        MouseArea {
                            id: pick; anchors.fill: parent; hoverEnabled: !root.busy; enabled: !root.busy; cursorShape: Qt.PointingHandCursor
                            onClicked: { Backend.useThumbnail(root.itemKey, index); root.dismiss() }
                        }
                    }
                }
            }
            GlassButton { label: "Cancel"; Layout.alignment: Qt.AlignHCenter; onClicked: root.close() }
        }
    }
}
