// Settings sheet, laid out like the web app's: section list on the left, one section at a time on the right.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    property var folders: []
    property var backups: []
    property var themes: []
    property var hw: ({})
    property string coreSetting: "auto"
    property string levelSetting: "auto"
    property color customAccent: "#30D158"
    property color customHighlight: "#0A84FF"
    property var customColours: []                // the Custom theme: every colour, [{key, name, role, value}]
    property var customMap: ({})                  // key -> colour (what the wheel is changing, live)
    property string editing: "custom_accent"     // which custom colour the wheel is changing
    function customValue(k) { return customMap[k] || "#808080" }
    function reloadCustom() {
        var c = Backend.themes().filter(function(t) { return t.id === "custom" })[0]
        if (!c) return
        customColours = c.colours || []
        var m = {}; customColours.forEach(function(x) { m[x.key] = x.value }); customMap = m
        customAccent = c.accent; customHighlight = c.highlight
    }
    property int section: 0
    property real shown: 0                   // 0..1: the sheet materialises (scale + fade), and dematerialises faster
    // name, icon tint, icon: fixed system colours (like macOS) so they read the same in every theme
    readonly property var sections: [["Library", "#0A84FF", "folders"], ["Appearance", "#AF52DE", "appearance"], ["Playback", "#FF3B30", "playback"],
                                     ["Library Status", "#FF9F0A", "health"], ["Integrations & APIs", "#8E8E93", "integrations"],
                                     ["Streaming", "#5AC8FA", "streaming"], ["About & Updates", "#FF9500", "components"], ["Backups", "#34C759", "backups"],
                                     ["Help", "#5E5CE6", "help"]]
    readonly property string sectionName: sections[section][0]
    signal configureFolder(int id, var source)      // the dashboard opens the folder's Configure window
    signal openTagManager(var source)
    property string discordDetail: Backend.setting("discord_detail") || "title"
    property string discordState: Backend.discordStatus()
    property string discordPaused: Backend.setting("discord_paused") || "show"
    property var discordPreview: Backend.discordPreview(Backend.setting("discord_details"), Backend.setting("discord_state"), discordPaused)
    property var discordHidden: Backend.discordPrivacy()
    property var report: ({})
    property var comps: []
    property bool checking: false
    property real downloading: -1           // 0..1 while the new Media Vault installer downloads
    readonly property var appInfo: Backend.appInfo()
    readonly property var appRow: comps.length ? comps[0] : ({})
    property var castLibs: ({})
    property var castDevices: []
    property bool searching: false
    function refreshHealth() { report = Backend.health() }
    onSectionNameChanged: {
        if (sectionName === "Library Status") refreshHealth()
        if (sectionName === "Streaming") { castLibs = Backend.castSupport(); castDevices = Backend.devices() }
        if (sectionName === "About & Updates") { comps = Backend.components(); checking = true; Backend.checkComponents() }
    }
    Connections {
        target: Backend
        function onDevicesFound(list) { root.castDevices = list; root.searching = false }
        function onComponentsChecked(list) { root.comps = list; root.checking = false }
        function onAppUpdateProgress(p) { root.downloading = p }
        function onStreamChanged() { root.castLibs = Backend.castSupport() }
        function onBoxArtChanged(key) { if (root.visible && root.sectionName === "Library Status") root.refreshHealth() }
        function onLibraryChanged() { if (root.visible && root.sectionName === "Library") root.folders = Backend.directories() }
    }
    readonly property var levelNames: ["Standard", "High Quality", "AI Ultra"]
    signal themeChosen(string id)            // the dashboard cross-fades the whole window into the new colours
    visible: false
    focus: visible
    z: 20
    Keys.onEscapePressed: close()

    // the sheet grows out of the button that opened it, and shrinks back into it
    property real originX: width / 2
    property real originY: height / 2
    function open(source) {
        if (source) { var p = source.mapToItem(root, source.width / 2, source.height / 2); originX = p.x; originY = p.y }
        folders = Backend.directories()
        backups = Backend.backups()
        themes = Backend.themes()
        var c = themes.filter(function(t) { return t.id === "custom" })[0]
        if (c) { customAccent = c.accent; customHighlight = c.highlight }
        reloadCustom()
        hw = Backend.hardware()
        coreSetting = Backend.setting("core") || "auto"
        levelSetting = Backend.setting("upscale_level") || "auto"
        visible = true
        forceActiveFocus()
        hide.stop(); show.restart()
    }
    function close() { if (visible && !hide.running) { show.stop(); hide.restart() } }
    function set(key, value) { Backend.setSetting(key, value); if (key === "core") coreSetting = value; else levelSetting = value }
    NumberAnimation { id: show; target: root; property: "shown"; to: 1; duration: 380 * Theme.motion; easing.type: Easing.OutQuint }
    NumberAnimation { id: hide; target: root; property: "shown"; to: 0; duration: 260 * Theme.motion; easing.type: Easing.InOutCubic
        onFinished: { root.visible = false; Backend.reload() } }

    component Heading: ColumnLayout {
        property string title
        property string sub
        Layout.fillWidth: true
        spacing: 4
        Text { text: parent.title; color: Theme.text; font.pixelSize: 18; font.weight: Font.Bold; font.letterSpacing: -0.3 }
        Text { visible: parent.sub !== ""; text: parent.sub; color: Theme.faint; font.pixelSize: 12; wrapMode: Text.Wrap; Layout.fillWidth: true }
    }
    component Caption: Text { color: Theme.faint; font.family: Theme.mono; font.pixelSize: 11; Layout.topMargin: 6; Layout.fillWidth: true; wrapMode: Text.Wrap }

    Rectangle { anchors.fill: parent; color: Theme.scrim; opacity: root.shown }
    MouseArea { anchors.fill: parent; onClicked: root.close(); onWheel: (w) => w.accepted = true }

    Rectangle {
        id: sheet
        anchors.centerIn: parent
        width: Math.min(root.width - 48, Math.max(980, Math.min(1500, root.width * 0.7)))
        height: Math.min(root.height - 48, Math.max(680, Math.min(1100, root.height * 0.82)))
        radius: 16
        color: Theme.graphite
        border.color: Theme.line
        clip: true
        opacity: Math.min(1, root.shown * 1.5)
        transform: Scale { origin.x: root.originX - sheet.x; origin.y: root.originY - sheet.y; xScale: 0.06 + 0.94 * root.shown; yScale: xScale }
        MouseArea { anchors.fill: parent }

        // ---- section list
        Rectangle {
            id: nav
            width: sheet.width < 820 ? 200 : 240
            height: parent.height
            color: "#66000000"
            radius: sheet.radius
            Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.line }
            ColumnLayout {
                anchors { fill: parent; margins: 18 }
                spacing: 6
                Row {
                    Layout.bottomMargin: 16
                    spacing: 10
                    Rectangle { width: 36; height: 36; radius: 11; color: Theme.fillHover; border.color: Theme.lineStrong
                        Text { anchors.centerIn: parent; text: "⚙"; color: Theme.green; font.pixelSize: 16 } }
                    Column {
                        anchors.verticalCenter: parent.verticalCenter
                        Text { text: "Vault Settings"; color: Theme.text; font.pixelSize: 14; font.weight: Font.ExtraBold }
                        Text { text: "Changes save as you go"; color: Theme.faint; font.family: Theme.mono; font.pixelSize: 10 }
                    }
                }
                Repeater {
                    model: root.sections
                    Rectangle {
                        readonly property bool on: root.section === index
                        Layout.fillWidth: true; height: 38; radius: 12
                        color: on ? Qt.rgba(1, 1, 1, 0.15) : (navArea.containsMouse ? Theme.fill : "transparent")
                        border.color: on ? Theme.line : "transparent"
                        Row {
                            anchors { left: parent.left; leftMargin: 8; verticalCenter: parent.verticalCenter }
                            spacing: 10
                            SettingsIcon { tint: modelData[1]; kind: modelData[2]; anchors.verticalCenter: parent.verticalCenter }
                            Text { text: modelData[0]; anchors.verticalCenter: parent.verticalCenter
                                color: parent.parent.on ? Theme.text : Theme.faint; font.pixelSize: 12; font.weight: Font.DemiBold }
                        }
                        Badge { count: modelData[0] === "About & Updates" ? Backend.updateCount : 0
                            anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } }
                        MouseArea { id: navArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.section = index }
                    }
                }
                Item { Layout.fillHeight: true }
                Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }
                Text { Layout.fillWidth: true; text: "PLAYBACK  " + Backend.deviceInfo; color: Theme.faint; font.family: Theme.mono; font.pixelSize: 10; wrapMode: Text.Wrap; lineHeight: 1.3 }
            }
        }

        // ---- section body
        Flickable {
            id: flick
            SmoothWheel { view: flick; step: 160 }
            anchors { left: nav.right; right: parent.right; top: parent.top; bottom: parent.bottom; leftMargin: 28; rightMargin: 16; topMargin: 26; bottomMargin: 24 }
            contentHeight: body.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}
            onVisibleChanged: contentY = 0
            Connections { target: root; function onSectionChanged() { flick.contentY = 0; swap.restart() } }
            ParallelAnimation {     // a new section slides up a touch and fades in, like a macOS settings pane
                id: swap
                NumberAnimation { target: body; property: "opacity"; from: 0; to: 1; duration: 220 * Theme.motion; easing.type: Easing.OutCubic }
                NumberAnimation { target: bodyShift; property: "y"; from: 10; to: 0; duration: 260 * Theme.motion; easing.type: Easing.OutCubic }
            }
            ColumnLayout {
                id: body
                transform: Translate { id: bodyShift }
                width: flick.width - 14
                spacing: 12

                // Appearance
                ColumnLayout {
                    visible: root.sectionName === "Appearance"
                    Layout.fillWidth: true
                    spacing: 12
                    Heading { title: "Appearance"; sub: "Dark colourways for your shelf. They apply right away."; Layout.rightMargin: 48 }
                    GridLayout {
                        Layout.fillWidth: true
                        columns: body.width > 560 ? 2 : 1
                        rowSpacing: 10; columnSpacing: 10
                        Repeater {
                            model: root.themes
                            Rectangle {
                                readonly property bool on: modelData.id === Theme.theme
                                Layout.fillWidth: true
                                implicitHeight: 76
                                radius: 12
                                color: on ? Qt.rgba(1, 1, 1, 0.08) : (themeArea.containsMouse ? Theme.fill : "#66000000")
                                border.color: on ? "#66FFFFFF" : Theme.line
                                border.width: on ? 1.5 : 1
                                scale: themeArea.pressed ? 0.98 : 1
                                Behavior on scale { NumberAnimation { duration: 120 * Theme.motion } }
                                Row {          // swatches: page, accent, highlight
                                    id: swatches
                                    anchors { left: parent.left; leftMargin: 14; verticalCenter: parent.verticalCenter }
                                    spacing: -7
                                    Repeater {
                                        model: modelData.id === "custom" ? [modelData.page, root.customAccent, root.customHighlight]
                                                                         : [modelData.page, modelData.accent, modelData.highlight]
                                        Rectangle { width: 24; height: 24; radius: 12; color: modelData; border.color: "#40FFFFFF"; border.width: 1.5 }
                                    }
                                }
                                Column {
                                    anchors { left: swatches.right; leftMargin: 14; right: parent.right; rightMargin: 34; verticalCenter: parent.verticalCenter }
                                    spacing: 3
                                    Text { width: parent.width; text: modelData.name; color: "#FFFFFF"; font.pixelSize: 13; font.weight: Font.Bold; elide: Text.ElideRight }
                                    Text { width: parent.width; text: modelData.tagline; color: Theme.faint; font.pixelSize: 11; wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight }
                                }
                                Rectangle {
                                    visible: parent.on
                                    anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
                                    width: 20; height: 20; radius: 10; color: modelData.accent
                                    Text { anchors.centerIn: parent; text: "\u2713"; color: Qt.color(modelData.accent).hslLightness > 0.6 ? "#000000" : "#FFFFFF"; font.pixelSize: 11; font.weight: Font.Bold }
                                }
                                MouseArea { id: themeArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                    onClicked: if (!parent.on) root.themeChosen(modelData.id) }
                            }
                        }
                    }
                
                    Toggle {
                        Layout.fillWidth: true
                        Layout.topMargin: 6
                        text: "Animated colours"
                        hint: "The page softly takes on the colours of the poster or featured title you are looking at."
                        checked: Backend.setting("animated_theme") !== "0"
                        onToggled: Backend.setSetting("animated_theme", checked ? "1" : "0")
                    }
                    // Custom theme: pick its two colours on a wheel. Picking switches to Custom right away.
                    Caption { text: "CUSTOM COLOURS" }
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: customRow.implicitHeight + 28
                        radius: 12; color: Theme.slate; border.color: Theme.line
                        RowLayout {
                            id: customRow
                            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 14 }
                            spacing: 20
                            ColorWheel {
                                id: wheel
                                Layout.preferredWidth: 180
                                Layout.alignment: Qt.AlignTop
                                color: root.customValue(root.editing)
                                onPicked: (c) => {
                                    var m = Object.assign({}, root.customMap); m[root.editing] = c.toString().toUpperCase(); root.customMap = m
                                    if (root.editing === "custom_accent") root.customAccent = c
                                    if (root.editing === "custom_highlight") root.customHighlight = c
                                    commitColour.restart()
                                }
                                Timer {          // the whole UI recolours, so at most ~12 times a second while dragging
                                    id: commitColour
                                    interval: 80
                                    onTriggered: Backend.setSetting(root.editing, root.customValue(root.editing))
                                }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                Layout.alignment: Qt.AlignTop
                                spacing: 8
                                // every colour of the theme: tap one, then drag on the wheel
                                GridLayout {
                                    Layout.fillWidth: true
                                    columns: customRow.width > 760 ? 3 : 2
                                    rowSpacing: 6; columnSpacing: 6
                                    Repeater {
                                        model: root.customColours
                                        Rectangle {
                                            readonly property bool on: root.editing === modelData.key
                                            readonly property color swatch: root.customValue(modelData.key)
                                            Layout.fillWidth: true
                                            Layout.preferredWidth: 1
                                            implicitHeight: 48
                                            radius: 10
                                            color: on ? Qt.rgba(1, 1, 1, 0.08) : "transparent"
                                            border.color: on ? "#66FFFFFF" : Theme.line
                                            Rectangle { id: chip; x: 10; anchors.verticalCenter: parent.verticalCenter; width: 24; height: 24; radius: 12; color: parent.swatch; border.color: "#40FFFFFF" }
                                            Column {
                                                anchors { left: chip.right; leftMargin: 10; right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter }
                                                spacing: 1
                                                Text { width: parent.width; text: modelData.name + "  " + parent.parent.swatch.toString().toUpperCase(); color: Theme.text; font.pixelSize: 12; font.weight: Font.Bold; elide: Text.ElideRight }
                                                Text { width: parent.width; text: modelData.role; color: Theme.faint; font.pixelSize: 10; elide: Text.ElideRight }
                                            }
                                            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.editing = modelData.key }
                                        }
                                    }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text { Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.faint; font.pixelSize: 11
                                        text: "Choose a colour, then drag on the wheel; the slider sets brightness. Picking one switches to the Custom theme." }
                                    GlassButton { small: true; label: "Reset colours"
                                        onClicked: { root.customColours.forEach(function(c) { Backend.setSetting(c.key, "") }); root.reloadCustom() } }
                                }
                            }
                        }
                    }
                }

                // Appearance: order of the sections in View More
                ColumnLayout {
                    visible: root.sectionName === "Appearance"
                    Layout.fillWidth: true
                    Layout.topMargin: 10
                    spacing: 8
                    RowLayout {
                        Layout.fillWidth: true
                        Caption { text: "VIEW MORE LAYOUT"; Layout.fillWidth: true }
                        GlassButton { small: true; label: "Reset"; onClicked: { Backend.setSetting("detail_order", ""); layoutModel.load() } }
                    }
                    Text { Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.faint; font.pixelSize: 11
                        text: "The order of the sections beside the box: drag a row to move it. Sections that do not apply to a title (actors for a home video, say) are skipped." }
                    ListModel {
                        id: layoutModel
                        function load() { clear(); Backend.detailSections().forEach(function(x) { append(x) }) }
                        function save() { var ids = []; for (var i = 0; i < count; i++) ids.push(get(i).id); Backend.setSetting("detail_order", ids.join(",")) }
                        Component.onCompleted: load()
                    }
                    ListView {
                        id: layoutList
                        Layout.fillWidth: true
                        Layout.preferredHeight: layoutModel.count * 44
                        interactive: false
                        model: layoutModel
                        spacing: 4
                        // rows glide to their new places
                        move: Transition { NumberAnimation { properties: "y"; duration: 240 * Theme.motion; easing.type: Easing.OutCubic } }
                        moveDisplaced: Transition { NumberAnimation { properties: "y"; duration: 240 * Theme.motion; easing.type: Easing.OutCubic } }
                        // drag a row anywhere to move it; the others glide out of the way (arrows still work)
                        delegate: Item {
                            id: rowWrap
                            width: layoutList.width; height: 40
                            z: rowDrag.drag ? 10 : 0
                            Rectangle {
                                id: rowCard
                                width: parent.width; height: 40; radius: 10
                                // while dragged it follows the pointer, wherever the list has moved its slot to
                                y: rowDrag.drag ? rowDrag.pointerY - rowDrag.grabY - rowWrap.y : 0
                                color: rowDrag.drag ? Theme.fillHover : Theme.slate
                                border.color: rowDrag.drag ? Theme.blue : Theme.line
                                scale: rowDrag.drag ? 1.02 : 1
                                Behavior on scale { NumberAnimation { duration: 120 * Theme.motion } }
                                Text { x: 14; anchors.verticalCenter: parent.verticalCenter; text: "\u2261"; color: Theme.faint; font.pixelSize: 16 }
                                Text { x: 34; anchors.verticalCenter: parent.verticalCenter; text: (index + 1) + "."; color: Theme.faint; font.family: Theme.mono; font.pixelSize: 11 }
                                Text { x: 60; anchors.verticalCenter: parent.verticalCenter; text: model.label; color: Theme.text; font.pixelSize: 13; font.weight: Font.Medium }
                                MouseArea {
                                    id: rowDrag
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    preventStealing: true
                                    cursorShape: drag ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                                    property bool drag: false
                                    property real grabY: 0
                                    property real pointerY: 0
                                    onPressed: (m) => { var p = mapToItem(layoutList, m.x, m.y); grabY = p.y - rowWrap.y; pointerY = p.y; drag = true }
                                    onPositionChanged: (m) => {
                                        if (!drag) return
                                        pointerY = mapToItem(layoutList, m.x, m.y).y
                                        var to = Math.max(0, Math.min(layoutModel.count - 1, Math.round((pointerY - grabY) / (40 + layoutList.spacing))))
                                        if (to !== index) layoutModel.move(index, to, 1)
                                    }
                                    onReleased: { if (drag) { drag = false; layoutModel.save() } }
                                    onCanceled: { drag = false; layoutModel.save() }
                                }
                                Tip { visible: rowDrag.containsMouse && !rowDrag.drag; delay: 700; text: "Drag to reorder" }
                                Row {
                                    anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter }
                                    spacing: 4
                                    GlassButton { small: true; label: "\u2191"; implicitWidth: 32; enabled: index > 0; opacity: enabled ? 1 : 0.3
                                        tip: "Move up"; onClicked: { layoutModel.move(index, index - 1, 1); layoutModel.save() } }
                                    GlassButton { small: true; label: "\u2193"; implicitWidth: 32; enabled: index < layoutModel.count - 1; opacity: enabled ? 1 : 0.3
                                        tip: "Move down"; onClicked: { layoutModel.move(index, index + 1, 1); layoutModel.save() } }
                                }
                            }
                        }
                    }
                }

                // Playback
                ColumnLayout {
                    visible: root.sectionName === "Playback"
                    Layout.fillWidth: true
                    spacing: 12
                    Heading { title: "Playback"; sub: "Media Vault looks at this PC and picks the video engine and upscaling for you. Override either one if you like."; Layout.rightMargin: 48 }
                    Rectangle {        // what was detected
                        Layout.fillWidth: true
                        implicitHeight: specs.implicitHeight + 28
                        radius: 12; color: Theme.slate; border.color: Theme.line
                        ColumnLayout {
                            id: specs
                            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 14 }
                            spacing: 4
                            Text { text: "THIS PC"; color: Theme.faint; font.family: Theme.mono; font.pixelSize: 10 }
                            Repeater { model: root.hw.gpus || []
                                Text { Layout.fillWidth: true; text: modelData; color: "#FFFFFF"; font.pixelSize: 13; font.weight: Font.DemiBold; elide: Text.ElideRight } }
                            Text { text: (root.hw.ram || 0).toFixed(0) + " GB RAM  \u00B7  " + (root.hw.cores || 0) + " CPU threads"; color: "#B3FFFFFF"; font.family: Theme.mono; font.pixelSize: 11 }
                            Text { Layout.fillWidth: true; Layout.topMargin: 4; wrapMode: Text.Wrap; color: Theme.green; font.pixelSize: 12; font.weight: Font.DemiBold
                                text: "Recommended: " + (root.hw.core || "").toUpperCase() + " engine \u00B7 " + (root.levelNames[(root.hw.level || 1) - 1]) }
                            Text { Layout.fillWidth: true; text: root.hw.why || ""; color: Theme.faint; font.pixelSize: 11; wrapMode: Text.Wrap }
                        }
                    }
                    Caption { text: "VIDEO ENGINE" }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 8
                        Repeater {
                            model: [["auto", "Auto (" + (root.hw.core || "").toUpperCase() + ")"], ["mpv", "MPV"], ["vlc", "VLC"]]
                            Pill { label: modelData[1]; selected: root.coreSetting === modelData[0]; accent: Theme.blue; onClicked: root.set("core", modelData[0]) }
                        }
                    }
                    Caption { text: "UPSCALING" }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 8
                        Repeater {
                            model: [["auto", "Auto (" + root.levelNames[(root.hw.level || 1) - 1] + ")"], ["1", "1. Standard"], ["2", "2. High Quality"], ["3", "3. AI Ultra"]]
                            Pill { label: modelData[1]; selected: root.levelSetting === modelData[0]; accent: Theme.blue; onClicked: root.set("upscale_level", modelData[0]) }
                        }
                    }
                    Text {             // say plainly when an override cannot do what it says
                        Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.amber; font.pixelSize: 12
                        readonly property string core: root.coreSetting === "auto" ? (root.hw.core || "") : root.coreSetting
                        readonly property int level: root.levelSetting === "auto" ? (root.hw.level || 1) : parseInt(root.levelSetting)
                        visible: text !== ""
                        text: core === "vlc" && level > 1 ? "Upscaling levels need the MPV engine; VLC plays at Standard."
                            : level === 3 && !root.hw.rtx ? "AI Ultra needs an NVIDIA RTX GPU; this PC will play at High Quality." : ""
                    }
                    Caption { text: "SOUND AND MOTION" }
                    Toggle {
                        Layout.fillWidth: true
                        text: "Reduce loud sounds by default"
                        hint: "Night mode: evens out explosions and whispers."
                        checked: Backend.setting("night_mode") === "1"
                        onToggled: Backend.setSetting("night_mode", checked ? "1" : "0")
                    }
                    Toggle {
                        Layout.fillWidth: true
                        text: "Reduce motion"
                        hint: "Applies next launch. Windows' own animation switch is honoured too."
                        checked: Backend.setting("reduce_motion") === "1"
                        onToggled: Backend.setSetting("reduce_motion", checked ? "1" : "0")
                    }
                    Caption { text: "SERIES" }
                    Toggle {
                        Layout.fillWidth: true
                        text: "Start the next episode when the credits start"
                        hint: "Found from chapter names, or press O in the player where the credits begin; it is remembered for the series."
                        checked: Backend.setting("auto_credits") !== "0"
                        onToggled: Backend.setSetting("auto_credits", checked ? "1" : "0")
                    }
                }

                // Library: the folders (each with its own Configure window), how titles read, box sets, and tags
                ColumnLayout {
                    visible: root.sectionName === "Library"
                    Layout.fillWidth: true
                    spacing: 10
                    Heading { title: "Library"; sub: "Your folders, how titles read, box sets and tags. Each folder is a tab, in this order (drag the tabs in the top bar, or use the arrows); Configure holds everything about one folder."; Layout.rightMargin: 48 }

                    Caption { text: "FOLDERS" }
                    Repeater {
                        model: root.folders
                        Rectangle {
                            id: folderCard
                            Layout.fillWidth: true
                            implicitHeight: 64
                            radius: 12; color: Theme.slate; border.color: Theme.line
                            RowLayout {
                                anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 14; rightMargin: 10 }
                                spacing: 10
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: 0           // never pushes the buttons out; the name elides instead
                                    spacing: 3
                                    // the name gets the whole line; what the folder is sits under it, beside its path
                                    Text { Layout.fillWidth: true; text: modelData.name; color: Theme.text; font.pixelSize: 14; font.weight: Font.Bold; elide: Text.ElideRight }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 6
                                        Repeater {
                                            model: [modelData.scrape ? (modelData.anime ? "Anime \u00B7 AniList" : "TMDB") : "Not scraped",
                                                    modelData.inAll ? "" : "Not in All", modelData.inInsights ? "" : "Not in Insights"].filter(function(t) { return t !== "" })
                                            Rectangle { implicitWidth: chip.implicitWidth + 12; implicitHeight: 18; radius: 5; color: "transparent"; border.color: Theme.lineStrong
                                                Text { id: chip; anchors.centerIn: parent; text: modelData; color: Theme.muted; font.family: Theme.mono; font.pixelSize: 9 } }
                                        }
                                        Text { Layout.fillWidth: true; Layout.leftMargin: 2; text: modelData.path || ""; color: Theme.faint; font.family: Theme.mono; font.pixelSize: 10; elide: Text.ElideMiddle }
                                    }
                                }
                                // tab order (the tabs can also be dragged in the top bar)
                                GlassButton { small: true; label: "\u2191"; implicitWidth: 30; enabled: index > 0; opacity: enabled ? 1 : 0.3
                                    tip: "Move this tab left (or drag the tabs in the top bar)"
                                    onClicked: { Backend.moveTab(modelData.id, index - 1); root.folders = Backend.directories() } }
                                GlassButton { small: true; label: "\u2193"; implicitWidth: 30; enabled: index < root.folders.length - 1; opacity: enabled ? 1 : 0.3
                                    tip: "Move this tab right"
                                    onClicked: { Backend.moveTab(modelData.id, index + 1); root.folders = Backend.directories() } }
                                GlassButton { id: configBtn; small: true; label: "Configure"; tip: "Name, scraping, anime, tagging, and where it shows"
                                    onClicked: root.configureFolder(modelData.id, configBtn) }
                            }
                        }
                    }
                    Text { visible: root.folders.length === 0; text: "No folders yet."; color: Theme.faint; font.pixelSize: 13 }
                    GlassButton { small: true; label: "Add folder"; glyph: "+"; onClicked: Backend.pickFolder() }

                    Caption { text: "TITLES"; Layout.topMargin: 10 }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 14
                        Rectangle {      // English | Romaji | Original
                            id: titleSeg
                            property string value: Backend.setting("title_language") || "english"
                            implicitWidth: 300; implicitHeight: 34; radius: 10; color: "#99000000"; border.color: Theme.line
                            Rectangle { width: (parent.width - 6) / 3; height: parent.height - 6; y: 3; radius: 8; color: Theme.text
                                x: 3 + width * ["english", "romaji", "original"].indexOf(titleSeg.value)
                                Behavior on x { NumberAnimation { duration: 240 * Theme.motion; easing.type: Easing.OutCubic } } }
                            Row {
                                anchors { fill: parent; margins: 3 }
                                Repeater {
                                    model: [["english", "English"], ["romaji", "Romaji"], ["original", "Original"]]
                                    Item {
                                        width: parent.width / 3; height: parent.height
                                        Text { anchors.centerIn: parent; text: modelData[1]; font.pixelSize: 12; font.weight: Font.Bold
                                            color: titleSeg.value === modelData[0] ? Theme.black : Theme.muted }
                                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                            onClicked: { titleSeg.value = modelData[0]; Backend.setSetting("title_language", modelData[0]) } }
                                    }
                                }
                            }
                        }
                        Text { Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.faint; font.pixelSize: 11
                            text: titleSeg.value === "original" ? "Titles in their own language and alphabet (\u5343\u3068\u5343\u5C0B\u306E\u795E\u96A0\u3057), with the English title in small underneath."
                                : titleSeg.value === "romaji" ? "Anime in Latin letters (Sen to Chihiro no Kamikakushi), with the original underneath. Others stay in English."
                                : "English titles, with the original in small underneath when it is different. Every version is searchable." }
                    }

                    Caption { text: "BOX SETS"; Layout.topMargin: 10 }
                    Toggle {
                        Layout.fillWidth: true
                        text: "Group films into box sets"
                        hint: "Films of the same series share one card when a tab has two or more of them (also the Box sets pill on the dashboard)"
                        checked: Backend.setting("group_collections") !== "0"
                        onToggled: Backend.setSetting("group_collections", checked ? "1" : "0")
                    }

                    Caption { text: "TAGS"; Layout.topMargin: 10 }
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: tagCardRow.implicitHeight + 28
                        radius: 12; color: Theme.slate; border.color: Theme.line
                        RowLayout {
                            id: tagCardRow
                            anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 14 }
                            spacing: 14
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 3
                                Text { text: "Tag Manager"; color: Theme.text; font.pixelSize: 14; font.weight: Font.Bold }
                                Text { Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.faint; font.pixelSize: 11
                                    text: "Tag many titles at once, rename or merge tags, choose which stay out of the All tab, and write rules like \u201Cif the file name contains Remux, tag it Remux\u201D." }
                            }
                            GlassButton { id: tagMgrBtn; label: "Open Tag Manager"; primary: true; onClicked: root.openTagManager(tagMgrBtn) }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12
                        Toggle {
                            Layout.fillWidth: true
                            text: "Tag titles from their folders and file names"
                            hint: "Sub-folders (Action, Kids ...), 4K / HDR, Remux / Blu-ray / Web, codec, Atmos / DTS, editions, 3D, the decade, the age rating"
                            checked: Backend.setting("auto_tags") !== "0"
                            onToggled: Backend.setSetting("auto_tags", checked ? "1" : "0")
                        }
                        GlassButton { small: true; label: "Work out tags again"; tip: "Names, age ratings and your rules, for the whole library"
                            onClicked: Backend.applyTagRules() }
                    }
                }

                // Library health
                ColumnLayout {
                    visible: root.sectionName === "Library Status"
                    Layout.fillWidth: true
                    spacing: 10
                    component IgnoreButtons: Row {
                        property string kind
                        property string key
                        spacing: 6
                        GlassButton { small: true; label: "Ignore for now"; onClicked: { Backend.ignoreIssue(parent.kind, parent.key, false); root.refreshHealth() } }
                        GlassButton { small: true; label: "Ignore forever"; onClicked: { Backend.ignoreIssue(parent.kind, parent.key, true); root.refreshHealth() } }
                    }
                    component Card: Rectangle {
                        default property alias body: inner.data
                        Layout.fillWidth: true
                        implicitHeight: inner.implicitHeight + 24
                        radius: 12; color: Theme.slate; border.color: Theme.line
                        ColumnLayout { id: inner; anchors { left: parent.left; right: parent.right; top: parent.top; margins: 12 } spacing: 6 }
                    }
                    Heading { title: "Library Status"; sub: "Copies you have twice, gaps in series, titles without a cover, and folders that cannot be reached. Nothing is ever deleted from here."; Layout.rightMargin: 48 }
                    Row {
                        spacing: 8
                        GlassButton { small: true; label: "Check again"; glyph: "\u21BB"; onClicked: root.refreshHealth() }
                        GlassButton { small: true; label: "Show ignored items again"; onClicked: { Backend.resetIgnored(); root.refreshHealth() } }
                    }

                    Caption { text: "FOLDERS" }
                    Repeater {
                        model: root.report.folders || []
                        Card {
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 10
                                Rectangle { width: 10; height: 10; radius: 5; color: modelData.online ? (modelData.missing ? Theme.amber : Theme.green) : Theme.red }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2
                                    Text { text: modelData.name; color: "#FFFFFF"; font.pixelSize: 13; font.weight: Font.Bold }
                                    Text { Layout.fillWidth: true; text: modelData.path; color: "#66FFFFFF"; font.family: Theme.mono; font.pixelSize: 10; elide: Text.ElideMiddle }
                                }
                                Text {
                                    color: modelData.online ? (modelData.missing ? Theme.amber : Theme.faint) : Theme.red; font.pixelSize: 12; font.weight: Font.DemiBold
                                    text: !modelData.online ? "Offline: titles kept, greyed out" : modelData.missing ? modelData.missing + " of " + modelData.titles + " files missing" : modelData.titles + " titles, all present"
                                }
                            }
                            Repeater { model: modelData.examples || []
                                Text { Layout.fillWidth: true; text: modelData; color: Theme.faint; font.family: Theme.mono; font.pixelSize: 10; elide: Text.ElideMiddle } }
                        }
                    }

                    Caption { text: "DUPLICATES" + ((root.report.duplicates || []).length ? "  \u00B7  " + root.report.duplicates.length : "") }
                    Text { visible: (root.report.duplicates || []).length === 0; text: "No title is in the library twice."; color: Theme.faint; font.pixelSize: 12 }
                    Repeater {
                        model: root.report.duplicates || []
                        Card {
                            readonly property var group: modelData
                            Text { text: group.title; color: "#FFFFFF"; font.pixelSize: 13; font.weight: Font.Bold; Layout.fillWidth: true; elide: Text.ElideRight }
                            Repeater {
                                model: group.files
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 8
                                    Rectangle { visible: modelData.best; implicitWidth: bestText.implicitWidth + 10; implicitHeight: 18; radius: 4; color: Theme.green
                                        Text { id: bestText; anchors.centerIn: parent; text: "BEST"; color: Theme.onGreen; font.family: Theme.mono; font.pixelSize: 9; font.weight: Font.Bold } }
                                    Text { text: modelData.resolution + (modelData.codec ? "  " + modelData.codec : "") + "  \u00B7  " + (modelData.sizeMb >= 1024 ? (modelData.sizeMb / 1024).toFixed(1) + " GB" : modelData.sizeMb + " MB")
                                        color: "#D9FFFFFF"; font.family: Theme.mono; font.pixelSize: 11 }
                                    Text { Layout.fillWidth: true; text: modelData.path; color: "#66FFFFFF"; font.family: Theme.mono; font.pixelSize: 10; elide: Text.ElideMiddle }
                                    GlassButton { small: true; label: "Show in folder"; onClicked: Backend.showInFolder(modelData.path) }
                                }
                            }
                            IgnoreButtons { kind: "duplicate"; key: group.key }
                        }
                    }

                    Caption { text: "MISSING EPISODES" + ((root.report.episodes || []).length ? "  \u00B7  " + root.report.episodes.length : "") }
                    Text { visible: (root.report.episodes || []).length === 0; text: "No gaps in any season."; color: Theme.faint; font.pixelSize: 12 }
                    Repeater {
                        model: root.report.episodes || []
                        Card {
                            readonly property var show: modelData
                            Text { text: show.title; color: "#FFFFFF"; font.pixelSize: 13; font.weight: Font.Bold }
                            Flow {
                                Layout.fillWidth: true; spacing: 5
                                Repeater { model: show.missing
                                    Rectangle { implicitWidth: epText.implicitWidth + 12; implicitHeight: 22; radius: 6; color: "#99000000"; border.color: Theme.line
                                        Text { id: epText; anchors.centerIn: parent; text: modelData; color: Theme.amber; font.family: Theme.mono; font.pixelSize: 10 } } }
                            }
                            IgnoreButtons { kind: "missing_episode"; key: show.key }
                        }
                    }

                    Caption { text: "MISSING ARTWORK" + ((root.report.artwork || []).length ? "  \u00B7  " + root.report.artwork.length : "") }
                    Text { visible: (root.report.artwork || []).length === 0; text: "Every title has a cover."; color: Theme.faint; font.pixelSize: 12 }
                    Repeater {
                        model: root.report.artwork || []
                        Card {
                            RowLayout {
                                Layout.fillWidth: true
                                Text { Layout.fillWidth: true; text: modelData.title; color: "#FFFFFF"; font.pixelSize: 13; font.weight: Font.Bold; elide: Text.ElideRight }
                                GlassButton { small: true; label: "Add cover\u2026"; onClicked: Backend.pickBoxArt(modelData.key, "front") }
                            }
                            IgnoreButtons { kind: "missing_art"; key: modelData.key }
                        }
                    }
                }

                // Integrations
                ColumnLayout {
                    visible: root.sectionName === "Integrations & APIs"
                    Layout.fillWidth: true
                    spacing: 10
                    Heading { title: "Integrations & APIs"; sub: "Keys stay on this PC. TMDB is used first, OMDb only when TMDB has nothing; fanart.tv adds disc art."; Layout.rightMargin: 48 }
                    Caption { text: "TMDB API KEY" }
                    Field { Layout.fillWidth: true; placeholderText: "Paste your TMDB key"; echoMode: TextInput.Password; text: Backend.setting("tmdb_key"); onActiveFocusChanged: if (!activeFocus) Backend.setSetting("tmdb_key", text) }
                    Caption { text: "OMDB API KEY (FALLBACK)" }
                    Field { Layout.fillWidth: true; placeholderText: "Paste your OMDb key"; echoMode: TextInput.Password; text: Backend.setting("omdb_key"); onActiveFocusChanged: if (!activeFocus) Backend.setSetting("omdb_key", text) }
                    Caption { text: "FANART.TV API KEY (DISC ART FOR FILMS)" }
                    Field { Layout.fillWidth: true; placeholderText: "Paste your fanart.tv key"; echoMode: TextInput.Password; text: Backend.setting("fanart_key"); onActiveFocusChanged: if (!activeFocus) Backend.setSetting("fanart_key", text) }
                    Text { Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.faint; font.pixelSize: 11
                        text: "Without it (or for series, which fanart.tv has no discs for) the disc shows the cover. Your own disc art always wins: View More \u203A Box art \u203A Disc." }
                    Caption { text: "DISCORD"; Layout.topMargin: 8 }
                    Toggle {
                        id: discordOn
                        Layout.fillWidth: true
                        text: "Show what you\u2019re watching on Discord"
                        hint: "Needs the Discord app running on this PC. Home videos never show their name."
                        checked: Backend.setting("discord") === "1"
                        onToggled: { Backend.setSetting("discord", checked ? "1" : "0"); root.discordState = Backend.discordStatus() }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        visible: discordOn.checked
                        spacing: 8
                        Flow {
                            Layout.fillWidth: true
                            spacing: 6
                            Repeater {
                                model: [["minimal", "Just \u201CWatching a movie\u201D"], ["title", "Title"], ["full", "Title and time left"]]
                                Pill { label: modelData[1]; accent: Theme.blue; selected: root.discordDetail === modelData[0]
                                    onClicked: { root.discordDetail = modelData[0]; Backend.setSetting("discord_detail", modelData[0]) } }
                            }
                        }
                        // your own wording for the two lines, with a live preview of a film and an episode
                        Caption { text: "STATUS TEXT  \u00B7  {title}  {year}  {episode}  {type}"; visible: root.discordDetail !== "minimal" }
                        RowLayout {
                            Layout.fillWidth: true
                            visible: root.discordDetail !== "minimal"
                            spacing: 8
                            Field { id: dLine1; Layout.fillWidth: true; placeholderText: "{title} ({year})"; text: Backend.setting("discord_details")
                                onTextEdited: root.discordPreview = Backend.discordPreview(text, dLine2.text, root.discordPaused)
                                onActiveFocusChanged: if (!activeFocus) Backend.setSetting("discord_details", text) }
                            Field { id: dLine2; Layout.fillWidth: true; placeholderText: "{episode}"; text: Backend.setting("discord_state")
                                onTextEdited: root.discordPreview = Backend.discordPreview(dLine1.text, text, root.discordPaused)
                                onActiveFocusChanged: if (!activeFocus) Backend.setSetting("discord_state", text) }
                        }
                        // a small preview of the status card: a film, then an episode, as Discord would show them
                        Rectangle {
                            Layout.fillWidth: true
                            implicitHeight: dcol.implicitHeight + 20
                            radius: 10; color: "#2B2D31"; border.color: Theme.line
                            Row {
                                anchors { left: parent.left; leftMargin: 12; verticalCenter: parent.verticalCenter }
                                spacing: 10
                                Rectangle { width: 40; height: 40; radius: 8; color: Theme.graphite; anchors.verticalCenter: parent.verticalCenter
                                    Text { anchors.centerIn: parent; text: "\u25B6"; color: Theme.green; font.pixelSize: 14 } }
                                Column {
                                    id: dcol
                                    anchors.verticalCenter: parent.verticalCenter
                                    spacing: 1
                                    readonly property var pv: root.discordPreview
                                    Text { text: "Watching Media Vault"; color: "#F2F3F5"; font.pixelSize: 12; font.weight: Font.Bold }
                                    Text { textFormat: Text.PlainText; color: "#DBDEE1"; font.pixelSize: 12
                                        text: root.discordDetail === "minimal" ? "Watching a movie" : (dcol.pv.movie || "Blade Runner 2049 (2017)") }
                                    Text { textFormat: Text.PlainText; visible: text !== ""; color: "#B5BAC1"; font.pixelSize: 11
                                        text: root.discordDetail === "minimal" ? "" : root.discordDetail === "full" ? [dcol.pv.movieState, "45:12 elapsed"].filter(Boolean).join(" \u00B7 ")
                                                                                                               : (dcol.pv.movieState || "") }
                                    Text { textFormat: Text.PlainText; visible: root.discordDetail !== "minimal"; color: "#949BA4"; font.pixelSize: 11
                                        text: "Episode: " + [dcol.pv.show, dcol.pv.showState].filter(Boolean).join(" \u2014 ") }
                                }
                            }
                        }
                        Caption { text: "PRIVACY" }
                        Toggle {
                            Layout.fillWidth: true
                            text: "Hide adult titles"
                            hint: "Rated 18+, R18+, NC-17 or X, or a Hentai / Erotica genre: Discord only sees \u201CWatching a video\u201D."
                            checked: Backend.setting("discord_hide_adult") !== "0"
                            onToggled: Backend.setSetting("discord_hide_adult", checked ? "1" : "0")
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 1
                                Text { text: "When paused"; color: Theme.text; font.pixelSize: 13 }
                                Text { Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.faint; font.pixelSize: 11
                                    text: "Show \u201CPaused\u201D, or clear the status until you play again." }
                            }
                            Repeater {
                                model: [["show", "Show Paused"], ["clear", "Clear status"]]
                                Pill { label: modelData[1]; accent: Theme.blue; selected: root.discordPaused === modelData[0]
                                    onClicked: { root.discordPaused = modelData[0]; Backend.setSetting("discord_paused", modelData[0]) } }
                            }
                        }
                        // tags whose titles only ever show "Watching a video"
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 6
                            Text { text: "Never name titles tagged"; color: Theme.text; font.pixelSize: 13 }
                            Flow {
                                Layout.fillWidth: true
                                spacing: 6
                                Repeater {
                                    model: root.discordHidden.tags || []
                                    Pill { label: (modelData.indexOf(":") > 0 ? modelData.split(":")[1] : modelData) + "   \u00D7"; selected: true; accent: Theme.red
                                        onClicked: { Backend.setDiscordHiddenTag(modelData, false); root.discordHidden = Backend.discordPrivacy() } }
                                }
                                Dropdown {
                                    width: 200
                                    prefix: "+ "
                                    options: [{ value: "", label: "Add a tag" }].concat(Backend.allTags().filter(function(t) {
                                        return (root.discordHidden.tags || []).indexOf(t.name) < 0 }).map(function(t) { return { value: t.name, label: t.label } }))
                                    value: ""
                                    onChosen: (v) => { if (v !== "") { Backend.setDiscordHiddenTag(v, true); root.discordHidden = Backend.discordPrivacy() } value = "" }
                                }
                            }
                            Text { Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.faint; font.pixelSize: 11
                                text: "Whole folders can show less, or nothing: Library \u203A Configure \u203A Discord." }
                        }
                        Caption { text: "IMAGE TOOLTIP" }
                        Field { Layout.fillWidth: true; placeholderText: "Media Vault"; text: Backend.setting("discord_image_text")
                            onActiveFocusChanged: if (!activeFocus) Backend.setSetting("discord_image_text", text) }
                        Caption { text: "DISCORD APPLICATION ID" }
                        Field { Layout.fillWidth: true; placeholderText: "From discord.com/developers \u203A Applications \u203A New (name it Media Vault)"
                            text: Backend.setting("discord_app_id"); validator: RegularExpressionValidator { regularExpression: /[0-9]{0,24}/ }
                            onActiveFocusChanged: if (!activeFocus) { Backend.setSetting("discord_app_id", text); root.discordState = Backend.discordStatus() } }
                        Row {
                            spacing: 6
                            Rectangle { width: 8; height: 8; radius: 4; anchors.verticalCenter: parent.verticalCenter
                                color: root.discordState === "Connected" ? Theme.green : root.discordState.indexOf("Needs") === 0 ? Theme.amber : Theme.faint }
                            Text { text: root.discordState; color: Theme.muted; font.pixelSize: 12 }
                        }
                        Timer { interval: 2000; repeat: true; running: root.visible && root.sectionName === "Integrations & APIs" && discordOn.checked
                            onTriggered: root.discordState = Backend.discordStatus() }
                    }
                    Caption { text: "WINDOWS"; Layout.topMargin: 8 }
                    Toggle {
                        Layout.fillWidth: true
                        text: "Offer Media Vault in “Open with”"
                        hint: ".mp4  .mkv  .avi"
                        checked: Backend.fileTypesOn()       // what Windows has now, not a remembered guess
                        onToggled: Backend.setFileTypes(checked)
                    }
                }

                // Streaming
                ColumnLayout {
                    visible: root.sectionName === "Streaming"
                    Layout.fillWidth: true
                    spacing: 10
                    Heading { title: "Streaming"; sub: "Watch on a phone, tablet or TV. Media Vault serves the files from this PC; nothing is uploaded anywhere."; Layout.rightMargin: 48 }

                    Caption { text: "ANY BROWSER ON THIS WI-FI" }
                    Toggle {
                        Layout.fillWidth: true
                        text: "Share the library on this network"
                        hint: "Anyone on your network who has the link can watch. The link gets a new secret every time you switch this on, and sharing is off again when Media Vault restarts."
                        checked: Backend.streamUrl !== ""
                        onToggled: Backend.setStreaming(checked)
                    }
                    Rectangle {
                        visible: Backend.streamUrl !== ""
                        Layout.fillWidth: true
                        implicitHeight: linkRow.implicitHeight + 20
                        radius: 10; color: Theme.slate; border.color: Theme.line
                        RowLayout {
                            id: linkRow
                            anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 10 }
                            spacing: 8
                            Text { Layout.fillWidth: true; text: Backend.streamUrl; color: "#FFFFFF"; font.family: Theme.mono; font.pixelSize: 11; elide: Text.ElideMiddle }
                            GlassButton { small: true; label: "Copy link"; onClicked: Backend.copyText(Backend.streamUrl) }
                            GlassButton { small: true; label: "Open"; onClicked: Backend.openStream() }
                        }
                    }

                    Caption { text: "AIRPLAY AND CHROMECAST" }
                    Text { Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.faint; font.pixelSize: 12
                        text: "Send a title to an Apple TV, an AirPlay 2 TV, or a Chromecast / Google TV. Use Play on\u2026 in View More, or Cast in the player. MP4, MOV and WebM play everywhere; MKV and AVI may not (Apple TV refuses them)." }
                    RowLayout {
                        visible: !(root.castLibs.chromecast && root.castLibs.airplay)
                        Layout.fillWidth: true
                        Text { Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.amber; font.pixelSize: 12
                            text: "Needs two small add-ons (pyatv for AirPlay, pychromecast for Chromecast)." }
                        GlassButton { small: true; label: "Install"; onClicked: Backend.installCastSupport() }
                    }
                    Row {
                        spacing: 8
                        GlassButton { small: true; label: root.searching ? "Searching\u2026" : "Find devices"; glyph: "\u2315"
                            onClicked: { root.searching = true; Backend.findDevices() } }
                    }
                    Repeater {
                        model: root.castDevices
                        Rectangle {
                            Layout.fillWidth: true
                            implicitHeight: 48
                            radius: 10; color: Theme.slate; border.color: Theme.line
                            RowLayout {
                                anchors { fill: parent; leftMargin: 12; rightMargin: 12 }
                                spacing: 10
                                SettingsIcon { kind: "streaming"; tint: modelData.kind === "AirPlay" ? "#8E8E93" : "#4285F4" }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 1
                                    Text { text: modelData.name; color: "#FFFFFF"; font.pixelSize: 13; font.weight: Font.Bold }
                                    Text { text: modelData.kind + (modelData.model ? "  \u00B7  " + modelData.model : ""); color: Theme.faint; font.pixelSize: 11 }
                                }
                            }
                        }
                    }
                    Text { visible: !root.searching && root.castDevices.length === 0; text: "No devices found yet."; color: Theme.faint; font.pixelSize: 12 }
                }

                // Help
                ColumnLayout {
                    visible: root.sectionName === "Help"
                    Layout.fillWidth: true
                    spacing: 10
                    Heading { title: "Help"; sub: "Keyboard shortcuts and tips. Hover any button for a moment to see what it does."; Layout.rightMargin: 48 }
                    component Keycap: Rectangle {
                        property string k
                        implicitWidth: Math.max(28, capText.implicitWidth + 16); implicitHeight: 28; radius: 7
                        gradient: Gradient { GradientStop { position: 0; color: "#3A3A3C" } GradientStop { position: 1; color: "#2C2C2E" } }
                        border.color: "#4DFFFFFF"
                        Rectangle { anchors { left: parent.left; right: parent.right; bottom: parent.bottom } height: 3; radius: 7; color: "#1C1C1E"; opacity: 0.8 }
                        Text { id: capText; anchors.centerIn: parent; anchors.verticalCenterOffset: -1; text: parent.k; color: "#FFFFFF"; font.pixelSize: 12; font.weight: Font.Bold }
                    }
                    component ShortcutRow: RowLayout {
                        id: sr
                        property var keys: []
                        property string what
                        Layout.fillWidth: true
                        spacing: 4
                        Repeater { model: sr.keys; Keycap { k: modelData } }
                        Text { Layout.fillWidth: true; Layout.leftMargin: 8; text: sr.what; color: "#D9FFFFFF"; font.pixelSize: 12; wrapMode: Text.Wrap }
                    }
                    component ShortcutCard: Rectangle {
                        id: sc
                        property string title
                        property var rows: []
                        Layout.fillWidth: true
                        implicitHeight: cardCol.implicitHeight + 28
                        radius: 12; color: Theme.slate; border.color: Theme.line
                        ColumnLayout {
                            id: cardCol
                            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 14 }
                            spacing: 8
                            Text { text: sc.title; color: "#FFFFFF"; font.pixelSize: 13; font.weight: Font.Bold }
                            GridLayout {
                                Layout.fillWidth: true
                                columns: body.width > 600 ? 2 : 1
                                columnSpacing: 18; rowSpacing: 8
                                Repeater { model: sc.rows; ShortcutRow { keys: modelData[0]; what: modelData[1] } }
                            }
                        }
                    }
                    ShortcutCard {
                        title: "In the player"
                        rows: [[["Space"], "Play / pause"], [["\u2190", "\u2192"], "Back / forward 10 seconds"],
                               [["\u2191", "\u2193"], "Volume up / down (or scroll)"], [["M"], "Mute"],
                               [["[", "]"], "Slower / faster (\\ resets)"], [["Z", "X"], "Subtitles earlier / later"],
                               [["\u2212", "="], "Audio earlier / later (lip sync)"],
                               [["Tab"], "Skip intro, or skip credits"], [["Enter"], "Next episode now"],
                               [["I"], "Mark intro start, then end"], [["O"], "Mark where the credits start"],
                               [["F"], "Full screen (or double-click, or click the mouse wheel)"], [["P"], "Picture in picture"], [["B"], "Black out other screens"], [["N"], "Reduce loud sounds"], [["U"], "Next upscaling level"],
                               [["V"], "VR view"], [["C"], "Frame as box art"], [["Shift", "C"], "Frame as fanart"],
                               [["Esc"], "Close menu, leave PiP, or back"]]
                    }
                    ShortcutCard {
                        title: "In the library"
                        rows: [[["Ctrl", "F"], "Search"], [["Esc"], "Clear search, close a window"],
                               [["Double-click"], "A tab: rename it"], [["Right-click"], "A tab: rename it"]]
                    }
                    Caption { text: "TIPS" }
                    Repeater {
                        model: [
                            "Click a poster to open its 3D box. Drag the box to spin it; Box art lets you set your own front, spine, back and disc.",
                            "Shelf view shows your library as DVD spines. Put a Movie-spine.jpg next to a film to use a real spine scan.",
                            "Series: press O in the player where the credits start once, and every episode jumps to the next one there.",
                            "Library Status finds copies you have twice, gaps in seasons and titles without covers. It never deletes anything.",
                            "Animated colours (Appearance) tint the page from the poster you hover. The Custom theme lets you pick your own two colours.",
                            "Portable backup (Settings › Backups) carries your whole library and artwork to another PC."
                        ]
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10
                            Rectangle { Layout.alignment: Qt.AlignTop; Layout.topMargin: 5; width: 6; height: 6; radius: 3; color: Theme.blue }
                            Text { Layout.fillWidth: true; text: modelData; color: "#D9FFFFFF"; font.pixelSize: 12; wrapMode: Text.Wrap; lineHeight: 1.3 }
                        }
                    }
                }

                // Components: every tool Media Vault uses, its version here, and updates (Media Vault itself from GitHub)
                ColumnLayout {
                    visible: root.sectionName === "About & Updates"
                    Layout.fillWidth: true
                    spacing: 10
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.rightMargin: 48
                        spacing: 12
                        Heading { title: "About & Updates"; sub: "The tools Media Vault is built on, the versions on this PC, and whether newer ones exist. Updates install here, without a setup wizard, and each one can be rolled back." }
                        GlassButton { Layout.alignment: Qt.AlignBottom; small: true; label: root.checking ? "Checking\u2026" : "Check now"
                            enabled: !root.checking; opacity: enabled ? 1 : 0.5
                            onClicked: { root.checking = true; Backend.checkComponents() } }
                        GlassButton {
                            Layout.alignment: Qt.AlignBottom
                            small: true; primary: Backend.updateCount > 0
                            label: Backend.updateCount > 0 ? "Update all (" + Backend.updateCount + ")" : "Update all"
                            enabled: Backend.updateCount > 0 && root.downloading < 0; opacity: enabled ? 1 : 0.45
                            tip: "Video engines, shader and packages first, then Media Vault itself (it closes and reopens)"
                            onClicked: Backend.updateAll()
                        }
                    }

                    // Media Vault itself
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: appCol.implicitHeight + 28
                        radius: 14; color: Theme.slate; border.color: root.appRow.status === "update" ? Theme.green : Theme.line
                        RowLayout {
                            id: appCol
                            anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 14 }
                            spacing: 14
                            Image { width: 44; height: 44; source: "brand/icon-128.png"; sourceSize: Qt.size(88, 88); smooth: true; mipmap: true }   // the app icon
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                Text { text: "Media Vault " + root.appInfo.version; color: Theme.text; font.pixelSize: 15; font.weight: Font.Bold }
                                Text {
                                    Layout.fillWidth: true; wrapMode: Text.Wrap; font.pixelSize: 12
                                    color: root.appRow.status === "update" ? Theme.green : root.appRow.status === "error" ? Theme.amber : Theme.muted
                                    text: root.downloading >= 0 && root.downloading < 1 ? "Downloading version " + root.appRow.latest + "\u2026 " + Math.round(root.downloading * 100) + "%"
                                        : root.downloading >= 1 ? "Installing\u2026 Media Vault closes now and opens again by itself in a moment."
                                        : root.checking ? "Checking GitHub for a newer version\u2026"
                                        : root.appRow.status === "update" ? "Version " + root.appRow.latest + " is available."
                                        : root.appRow.status === "error" ? "Could not reach GitHub. Check your connection and try again."
                                        : root.appRow.latest ? "Up to date. Latest release on GitHub: " + root.appRow.latest + "."
                                        : "Releases: github.com/" + root.appInfo.repo
                                }
                                Rectangle {    // download progress
                                    visible: root.downloading >= 0 && root.downloading < 1
                                    Layout.fillWidth: true; Layout.topMargin: 4; height: 4; radius: 2; color: "#26FFFFFF"
                                    Rectangle { width: parent.width * Math.max(0, root.downloading); height: parent.height; radius: 2; color: Theme.green
                                        Behavior on width { NumberAnimation { duration: 150 * Theme.motion } } }
                                }
                            }
                            GlassButton { small: true; visible: root.appRow.status === "update" && root.downloading < 0
                                primary: true; label: root.appInfo.installed ? "Download & install" : "Get it on GitHub"
                                onClicked: root.appInfo.installed ? Backend.installAppUpdate(root.appRow.setup || "", root.appRow.setup ? root.appRow.setup.split("/").pop() : "")
                                                                  : Backend.openLink(root.appRow.page || root.appInfo.page) }
                            GlassButton {      // two clicks: going back a version is not something to do by accident
                                id: appBack
                                property bool asking: false
                                small: true
                                visible: (root.appRow.previous || "") !== "" && root.downloading < 0
                                label: asking ? "Install " + root.appRow.previous + "?" : "Roll back"
                                glyphColor: Theme.amber
                                tip: "Install Media Vault " + root.appRow.previous + " again, the same way as an update. Your library stays."
                                onClicked: {
                                    if (!asking) { asking = true; appBackReset.restart(); return }
                                    asking = false
                                    Backend.installAppUpdate(root.appRow.previousSetup, root.appRow.previousName)
                                }
                                Timer { id: appBackReset; interval: 4000; onTriggered: appBack.asking = false }
                            }
                            GlassButton { small: true; label: "Release notes"; onClicked: Backend.openLink(root.appRow.page || root.appInfo.page) }
                        }
                    }

                    Caption { text: "WHAT MEDIA VAULT USES"; Layout.topMargin: 6 }
                    Repeater {
                        model: root.comps.slice(1)
                        Rectangle {
                            id: compRow
                            Layout.fillWidth: true
                            implicitHeight: 56
                            radius: 12; color: Theme.slate; border.color: Theme.line
                            readonly property bool canAct: (modelData.status === "update" || modelData.status === "missing" || modelData.status === "optional")
                                                           && modelData.kind !== "bundled" && modelData.kind !== "system"
                            RowLayout {
                                anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 14; rightMargin: 10 }
                                spacing: 12
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 1
                                    Text { text: modelData.name; color: Theme.text; font.pixelSize: 13; font.weight: Font.DemiBold }
                                    Text { Layout.fillWidth: true; text: modelData.role; color: Theme.faint; font.pixelSize: 11; elide: Text.ElideRight }
                                }
                                Column {
                                    Layout.preferredWidth: 150
                                    spacing: 1
                                    Text { width: parent.width; horizontalAlignment: Text.AlignRight; elide: Text.ElideLeft
                                        text: modelData.installed || "\u2014"; color: Theme.soft; font.family: Theme.mono; font.pixelSize: 11 }
                                    Text { width: parent.width; horizontalAlignment: Text.AlignRight; visible: modelData.status === "update"
                                        text: "\u2192 " + modelData.latest; color: Theme.green; font.family: Theme.mono; font.pixelSize: 11 }
                                }
                                // status: up to date, update available, missing, optional, built in
                                Rectangle {
                                    readonly property var look: modelData.kind === "bundled" && modelData.status !== "missing" ? ["Built in", Theme.faint]
                                        : ({ ok: ["Up to date", Theme.green], update: ["Update", Theme.green], missing: ["Missing", Theme.red],
                                             optional: ["Not installed", Theme.faint], error: ["Unknown", Theme.amber] })[modelData.status] || ["", Theme.faint]
                                    Layout.preferredWidth: 96
                                    implicitHeight: 22; radius: 11
                                    color: "transparent"; border.color: look[1]; opacity: 0.9
                                    Text { anchors.centerIn: parent; text: parent.look[0]; color: parent.look[1]; font.pixelSize: 10; font.weight: Font.Bold }
                                }
                                // roll back: the version from before the last update (or, once asked, restart to finish)
                                GlassButton {
                                    small: true
                                    visible: modelData.rollbackPending === true || (modelData.previous || "") !== ""
                                    label: modelData.rollbackPending ? "Restart to finish" : "Roll back"
                                    tip: modelData.rollbackPending ? "Media Vault puts back " + modelData.previous + " as it starts"
                                                                   : "Go back to " + modelData.previous
                                    glyphColor: Theme.amber
                                    onClicked: modelData.rollbackPending ? Backend.restartApp() : Backend.rollbackComponent(modelData.id)
                                }
                                Item {
                                    Layout.preferredWidth: 84; implicitHeight: 30
                                    GlassButton { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; small: true; visible: compRow.canAct
                                        label: modelData.status === "update" ? "Update" : "Install"
                                        onClicked: Backend.updateComponent(modelData.id) }
                                }
                            }
                        }
                    }
                    Text { Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.faint; font.pixelSize: 11
                        text: root.appInfo.installed ? "Python and its packages are built into Media Vault and update with it. libmpv, libVLC and the shader update on their own, into your Media Vault folder."
                                                     : "Running from source: Update uses pip for Python packages. libmpv, libVLC and the shader download into bin/." }
                }

                // Backups
                ColumnLayout {
                    visible: root.sectionName === "Backups"
                    Layout.fillWidth: true
                    spacing: 10
                    Heading { title: "Backups"; sub: "The library database is backed up automatically. Restore replaces the current library."; Layout.rightMargin: 48 }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 8
                        GlassButton { small: true; label: "Back up now"; onClicked: { Backend.backupNow(); root.backups = Backend.backups() } }
                    }
                    Caption { text: "PORTABLE BACKUP" }
                    Text { Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.faint; font.pixelSize: 12
                        text: "One .mvault file with the whole library, your settings and all artwork (custom covers, spines, discs). Restoring puts the artwork back where those folders exist and swaps in the library at the next start; the current one is kept in backups." }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 8
                        GlassButton { small: true; label: "Export portable backup\u2026"; glyph: "\u2191"; onClicked: Backend.exportPortable() }
                        GlassButton { small: true; label: "Restore portable backup\u2026"; glyph: "\u2193"; onClicked: Backend.importPortable() }
                    }
                    Caption { text: "RECENT BACKUPS" }
                    Repeater {
                        model: root.backups.slice(0, 5)
                        Rectangle {
                            Layout.fillWidth: true
                            implicitHeight: 48
                            radius: 10; color: Theme.slate; border.color: Theme.line
                            RowLayout {
                                anchors { fill: parent; leftMargin: 14; rightMargin: 8 }
                                Text { text: modelData; color: Theme.text; font.family: Theme.mono; font.pixelSize: 11; Layout.fillWidth: true; elide: Text.ElideMiddle }
                                GlassButton { small: true; label: "Restore"; onClicked: Backend.restoreBackup(modelData) }
                            }
                        }
                    }
                    Text { visible: root.backups.length === 0; text: "No backups yet."; color: Theme.faint; font.pixelSize: 13 }
                }
            }
        }

        // close
        Rectangle {
            anchors { top: parent.top; right: parent.right; margins: 16 }
            width: 34; height: 34; radius: 17
            color: closeArea.containsMouse ? Qt.rgba(1, 1, 1, 0.20) : Theme.fillHover
            scale: closeArea.pressed ? 0.94 : 1
            Behavior on scale { NumberAnimation { duration: 120 * Theme.motion } }
            Text { anchors.centerIn: parent; text: "✕"; color: "#B3FFFFFF"; font.pixelSize: 14 }
            MouseArea { id: closeArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.close() }
        }
    }
}
