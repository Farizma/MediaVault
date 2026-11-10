// First-run onboarding: pick folders, choose scraping per folder, optional API key, file types.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    color: Theme.black
    ListModel { id: folders }
    property string problem: ""

    function addFolder() {
        var path = Onboarding.pickFolder()
        if (path === "") return
        for (var i = 0; i < folders.count; i++) if (folders.get(i).path === path) return
        folders.append({ path: path, tab: Onboarding.baseName(path), scrape: true, anime: /anime/i.test(path),
                         parts: Backend.scrapeParts().map(function(x) { return x.id }).join(",") })
        problem = ""
    }

    Rectangle {
        id: card
        anchors.centerIn: parent
        width: Math.min(760, parent.width - 48)
        // grows with its content, scrolls only when the window is too short
        height: Math.min(parent.height - 48, col.implicitHeight + 52 + footer.height)
        radius: 24
        color: Theme.graphite
        border.color: Theme.line
        opacity: 0
        scale: 0.98 + 0.02 * opacity
        Component.onCompleted: fade.start()
        NumberAnimation on opacity { id: fade; running: false; from: 0; to: 1; duration: 300 * Theme.motion; easing.type: Easing.OutCubic }

        Flickable {
            id: flick
            anchors { left: parent.left; right: parent.right; top: parent.top; bottom: footer.top; leftMargin: 40; rightMargin: 28; topMargin: 40; bottomMargin: 12 }
            contentHeight: col.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}
            ColumnLayout {
                id: col
                width: flick.width - 12
                spacing: 16

                RowLayout {
                    spacing: 14
                    Image { Layout.preferredWidth: 44; Layout.preferredHeight: 44; source: "brand/icon-128.png"; sourceSize: Qt.size(88, 88); smooth: true; mipmap: true }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        Text { Layout.fillWidth: true; text: "Welcome to Media Vault"; color: "#FFFFFF"; font.pixelSize: 24; font.weight: Font.ExtraBold; font.letterSpacing: -0.6; wrapMode: Text.Wrap }
                        Text { Layout.fillWidth: true; text: "Point it at your folders. It keeps the library up to date by itself."; color: Theme.faint; font.pixelSize: 13; wrapMode: Text.Wrap }
                    }
                }
                Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line; Layout.topMargin: 4; Layout.bottomMargin: 4 }

                Text { text: "FOLDERS · EACH ONE BECOMES A TAB"; color: Theme.faint; font.family: Theme.mono; font.pixelSize: 11 }
                Repeater {
                    model: folders
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: folderCol.implicitHeight + 28
                        radius: 12
                        color: Theme.slate
                        border.color: Theme.line
                        ColumnLayout {
                            id: folderCol
                            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 14 }
                            spacing: 10
                            RowLayout {
                                spacing: 10
                                Rectangle { width: 8; height: 8; radius: 4; color: Theme.blue }
                                Text { text: model.path; color: "#99FFFFFF"; font.family: Theme.mono; font.pixelSize: 11; elide: Text.ElideMiddle; Layout.fillWidth: true }
                                Rectangle {
                                    width: 26; height: 26; radius: 13
                                    color: removeArea.containsMouse ? Theme.fillHover : "transparent"
                                    Text { anchors.centerIn: parent; text: "✕"; color: removeArea.containsMouse ? Theme.red : "#66FFFFFF"; font.pixelSize: 12 }
                                    MouseArea { id: removeArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: folders.remove(index) }
                                }
                            }
                            RowLayout {
                                spacing: 16
                                Field { Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.minimumWidth: 140; placeholderText: "Tab name"; text: model.tab; onTextEdited: folders.setProperty(index, "tab", text) }
                                Toggle {
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: 1
                                    Layout.minimumWidth: 190
                                    text: "Scrape the web"
                                    hint: "Covers, details and actors. Off for home videos."
                                    checked: model.scrape
                                    onToggled: folders.setProperty(index, "scrape", checked)
                                }
                            }
                            Toggle { Layout.fillWidth: true; visible: model.scrape; text: "Anime (details from AniList)"
                                checked: model.anime; onToggled: folders.setProperty(index, "anime", checked) }
                            ScrapeParts {
                                Layout.fillWidth: true
                                enabled: model.scrape
                                visible: model.scrape
                                selected: model.parts.split(",")
                                onEdited: (csv) => folders.setProperty(index, "parts", csv)
                            }
                        }
                    }
                }
                // add-folder card (dashed, like the web onboarding)
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: 64
                    radius: 12
                    color: addArea.containsMouse ? Theme.fill : "#80000000"
                    border.color: addArea.containsMouse ? "#4DFFFFFF" : "#33FFFFFF"
                    scale: addArea.pressed ? 0.99 : 1
                    Behavior on scale { NumberAnimation { duration: 120 * Theme.motion } }
                    Row {
                        anchors.centerIn: parent
                        spacing: 10
                        Text { text: "+"; color: Theme.blue; font.pixelSize: 20; font.weight: Font.Bold; anchors.verticalCenter: parent.verticalCenter }
                        Text { text: folders.count === 0 ? "Add the folders that hold your movies, shows and home videos" : "Add another folder"
                            color: "#E6FFFFFF"; font.pixelSize: 13; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter
                            width: Math.min(implicitWidth, card.width - 160); elide: Text.ElideRight }
                    }
                    MouseArea { id: addArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.addFolder() }
                }

                Text { text: "POSTERS AND SYNOPSES (OPTIONAL)"; color: Theme.faint; font.family: Theme.mono; font.pixelSize: 11; Layout.topMargin: 6 }
                Field { id: tmdb; Layout.fillWidth: true; placeholderText: "TMDB API key"; echoMode: TextInput.Password }
                Toggle { id: associate; Layout.fillWidth: true; Layout.topMargin: 4; checked: true; text: "Offer Media Vault in “Open with”"; hint: "For .mp4, .mkv and .avi files" }

            }
        }
        // Finish stays visible however many folders are listed
        Item {
            id: footer
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom; leftMargin: 40; rightMargin: 40 }
            height: 88
            Rectangle { width: parent.width; height: 1; color: Theme.line }
            RowLayout {
                anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter }
                Text { Layout.fillWidth: true; text: root.problem; color: Theme.red; font.pixelSize: 13; wrapMode: Text.Wrap }
                GlassButton {
                    label: "Finish setup"; primary: true
                    onClicked: {
                        if (folders.count === 0) { root.problem = "Add at least one folder to continue."; return }
                        var out = []
                        for (var i = 0; i < folders.count; i++) out.push({ path: folders.get(i).path, tab: folders.get(i).tab, scrape: folders.get(i).scrape,
                                                                        anime: folders.get(i).anime,
                                                                        parts: folders.get(i).parts.split(",").filter(function(p) { return p !== "" }) })
                        Onboarding.finish(JSON.stringify(out), tmdb.text, associate.checked)
                    }
                }
            }
        }
    }
}
