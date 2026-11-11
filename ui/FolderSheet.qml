// After picking a folder: name its tab and choose what to scrape, then add it.
// Grows out of the middle of the window; Esc or a click outside cancels.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    property string path: ""
    property real shown: 0
    visible: shown > 0
    z: 40
    Behavior on shown { NumberAnimation { duration: (root.shown < 0.5 ? 300 : 200) * Theme.motion; easing.type: Easing.OutCubic } }

    function open(p, name) {
        path = p
        tabName.text = name
        scrapeOn.checked = true
        animeOn.checked = /anime/i.test(p)       // a folder called Anime is very likely anime
        parts.selected = parts.parts.map(function(x) { return x.id })
        shown = 1
        tabName.forceActiveFocus()
        tabName.selectAll()
    }
    function close() { shown = 0 }
    function add() {
        Backend.addFolder(path, tabName.text, scrapeOn.checked, parts.selected.join(","), animeOn.checked)
        close()
    }

    Rectangle { anchors.fill: parent; color: Theme.scrim; opacity: root.shown
        MouseArea { anchors.fill: parent; onClicked: root.close() } }

    Rectangle {
        id: panel
        anchors.centerIn: parent
        width: Math.min(560, root.width - 48)
        height: col.implicitHeight + 48
        radius: 18
        color: Theme.graphite
        border.color: Theme.lineStrong
        opacity: root.shown
        scale: 0.92 + 0.08 * root.shown
        MouseArea { anchors.fill: parent }
        Keys.onEscapePressed: root.close()

        ColumnLayout {
            id: col
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 24 }
            spacing: 12
            Text { text: "Add folder"; color: Theme.text; font.pixelSize: 22; font.weight: Font.ExtraBold; font.letterSpacing: -0.4 }
            Text { Layout.fillWidth: true; text: root.path; color: "#80FFFFFF"; font.family: Theme.mono; font.pixelSize: 11; elide: Text.ElideMiddle }
            Text { text: "TAB NAME"; color: Theme.faint; font.family: Theme.mono; font.pixelSize: 10; Layout.topMargin: 4 }
            Field { id: tabName; Layout.fillWidth: true; placeholderText: "Tab name"; onAccepted: root.add(); Keys.onEscapePressed: root.close() }
            Toggle { id: scrapeOn; Layout.fillWidth: true; Layout.topMargin: 4; text: "Scrape the web"
                hint: "Off for home videos: nothing about them leaves this PC" }
            Toggle { id: animeOn; Layout.fillWidth: true; text: "This folder is anime"; enabled: scrapeOn.checked; opacity: enabled ? 1 : 0.4
                hint: "Details, cast and art from AniList (no key needed) instead of TMDB. Understands \u201C[Group] Show - 07\u201D file names." }
            Text { text: "WHAT TO SCRAPE"; color: Theme.faint; font.family: Theme.mono; font.pixelSize: 10; opacity: scrapeOn.checked ? 1 : 0.4 }
            ScrapeParts { id: parts; Layout.fillWidth: true; enabled: scrapeOn.checked }
            Text { Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.faint; font.pixelSize: 11; opacity: scrapeOn.checked ? 1 : 0.4
                text: "Change this any time in Settings › Library › Configure. Your own titles, art and notes always win over scraped ones." }
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 8
                Item { Layout.fillWidth: true }
                GlassButton { label: "Cancel"; onClicked: root.close() }
                GlassButton { label: "Add folder"; primary: true; onClicked: root.add() }
            }
        }
    }
}
