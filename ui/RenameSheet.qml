// Rename files on disk to match their titles: a preview of every change first, nothing happens until Rename.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Sheet {
    id: root
    title: "Rename files to match"
    sub: "Films become “Title (Year)”, episodes “Series S01E02 - Name”. Artwork and subtitles beside them follow. Folders are not renamed."
    maxWidth: 860
    maxHeight: 640
    scrolls: false
    property var rows: []
    readonly property int ready: { var n = 0; for (var i = 0; i < rows.length; i++) if (!rows[i].problem) n++; return n }
    signal done()
    function begin(keys) { rows = Backend.renamePlan(keys); from = Qt.rect(width / 2, height / 2, 0, 0); shown = 1 }

    ColumnLayout {
        anchors.fill: parent
        spacing: 12
        Text { visible: root.rows.length === 0; Layout.fillWidth: true; Layout.topMargin: 30; horizontalAlignment: Text.AlignHCenter
            text: "These files already match their titles."; color: Theme.faint; font.pixelSize: 13 }
        ListView {
            id: renameList
            Layout.fillWidth: true; Layout.fillHeight: true
            visible: root.rows.length > 0
            SmoothWheel { view: renameList; step: 160 }
            clip: true
            spacing: 6
            boundsBehavior: Flickable.StopAtBounds
            model: root.rows
            ScrollBar.vertical: ScrollBar {}
            delegate: Rectangle {
                width: ListView.view.width - 10; height: 58; radius: 10
                color: Theme.slate; border.color: modelData.problem ? "#66FF453A" : Theme.line
                Column {
                    anchors { left: parent.left; right: parent.right; margins: 12; verticalCenter: parent.verticalCenter }
                    spacing: 4
                    Text { width: parent.width; text: modelData.old; color: Theme.faint; font.family: Theme.mono; font.pixelSize: 11; elide: Text.ElideMiddle }
                    Text { width: parent.width; elide: Text.ElideMiddle; font.pixelSize: 13; font.weight: Font.DemiBold
                        text: modelData.problem ? modelData.problem : "→ " + modelData.new
                        color: modelData.problem ? Theme.red : Theme.text }
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            Text { Layout.fillWidth: true; color: Theme.faint; font.family: Theme.mono; font.pixelSize: 11
                text: root.rows.length === 0 ? "" : root.ready + " TO RENAME" + (root.rows.length > root.ready ? " · " + (root.rows.length - root.ready) + " SKIPPED" : "") }
            GlassButton { label: "Cancel"; onClicked: root.close() }
            GlassButton { primary: true; visible: root.ready > 0; label: "Rename " + root.ready + (root.ready === 1 ? " file" : " files")
                onClicked: { Backend.renameApply(root.rows); root.close(); root.done() } }
        }
    }
}
