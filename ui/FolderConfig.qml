// Configure one library folder: its tab, where it shows, scraping (TMDB or AniList, and what to fetch), tagging,
// and removing it. Opened from Settings > Library > Configure. Every change applies at once.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Sheet {
    id: root
    property int folderId: -1
    property var f: ({})
    maxWidth: 720
    title: f.name ? "Configure “" + f.name + "”" : "Configure folder"
    sub: f.path || ""
    signal changed()

    property string discordMode: "show"
    function load() {
        f = Backend.directories().find(function(d) { return d.id === folderId }) || ({})
        discordMode = Backend.discordPrivacy().folders[String(folderId)] || "show"
    }
    property var subs: []           // its subfolders, tree order: {rel, name, depth, videos, excluded, inherited}
    property bool subsBusy: false
    function loadSubs() { subsBusy = true; Backend.listSubfolders(folderId) }
    Connections {
        target: Backend
        function onSubfoldersReady(id, rows) { if (id === root.folderId) { root.subs = rows; root.subsBusy = false } }
    }
    function show(id, source) { folderId = id; subs = []; load(); open(source); loadSubs() }
    function after() { load(); changed() }

    component Caption: Text { color: Theme.faint; font.family: Theme.mono; font.pixelSize: 10; Layout.topMargin: 10 }
    component Note: Text { Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.faint; font.pixelSize: 11 }

    ColumnLayout {
        width: parent.width
        spacing: 10

        Caption { text: "TAB"; Layout.topMargin: 0 }
        Field {
            Layout.fillWidth: true
            text: root.f.name || ""
            placeholderText: "Tab name (empty: the folder's own name)"
            onEditingFinished: if (text !== root.f.name) { text = Backend.renameTab(root.folderId, text); root.after() }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 16
            Toggle { Layout.fillWidth: true; text: "Show in the All tab"; hint: "Its own tab always shows it"
                checked: root.f.inAll === true; onToggled: { Backend.toggleHidden("all_dirs", String(root.folderId)); root.after() } }
            Toggle { Layout.fillWidth: true; text: "Count in Insights"; hint: "Watch time and top genres"
                checked: root.f.inInsights === true; onToggled: { Backend.toggleHidden("insights_dirs", String(root.folderId)); root.after() } }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 16
            // how this tab shows its titles: DVD cases (the grid or the shelf) or wide video cards
            Toggle { Layout.fillWidth: true; text: "Landscape thumbnails"; hint: "16:9 video cards in this tab instead of DVD cases (pick a frame with Choose thumbnail)"
                checked: root.f.landscape === true; onToggled: { Backend.setTabLandscape(root.folderId, checked); root.after() } }
            Item { Layout.fillWidth: true }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 16
            Toggle { Layout.fillWidth: true; text: "Continue Watching row"; hint: "Part-watched titles above this tab's catalog"
                checked: root.f.continueRow === true; onToggled: { Backend.toggleHidden("continue_dirs", String(root.folderId)); root.after() } }
            Toggle { Layout.fillWidth: true; text: "Recently Added row"; hint: "Titles added in the last 30 days"
                checked: root.f.recentRow === true; onToggled: { Backend.toggleHidden("recent_dirs", String(root.folderId)); root.after() } }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 16
            Toggle { Layout.fillWidth: true; text: "Private tab"; hint: "Hidden everywhere until you sign in (needs a sign-in in Settings \u203A Privacy)"
                checked: root.f.private === true
                onToggled: { Backend.toggleHidden("private_dirs", String(root.folderId)); root.after(); checked = Qt.binding(function() { return root.f.private === true }) } }
        }

        Caption { text: "SUBFOLDERS" + (root.f.leftOut ? "  \u00B7  " + root.f.leftOut + " LEFT OUT" : "") }
        Note { text: "Untick a subfolder to leave it out: its titles leave this tab, scans, scraping and the watcher. Their tags, notes and watch history are kept for when you tick it again." }
        Rectangle {
            id: subBox
            Layout.fillWidth: true
            Layout.preferredHeight: root.subs.length ? Math.min(subList.contentHeight + 8, 264) : 44
            radius: 10
            color: "transparent"
            border.color: Theme.line
            Behavior on Layout.preferredHeight { NumberAnimation { duration: Theme.motion ? 220 : 0; easing.type: Easing.OutCubic } }
            Row {
                anchors.centerIn: parent
                spacing: 8
                visible: root.subs.length === 0
                Spinner { size: 14; color: Theme.blue; running: root.subsBusy; visible: root.subsBusy; anchors.verticalCenter: parent.verticalCenter }
                Text { color: Theme.faint; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter
                    text: root.subsBusy ? "Reading the folder\u2026" : "No subfolders: every video sits in the folder itself" }
            }
            ListView {
                id: subList
                anchors { fill: parent; margins: 4 }
                clip: true
                model: root.subs
                boundsBehavior: Flickable.StopAtBounds
                delegate: Rectangle {
                    id: row
                    required property var modelData
                    readonly property bool on: !modelData.excluded && !modelData.inherited
                    width: ListView.view.width
                    height: 32
                    radius: 7
                    color: hit.containsMouse && !modelData.inherited ? Theme.fillHover : "transparent"
                    opacity: modelData.inherited ? 0.4 : 1
                    Rectangle {
                        id: box
                        x: 10 + row.modelData.depth * 20
                        anchors.verticalCenter: parent.verticalCenter
                        width: 16; height: 16; radius: 4
                        color: row.on ? Theme.blue : "transparent"
                        border.color: row.on ? Theme.blue : Theme.muted
                        border.width: 1.5
                        Behavior on color { ColorAnimation { duration: Theme.motion ? 120 : 0 } }
                        Text { anchors.centerIn: parent; text: "\u2713"; color: "white"; font.pixelSize: 11; font.bold: true
                            visible: row.on; scale: row.on ? 1 : 0.6
                            Behavior on scale { NumberAnimation { duration: Theme.motion ? 160 : 0; easing.type: Easing.OutBack } } }
                    }
                    Text {
                        anchors { left: box.right; leftMargin: 10; right: count.left; rightMargin: 10; verticalCenter: parent.verticalCenter }
                        text: row.modelData.name
                        elide: Text.ElideMiddle
                        color: row.on ? Theme.text : Theme.muted
                        font.pixelSize: 13
                    }
                    Text {
                        id: count
                        anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
                        text: row.modelData.videos === 1 ? "1 video" : row.modelData.videos + " videos"
                        color: Theme.faint; font.family: Theme.mono; font.pixelSize: 10
                    }
                    MouseArea {
                        id: hit
                        anchors.fill: parent
                        hoverEnabled: true
                        enabled: !row.modelData.inherited
                        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: {
                            Backend.setSubfolderIncluded(root.folderId, row.modelData.rel, !row.on)
                            root.after(); root.loadSubs()
                        }
                    }
                }
            }
        }

        Caption { text: "SCRAPING" }
        Toggle { id: scrapeOn; Layout.fillWidth: true; text: "Scrape the web for this folder"; hint: "Off for home videos: nothing about them leaves this PC"
            checked: root.f.scrape === true; onToggled: { Backend.setScrape(root.folderId, checked); root.after() } }
        // where details come from
        RowLayout {
            Layout.fillWidth: true
            spacing: 14
            enabled: scrapeOn.checked
            opacity: enabled ? 1 : 0.4
            Rectangle {
                id: sourceSeg
                implicitWidth: 300; implicitHeight: 34; radius: 10; color: "#99000000"; border.color: Theme.line
                Rectangle { width: (parent.width - 6) / 2; height: parent.height - 6; y: 3; radius: 8; color: Theme.text
                    x: 3 + (root.f.anime === true ? width : 0)
                    Behavior on x { NumberAnimation { duration: 240 * Theme.motion; easing.type: Easing.OutCubic } } }
                Row {
                    anchors { fill: parent; margins: 3 }
                    Repeater {
                        model: [[false, "Movies & TV · TMDB"], [true, "Anime · AniList"]]
                        Item {
                            width: parent.width / 2; height: parent.height
                            Text { anchors.centerIn: parent; text: modelData[1]; font.pixelSize: 12; font.weight: Font.Bold
                                color: (root.f.anime === true) === modelData[0] ? Theme.black : Theme.muted }
                            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                onClicked: if ((root.f.anime === true) !== modelData[0]) { Backend.setAnime(root.folderId, modelData[0]); root.after() } }
                        }
                    }
                }
            }
            Note { text: root.f.anime === true ? "AniList needs no key, and understands “[Group] Show - 07” file names." : "Needs a TMDB key (Settings › Integrations & APIs); OMDb fills in when TMDB has nothing." }
        }
        Text { text: "WHAT TO SCRAPE"; color: Theme.faint; font.family: Theme.mono; font.pixelSize: 10; opacity: scrapeOn.checked ? 1 : 0.4 }
        ScrapeParts { Layout.fillWidth: true; enabled: scrapeOn.checked; selected: root.f.parts || []
            onEdited: (csv) => { Backend.setScrapeParts(root.folderId, csv); root.f.parts = csv.split(",") } }
        RowLayout {
            Layout.fillWidth: true
            spacing: 12
            Note { text: "New files follow these choices. For titles already here, Fetch missing adds what they lack (age ratings, original titles, actors, covers, discs, box sets, genres, Gallery) and leaves titles and your edits alone." }
            GlassButton { small: true; label: "Fetch missing"; enabled: scrapeOn.checked; opacity: enabled ? 1 : 0.4
                onClicked: Backend.fetchMissing(root.folderId) }
        }

        Caption { text: "TAGGING" }
        RowLayout {
            Layout.fillWidth: true
            spacing: 12
            Note { text: "Tags from this folder's sub-folders and file names, its age ratings and your rules (Tag Manager), worked out again for every title here. Tags you added yourself stay." }
            GlassButton { small: true; label: "Re-tag this folder"; onClicked: Backend.retag(root.folderId) }
        }

        Caption { text: "DISCORD" }
        RowLayout {
            Layout.fillWidth: true
            spacing: 6
            Note { text: "What Discord may show while you watch something from this folder (when Discord status is on in Settings \u203A Integrations & APIs)." }
            Repeater {
                model: [["show", "Title"], ["generic", "\u201CWatching a video\u201D"], ["off", "Nothing"]]
                Pill { label: modelData[1]; accent: Theme.blue; selected: root.discordMode === modelData[0]
                    onClicked: { Backend.setDiscordFolder(root.folderId, modelData[0]); root.discordMode = modelData[0] } }
            }
        }

        Caption { text: "REMOVE" }
        RowLayout {
            Layout.fillWidth: true
            spacing: 12
            Note { text: removeBtn.armed ? "Click again to remove. The files stay on your drive; only the tab and what Media Vault knows about them go."
                                         : "Takes the tab out of Media Vault. Your files are never deleted." }
            GlassButton {
                id: removeBtn
                property bool armed: false
                small: true
                label: armed ? "Remove for good" : "Remove folder…"
                glyphColor: Theme.red
                onClicked: { if (!armed) { armed = true; disarm.restart(); return } armed = false; Backend.removeFolder(root.folderId); root.changed(); root.close() }
                Timer { id: disarm; interval: 4000; onTriggered: removeBtn.armed = false }
            }
        }
    }
}
