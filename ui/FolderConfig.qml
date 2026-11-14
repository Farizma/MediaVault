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
    function show(id, source) { folderId = id; load(); open(source) }
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
