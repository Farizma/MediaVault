// Insights: watch time this week, top-rated genres, and which tags count. A window of its own that grows out of
// the Insights button and shrinks back into it (Esc, the close button, or a click outside).
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    readonly property var ins: Backend.insights
    property rect from: Qt.rect(width / 2, height / 2, 0, 0)
    property real shown: 0
    function maxOf(list, field) { var m = 1; for (var i = 0; i < (list || []).length; i++) m = Math.max(m, list[i][field]); return m }
    function open(source) {
        if (source) { var p = source.mapToItem(root, 0, 0); from = Qt.rect(p.x, p.y, source.width, source.height) }
        Backend.refreshInsights()
        shown = 1
        panel.forceActiveFocus()
    }
    function close() { shown = 0 }
    visible: shown > 0.001
    z: 35
    Behavior on shown { NumberAnimation { duration: (root.shown < 0.5 ? 380 : 220) * Theme.motion; easing.type: root.shown < 0.5 ? Easing.OutQuint : Easing.InCubic } }

    Rectangle { anchors.fill: parent; color: Theme.scrim; opacity: root.shown
        MouseArea { anchors.fill: parent; onClicked: root.close(); onWheel: (w) => w.accepted = true } }

    Rectangle {
        id: panel
        anchors.centerIn: parent
        width: Math.min(900, root.width - 48)
        height: Math.min(root.height - 48, insRow.implicitHeight + head.height + 66)
        radius: 18
        color: Theme.panel
        border.color: Theme.lineStrong
        clip: true
        opacity: Math.min(1, root.shown * 1.6)
        // grows out of the button that opened it, and warps back into it
        transform: Scale { origin.x: root.from.x + root.from.width / 2 - panel.x; origin.y: root.from.y + root.from.height / 2 - panel.y
                           xScale: 0.05 + 0.95 * root.shown; yScale: 0.05 + 0.95 * root.shown }
        Keys.onEscapePressed: root.close()
        MouseArea { anchors.fill: parent }

        Item {
            id: head
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 24 }
            height: 40
            Column {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 2
                Text { text: "Insights"; color: Theme.text; font.pixelSize: 22; font.weight: Font.ExtraBold; font.letterSpacing: -0.4 }
                Text { text: "What you watched, and what you rate highest"; color: Theme.faint; font.pixelSize: 12 }
            }
            Rectangle {
                anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                width: 34; height: 34; radius: 17
                color: xArea.containsMouse ? Qt.rgba(1, 1, 1, 0.20) : Theme.fillHover
                border.color: Theme.line
                Text { anchors.centerIn: parent; text: "\u2715"; color: "#B3FFFFFF"; font.pixelSize: 14 }
                MouseArea { id: xArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.close() }
            }
        }

                    RowLayout {
                        id: insRow
                        anchors { left: parent.left; right: parent.right; top: head.bottom; margins: 24; topMargin: 18 }
                        spacing: 36
                        ColumnLayout {
                            Layout.alignment: Qt.AlignTop
                            spacing: 6
                            Text { text: "WATCH TIME · 7 DAYS"; color: Theme.faint; font.family: Theme.mono; font.pixelSize: 11 }
                            Text { text: root.ins.total || "0h 00m"; color: Theme.text; font.pixelSize: 22; font.weight: Font.ExtraBold; font.letterSpacing: -0.4 }
                            Row {
                                Layout.topMargin: 6
                                spacing: 10
                                Repeater {
                                    model: root.ins.days || []
                                    Column {
                                        spacing: 4
                                        Item {     // bars grow up from a shared baseline
                                            width: 24; height: 72
                                            Rectangle {
                                                anchors.bottom: parent.bottom
                                                width: parent.width; radius: 5; color: modelData.minutes > 0 ? Theme.green : Theme.fillHover
                                                height: Math.max(4, 72 * modelData.minutes / root.maxOf(root.ins.days, "minutes"))
                                            }
                                        }
                                        Text { text: modelData.label; color: Theme.faint; font.family: Theme.mono; font.pixelSize: 10; anchors.horizontalCenter: parent.horizontalCenter }
                                    }
                                }
                            }
                        }
                        ColumnLayout {
                            Layout.alignment: Qt.AlignTop
                            spacing: 7
                            Text { text: "TOP-RATED GENRES"; color: Theme.faint; font.family: Theme.mono; font.pixelSize: 11 }
                            Repeater {
                                model: root.ins.genres || []
                                Row {
                                    spacing: 8
                                    Text { text: modelData.name; color: Theme.text; font.pixelSize: 12; font.weight: Font.DemiBold; width: 108; elide: Text.ElideRight }
                                    Rectangle { width: Math.max(4, 120 * modelData.minutes / root.maxOf(root.ins.genres, "minutes")); height: 8; radius: 4; color: Theme.blue; anchors.verticalCenter: parent.verticalCenter }
                                    Text { text: modelData.minutes + "m" + (modelData.rating > 0 ? "  " + modelData.rating.toFixed(1) + "★" : ""); color: Theme.faint; font.family: Theme.mono; font.pixelSize: 11 }
                                }
                            }
                            Text { visible: (root.ins.genres || []).length === 0; text: "Genres appear once scraped titles are watched."; color: Theme.faint; font.pixelSize: 12 }
                        }
                        ColumnLayout {
                            Layout.alignment: Qt.AlignTop
                            Layout.fillWidth: true
                            Layout.preferredWidth: 1          // take what is left, never push the row wider
                            Layout.minimumWidth: 160
                            spacing: 8
                            Text { text: "TAP A TAG TO HIDE IT FROM THESE CHARTS"; Layout.fillWidth: true; color: Theme.faint; font.family: Theme.mono; font.pixelSize: 11; wrapMode: Text.Wrap }
                            Flow {
                                Layout.fillWidth: true; spacing: 6
                                Repeater {
                                    model: root.ins.tags || []
                                    Pill { label: (modelData.hidden ? "Hidden: " : "") + modelData.name; selected: !modelData.hidden; accent: Theme.blue; onClicked: Backend.toggleTag(modelData.name) }
                                }
                            }
                        }
                    }
    }
}
