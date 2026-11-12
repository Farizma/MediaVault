import QtQuick
import QtQuick.Controls
import QtQuick.Effects
import QtQuick.Layouts
import QtMultimedia

Item {
    id: dash
    property int currentTab: -1
    property string currentTabName: "All"
    readonly property bool overlayOpen: detail.visible || picker.visible || settings.visible || insightsSheet.visible || folderSheet.visible || folderConfig.isOpen || tagManager.isOpen
    // content column: the page uses the whole window at any size (more columns as it widens), with margins that grow a little
    readonly property real gutter: width < 1100 ? 24 : width < 1900 ? 32 : 48

    // ---- the ONE preview player (singleton). It is re-pointed at whichever card is hovered.
    MediaPlayer {
        id: standby
        audioOutput: AudioOutput { muted: true }
        property real startMs: 0
        onMediaStatusChanged: if (mediaStatus === MediaPlayer.LoadedMedia && duration > 0) {
            startMs = duration * 0.2
            standby.setPosition(startMs)
            play()
        }
        onPositionChanged: if (standby.position > startMs + 15000) standby.setPosition(startMs)     // 15 second loop
    }
    property var previewOwner: null
    function startPreview(output, url) {
        standby.stop()
        standby.videoOutput = output
        standby.source = url
        previewOwner = output
    }
    function stopPreview(output) {
        if (previewOwner === output) { standby.stop(); standby.source = ""; previewOwner = null }
    }

    // ---- Play: the cover opens, the screen fades to black, then the player starts. The black stays until the
    // player has taken over, and fades away again when playback ends (or if it never starts).
    property string phase: ""              // "" | "launching" | "playing"
    property string launchKey: ""          // the card whose cover is opening
    property real launchT: 0
    property var pendingStart: null
    function launch(start, cardKey, lead) {
        if (phase !== "") return
        phase = "launching"
        launchKey = cardKey || ""
        pendingStart = start
        launchLead.duration = (lead || 0) * Theme.motion          // the View More box first turns to face you
        launchAnim.restart()
    }
    function landed() {                    // the player is up: reset everything behind the black, then lift it
        launchWatchdog.stop()
        phase = "playing"
        launchKey = ""; launchT = 0
        detail.dismiss()
        curtainOut.restart()               // the player is its own window now, so the library shows again behind it
    }
    function reveal() {                    // back from the player, or it never started
        launchWatchdog.stop()
        launchAnim.stop()
        phase = ""
        launchKey = ""; launchT = 0
        detail.dismiss()
        curtainOut.restart()
    }
    SequentialAnimation {
        id: launchAnim
        PauseAnimation { id: launchLead }
        ParallelAnimation {
            NumberAnimation { target: dash; property: "launchT"; from: 0; to: 1; duration: 700 * Theme.motion; easing.type: Easing.OutCubic }
            SequentialAnimation {
                PauseAnimation { duration: 250 * Theme.motion }
                NumberAnimation { target: curtain; property: "opacity"; to: 1; duration: 450 * Theme.motion; easing.type: Easing.InOutQuad }
            }
        }
        ScriptAction { script: { launchWatchdog.restart(); dash.pendingStart() } }
    }
    NumberAnimation { id: curtainOut; target: curtain; property: "opacity"; to: 0; duration: 500 * Theme.motion; easing.type: Easing.OutCubic }
    Timer { id: launchWatchdog; interval: 8000; onTriggered: dash.reveal() }   // nothing played (missing file, no core)
    Connections {
        target: Player
        function onStateChanged() {
            if (dash.phase === "launching" && Player.state.active === true) dash.landed()
        }
        function onClosed() { if (dash.phase !== "") dash.reveal() }
        function onError(message) { if (dash.phase !== "") dash.reveal() }
    }

    // ---- animated themes: the page glow eases toward the colour of what you are looking at
    property bool animatedTheme: Backend.setting("animated_theme") !== "0"
    property color glow: Theme.blue
    Behavior on glow { ColorAnimation { duration: 900 * Theme.motion; easing.type: Easing.InOutQuad } }
    property string billboardArt: ""
    function tintTo(url) {
        if (!animatedTheme) return
        var c = url ? Backend.tintOf(url) : ""
        glow = c !== "" ? c : Theme.blue
    }
    Connections { target: settings; function onVisibleChanged() { if (!settings.visible) { dash.animatedTheme = Backend.setting("animated_theme") !== "0"; if (!dash.animatedTheme) dash.glow = Theme.blue } } }

    // ---- search, sort, filters, grid / shelf
    property string query: ""
    property string sort: "title"
    property string genre: ""
    property string quality: ""
    property bool unwatched: false
    property bool boxSets: Backend.setting("group_collections") !== "0"
    property int tabDragFrom: -1          // tab being dragged (index), where it would land, and its width
    property int tabDragTo: -1
    property real tabDragW: 0
    property bool shelf: false
    property var opts: ({})
    property var searchField: null
    readonly property bool filtered: query !== "" || genre !== "" || quality !== "" || unwatched || sort !== "title"
    function applyView() { Backend.setView(query, sort, genre, quality, unwatched) }
    function clearView() { query = ""; sort = "title"; genre = ""; quality = ""; unwatched = false; applyView() }
    function setShelf(on) { shelf = on; stagger = true; staggerOff.restart(); grid.keptY = -1; Backend.setShelf(on); grid.keptY = -1; grid.userScrolled = false; grid.positionViewAtBeginning() }
    Timer { id: searchDebounce; interval: 160; onTriggered: dash.applyView() }
    Shortcut { sequences: [StandardKey.Find]; onActivated: if (dash.searchField) { grid.contentY = grid.originY; dash.searchField.forceActiveFocus() } }
    Component.onCompleted: opts = Backend.viewOptions()
    Connections { target: Library; function onModelReset() { dash.opts = Backend.viewOptions() } }

    // ---- tab change: the new cards fade up in a quick cascade (30 ms apart, first 14 only)
    property bool stagger: false
    Timer { id: staggerOff; interval: 900; onTriggered: dash.stagger = false }

    // ---- theme change: snapshot the window, switch colours underneath, fade the snapshot out (like macOS)
    function switchTheme(id) {
        if (Theme.motion === 0) { Backend.setSetting("theme", id); return }
        dash.grabToImage(function(result) {
            themeShot.source = result.url
            themeShot.opacity = 1
            Backend.setSetting("theme", id)
            themeFade.restart()
        })
    }

    // ---- content (blurred while an overlay is open)
    Item {
        id: content
        anchors.fill: parent
        layer.enabled: dash.overlayOpen
        layer.effect: MultiEffect { blurEnabled: true; blurMax: 40; blur: 0.7 * (picker.visible || settings.visible ? 1 : detail.f) }

        Rectangle { anchors.fill: parent; color: Theme.black }
        Rectangle {          // the glow: a wash of colour from the top, fading into the page
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: parent.height * 0.75
            visible: dash.animatedTheme
            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.rgba(dash.glow.r, dash.glow.g, dash.glow.b, 0.26) }
                GradientStop { position: 0.45; color: Qt.rgba(dash.glow.r, dash.glow.g, dash.glow.b, 0.08) }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }

        // ---- virtual grid: delegates are created only for what is visible, and recycled.
        // Billboard, insights and the catalog title ride in the header so the whole page scrolls as one.
        GridView {
            id: grid
            // columns of 180 px cards whose outer edges line up with the billboard; the gap absorbs the slack
            readonly property real span: dash.width - 2 * dash.gutter
            readonly property int itemW: dash.shelf ? 30 : 180          // a poster, or a spine on the shelf
            readonly property int minGap: dash.shelf ? 5 : 20
            readonly property int columns: Math.max(1, Math.floor((span + minGap) / (itemW + minGap)))
            readonly property int gap: columns > 1 ? Math.floor((span - columns * itemW) / (columns - 1)) : Math.floor(span - itemW)
            property bool userScrolled: false
            anchors { fill: parent; topMargin: topBar.height; leftMargin: dash.gutter - gap / 2; rightMargin: dash.gutter - gap / 2 }
            clip: true
            model: Library
            cellWidth: itemW + gap
            cellHeight: dash.shelf ? 276 : 344
            onMovementStarted: userScrolled = true
            cacheBuffer: 900
            reuseItems: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { parent: content; x: content.width - width; y: grid.y; height: grid.height }
            SmoothWheel { view: grid; onScrolled: grid.userScrolled = true }
            // a filter, the sort or the Box sets switch rebuilds the list, and a rebuilt GridView starts at its top:
            // remember where the page was and go back there (as far as the new, maybe shorter, list allows).
            // Switching tabs and Grid / Shelf still start at the top on purpose (they call positionViewAtBeginning).
            property real keptY: -1
            Connections {
                target: Library
                function onModelAboutToBeReset() { grid.keptY = grid.contentY - grid.originY }
                function onModelReset() { if (grid.keptY > 0) Qt.callLater(grid.restoreY) }
            }
            function restoreY() {
                if (keptY <= 0) return
                forceLayout()
                userScrolled = true                     // keeps the header's "stay at the top" rule out of the way
                contentY = originY + Math.min(keptY, Math.max(0, contentHeight - height))
                keptY = -1
            }

            header: Column {
                width: grid.width
                leftPadding: grid.gap / 2
                rightPadding: grid.gap / 2
                topPadding: 24
                spacing: 24
                // the billboard and insights size themselves after the first layout; keep the page at its top
                // until the person scrolls, otherwise the grid holds its first row still and the header slides up
                onHeightChanged: if (!grid.userScrolled) Qt.callLater(grid.positionViewAtBeginning)

                // ---- recommended carousel: random titles from the selected tab, a new one every 7 s
                Rectangle {
                    id: billboard
                    readonly property var slides: Backend.billboard.items || []
                    readonly property int count: slides.length
                    readonly property bool compact: width < 900
                    readonly property real pad: compact ? 28 : 44
                    // hold still while the person reads, or while the app is out of sight
                    readonly property bool hold: hover.hovered || dash.overlayOpen || Qt.application.state !== Qt.ApplicationActive
                    property int index: 0
                    property string currentKey: ""
                    property real progress: 0
                    property real textH: 0
                    function go(i) {    // reads slides.length, not count: count may not have caught up yet
                        var n = slides.length
                        if (n === 0) { tick.stop(); return }
                        index = (i + n) % n
                        currentKey = slides[index].key
                        dash.billboardArt = slides[index].art || ""
                        dash.tintTo(dash.billboardArt)
                        progress = 0
                        if (n > 1) tick.restart(); else tick.stop()
                    }
                    function fit() {    // tallest text block of all slides: the card does not jump between slides
                        var m = 0
                        for (var i = 0; i < texts.count; i++) if (texts.itemAt(i)) m = Math.max(m, texts.itemAt(i).implicitHeight)
                        textH = m
                    }
                    // a library refresh keeps the slide you are looking at; a new tab starts at the first
                    onSlidesChanged: {
                        var at = 0
                        for (var i = 0; i < slides.length; i++) if (slides[i].key === currentKey) at = i
                        go(at)
                        Qt.callLater(fit)
                    }
                    NumberAnimation {
                        id: tick
                        target: billboard; property: "progress"; from: 0; to: 1
                        duration: 7000; easing.type: Easing.Linear
                        paused: running && billboard.hold
                        onFinished: billboard.go(billboard.index + 1)
                    }
                    HoverHandler { id: hover }

                    visible: count > 0
                    width: grid.span
                    // as tall as the width suggests, but never shorter than kicker + tallest text block (no overlap)
                    height: visible ? Math.round(Math.max(Math.min(520, width * 0.36), textH + 2 * pad + 22 + 20)) : 0
                    radius: 16
                    color: Theme.black
                    border.color: Theme.line
                    clip: true
                    // rounded picture: art, scrims and the progress bar are masked so the corners stay round
                    Item {
                        id: bbArt
                        anchors.fill: parent
                        visible: false
                        layer.enabled: true
                        Repeater {
                            model: billboard.slides
                            Image {
                                anchors.fill: parent
                                source: modelData.art
                                fillMode: Image.PreserveAspectCrop
                                asynchronous: true
                                sourceSize.width: 1600
                                opacity: index === billboard.index ? 0.85 : 0
                                Behavior on opacity { NumberAnimation { duration: 600 * Theme.motion; easing.type: Easing.InOutQuad } }
                            }
                        }
                        Rectangle {   // left-to-right scrim (black/95 -> black/60 -> clear)
                            anchors.fill: parent
                            gradient: Gradient {
                                orientation: Gradient.Horizontal
                                GradientStop { position: 0.0; color: "#F2000000" }
                                GradientStop { position: 0.5; color: "#99000000" }
                                GradientStop { position: 1.0; color: "#00000000" }
                            }
                        }
                        Rectangle {   // bottom-up scrim into the page colour
                            anchors.fill: parent
                            gradient: Gradient {
                                GradientStop { position: 0.0; color: "#66000000" }
                                GradientStop { position: 0.5; color: "#00000000" }
                                GradientStop { position: 1.0; color: Theme.graphite }
                            }
                        }
                        Rectangle {   // time to the next slide
                            visible: billboard.count > 1
                            anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                            height: 4
                            color: "#CC000000"
                            Rectangle {
                                width: parent.width * billboard.progress; height: parent.height
                                gradient: Gradient {
                                    orientation: Gradient.Horizontal
                                    GradientStop { position: 0.0; color: Theme.blue }
                                    GradientStop { position: 0.6; color: Theme.green }
                                }
                            }
                        }
                    }
                    Item { id: bbMask; anchors.fill: parent; visible: false; layer.enabled: true
                        Rectangle { anchors.fill: parent; radius: billboard.radius; color: "black" } }
                    MultiEffect { source: bbArt; anchors.fill: bbArt; maskEnabled: true; maskSource: bbMask }
                    Rectangle { anchors.fill: parent; radius: parent.radius; color: "transparent"; border.color: Theme.line }

                    // kicker
                    Rectangle {
                        x: billboard.compact ? 28 : 48; y: billboard.pad
                        height: 22; radius: 11; width: kick.implicitWidth + 20; color: "#33FFFFFF"
                        Text { id: kick; anchors.centerIn: parent; text: "RECOMMENDED IN " + dash.currentTabName.toUpperCase()
                            color: "#FFFFFF"; font.family: Theme.mono; font.pixelSize: 11; font.weight: Font.Bold }
                    }
                    // one text block per slide; they cross-fade and sit on the bottom edge
                    Repeater {
                        id: texts
                        model: billboard.slides
                        ColumnLayout {
                            readonly property bool current: index === billboard.index
                            anchors { left: parent.left; bottom: parent.bottom; leftMargin: billboard.compact ? 28 : 48; bottomMargin: billboard.pad }
                            width: Math.min(680, billboard.width - 2 * anchors.leftMargin - (billboard.count > 1 ? 130 : 0))
                            spacing: 12
                            opacity: current ? 1 : 0
                            visible: opacity > 0
                            enabled: current
                            transform: Translate { y: current ? 0 : 8 }
                            Behavior on opacity { NumberAnimation { duration: 300 * Theme.motion; easing.type: Easing.OutCubic } }
                            onImplicitHeightChanged: billboard.fit()
                            Text {
                                Layout.fillWidth: true
                                text: modelData.title
                                color: "#FFFFFF"
                                font.pixelSize: billboard.compact ? 34 : 46
                                font.weight: Font.ExtraBold
                                font.letterSpacing: billboard.compact ? -1.0 : -1.4
                                lineHeight: 1.08
                                wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight
                            }
                            Text {      // original title, small, under the one shown
                                Layout.fillWidth: true
                                Layout.topMargin: -6
                                visible: (modelData.subtitle || "") !== ""
                                text: modelData.subtitle || ""
                                color: "#CCFFFFFF"; font.pixelSize: billboard.compact ? 14 : 16; font.weight: Font.Medium
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.fillWidth: true
                                visible: text !== ""
                                text: modelData.meta
                                color: "#B3FFFFFF"
                                font.family: Theme.mono; font.pixelSize: 12
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.fillWidth: true
                                visible: text !== ""
                                text: modelData.synopsis
                                color: "#D9FFFFFF"
                                font.pixelSize: billboard.compact ? 14 : 15
                                lineHeight: 1.45
                                wrapMode: Text.Wrap; maximumLineCount: billboard.compact ? 2 : 3; elide: Text.ElideRight
                            }
                            RowLayout {
                                Layout.topMargin: 6
                                spacing: 12
                                GlassButton { label: "Watch Now"; glyph: "\u25B6"; primary: true; implicitHeight: 46; onClicked: { var k = modelData.key; dash.launch(function() { Backend.play(k) }, "") } }
                                GlassButton { id: moreInfo; label: "More Info"; glyph: "\u24D8"; glyphColor: Theme.blue; implicitHeight: 46
                                    onClicked: detail.open(modelData.key, moreInfo.mapToItem(detail, 0, 0, moreInfo.width, moreInfo.height), "button") }
                            }
                        }
                    }
                    // previous / position / next
                    Row {
                        visible: billboard.count > 1
                        anchors { right: parent.right; bottom: parent.bottom; rightMargin: billboard.compact ? 24 : 40; bottomMargin: billboard.pad + 7 }
                        spacing: 10
                        Repeater {
                            model: [-1, 1]
                            Rectangle {
                                width: 32; height: 32; radius: 16
                                color: navArea.containsMouse ? "#E6000000" : "#99000000"
                                border.color: Theme.line
                                scale: navArea.pressed ? 0.94 : 1
                                Behavior on scale { NumberAnimation { duration: 120 * Theme.motion } }
                                Text { anchors.centerIn: parent; anchors.verticalCenterOffset: -1; text: modelData < 0 ? "\u2039" : "\u203A"; color: "#FFFFFF"; font.pixelSize: 20 }
                                MouseArea { id: navArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                    onClicked: billboard.go(billboard.index + modelData) }
                            }
                        }
                    }
                    Text {
                        visible: billboard.count > 1
                        anchors { right: parent.right; bottom: parent.bottom; rightMargin: (billboard.compact ? 24 : 40) + 84; bottomMargin: billboard.pad + 15 }
                        text: (billboard.index + 1) + " / " + billboard.count
                        color: "#CCFFFFFF"; font.family: Theme.mono; font.pixelSize: 12
                    }
                }

                // ---- catalog title, search, view toggle, sort and filters
                Item {
                    width: grid.span
                    height: catalogCol.implicitHeight + 14
                    Column {
                        id: catalogCol
                        anchors { left: parent.left; right: parent.right; top: parent.top }
                        spacing: 10
                        Row {
                            spacing: 12
                            Text { id: catalogTitle; text: dash.currentTabName + (dash.shelf ? " Shelf" : " Catalog"); color: "#FFFFFF"; font.pixelSize: 20; font.weight: Font.ExtraBold; font.letterSpacing: -0.4
                                elide: Text.ElideRight; width: Math.min(implicitWidth, catalogCol.width - 140) }
                            Text { anchors.baseline: catalogTitle.baseline; text: grid.count + (grid.count === 1 ? " title" : " titles"); color: "#66FFFFFF"; font.family: Theme.mono; font.pixelSize: 12 }
                        }
                        // sort and filters on the left (they wrap on a narrow window); the view switch and search stay on the right
                        // plain anchors, not a RowLayout: a wrapping Flow inside a layout makes Qt re-lay out forever
                        Item {
                            width: parent.width
                            height: Math.max(filterFlow.height, viewTools.height)
                            Flow {
                                id: filterFlow
                                anchors { left: parent.left; right: viewTools.left; rightMargin: 12; top: parent.top }
                                spacing: 8
                                Dropdown { prefix: "Sort: "; options: dash.opts.sorts || []; value: dash.sort; onChosen: (v) => { dash.sort = v; dash.applyView() } }
                                Dropdown { options: dash.opts.genres || []; value: dash.genre; onChosen: (v) => { dash.genre = v; dash.applyView() } }
                                Dropdown { options: dash.opts.qualities || []; value: dash.quality; onChosen: (v) => { dash.quality = v; dash.applyView() } }
                                Pill { height: 32; label: "Unwatched"; selected: dash.unwatched; accent: Theme.blue; onClicked: { dash.unwatched = !dash.unwatched; dash.applyView() } }
                                // box sets on or off, right here (also in Settings > Library)
                                Pill { height: 32; label: "Box sets"; selected: dash.boxSets; accent: Theme.amber
                                    onClicked: { dash.boxSets = !dash.boxSets; Backend.setSetting("group_collections", dash.boxSets ? "1" : "0") }
                                    Tip { visible: boxSetHover.hovered; delay: 600; text: dash.boxSets ? "Showing films of a series as one box set" : "Showing every film on its own" }
                                    HoverHandler { id: boxSetHover } }
                                GlassButton { small: true; label: "Clear"; visible: dash.filtered; onClicked: dash.clearView() }
                            }
                            Row {
                                id: viewTools
                                anchors { right: parent.right; top: parent.top }
                                spacing: 12
                                // Grid | Shelf
                                Rectangle {
                                    implicitWidth: 132; implicitHeight: 32; radius: 10
                                    color: "#99000000"; border.color: Theme.line
                                    Rectangle { width: (parent.width - 6) / 2; height: parent.height - 6; y: 3; radius: 8; color: "#FFFFFF"
                                        x: 3 + (dash.shelf ? width : 0)
                                        Behavior on x { NumberAnimation { duration: 260 * Theme.motion; easing.type: Easing.OutCubic } } }
                                    Row {
                                        anchors { fill: parent; margins: 3 }
                                        Repeater {
                                            model: ["Grid", "Shelf"]
                                            Item {
                                                width: parent.width / 2; height: parent.height
                                                Text { anchors.centerIn: parent; text: modelData; font.pixelSize: 12; font.weight: Font.Bold
                                                    color: (index === 1) === dash.shelf ? "#000000" : "#B3FFFFFF" }
                                                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                                    onClicked: if ((index === 1) !== dash.shelf) dash.setShelf(index === 1) }
                                            }
                                        }
                                    }
                                }
                                // search: every word must match (title, synopsis, tags, genres, notes, year, format). Ctrl+F
                                Field {
                                    id: searchField
                                    width: activeFocus || text !== "" ? 280 : 210
                                    Behavior on width { NumberAnimation { duration: 220 * Theme.motion; easing.type: Easing.OutCubic } }
                                    implicitHeight: 32
                                    topPadding: 6; bottomPadding: 6; leftPadding: 30
                                    placeholderText: "Search library"
                                    text: dash.query
                                    onTextEdited: { dash.query = text; searchDebounce.restart() }
                                    Keys.onEscapePressed: { text = ""; dash.query = ""; dash.applyView(); grid.forceActiveFocus() }
                                    Component.onCompleted: dash.searchField = searchField
                                    Text { x: 11; anchors.verticalCenter: parent.verticalCenter; text: "\u2315"; color: Theme.faint; font.pixelSize: 14 }
                                }
                                                    }
                        }
                    }
                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }
                }
                Item { width: 1; height: 1 }
            }

            footer: Item {
                width: grid.width
                height: grid.count === 0 ? 300 : 40
                Column {
                    visible: grid.count === 0
                    anchors.centerIn: parent
                    spacing: 10
                    Rectangle { anchors.horizontalCenter: parent.horizontalCenter; width: 48; height: 48; radius: 16; color: Theme.fill; border.color: Theme.line
                        Text { anchors.centerIn: parent; text: "⌕"; color: Theme.faint; font.pixelSize: 22 } }
                    Text { anchors.horizontalCenter: parent.horizontalCenter; text: dash.filtered ? "No titles match" : "Nothing here yet"; color: "#FFFFFF"; font.pixelSize: 16; font.weight: Font.Bold }
                    Text { anchors.horizontalCenter: parent.horizontalCenter; text: dash.filtered ? "Try fewer words, or clear the filters." : "Add a folder, or give the scan a moment."; color: Theme.faint; font.pixelSize: 13 }
                    GlassButton { anchors.horizontalCenter: parent.horizontalCenter; label: dash.filtered ? "Clear search and filters" : "Add folder"; glyph: dash.filtered ? "" : "+"; small: true
                        onClicked: dash.filtered ? dash.clearView() : Backend.pickFolder() }
                }
            }

            delegate: Item {
                id: cell
                width: grid.cellWidth
                height: grid.cellHeight
                z: pointerIn || opening > 0 ? 2 : 0   // the lifted / opening card draws over its neighbours
                property bool pointerIn: false        // immediate: border, lift, parallax
                property bool hovered: false          // after the 500 ms linger: preview video
                readonly property bool previewing: hovered && dash.previewOwner === vo && standby.playbackState === MediaPlayer.PlayingState
                // while its box is out in the View More sheet, the card itself is not there
                readonly property bool lifted: detail.visible && detail.fromCard && detail.itemKey === key
                readonly property real opening: key === dash.launchKey ? dash.launchT : 0
                // parallax: where the pointer is over the poster (tx, ty: -1..1), and where the tilt is now (px, py).
                // Every frame the tilt closes a share of the gap, scaled by the real frame time: smooth at any
                // pointer speed (a spring restarted on each mouse event stutters when the pointer moves slowly).
                property real tx: 0
                property real ty: 0
                property real px: 0
                property real py: 0
                FrameAnimation {
                    running: Theme.motion > 0 && (Math.abs(cell.tx - cell.px) > 0.0005 || Math.abs(cell.ty - cell.py) > 0.0005)
                    onTriggered: {
                        var k = 1 - Math.exp(-Math.min(frameTime, 0.05) * 12)
                        cell.px += (cell.tx - cell.px) * k
                        cell.py += (cell.ty - cell.py) * k
                    }
                }
                onTxChanged: if (Theme.motion === 0) px = tx
                onTyChanged: if (Theme.motion === 0) py = ty
                GridView.onPooled: { pointerIn = false; hovered = false; tx = 0; ty = 0; px = 0; py = 0; linger.stop(); dash.stopPreview(vo) }
                GridView.onReused: { pointerIn = false; hovered = false; enter() }
                Component.onCompleted: enter()
                property real appear: 1
                function enter() { if (dash.stagger && Theme.motion > 0) { appear = 0; rise.restart() } }
                SequentialAnimation {
                    id: rise
                    PauseAnimation { duration: Math.max(0, Math.min(index, 14)) * 30 }
                    NumberAnimation { target: cell; property: "appear"; to: 1; duration: 320; easing.type: Easing.OutCubic }
                }
                opacity: appear
                transform: Translate { y: 14 * (1 - cell.appear) }

                // the open case behind the cover: tray and disc, seen as the cover swings open on Play
                Rectangle {
                    x: box.x; y: box.y; width: box.width; height: box.height
                    visible: cell.opening > 0 && !dash.shelf
                    radius: 12
                    color: "#141416"
                    border.color: Theme.line
                    Disc { anchors.centerIn: parent; width: 164; height: 164; source: disc !== "" ? disc : poster; spin: 300 * cell.opening }
                }

                // box set: two more cases peek out behind the cover, and fan out a little on hover
                Repeater {
                    model: key.indexOf("set:") === 0 && !dash.shelf && cell.opening === 0 ? 2 : 0
                    Rectangle {
                        readonly property real fan: cell.pointerIn ? 1 : 0
                        x: box.x + (index + 1) * (7 + 4 * fan); y: box.y - (index + 1) * (5 + 3 * fan)
                        width: box.width; height: box.height; radius: 12
                        rotation: (index + 1) * (1.2 + 1.6 * fan)
                        z: -1 - index
                        color: index === 0 ? "#3A3A3F" : "#2A2A2E"
                        border.color: Theme.lineStrong
                        opacity: (cell.lifted ? 0 : offline ? 0.35 : 1) * (0.9 - 0.2 * index)
                        Behavior on x { NumberAnimation { duration: 260 * Theme.motion; easing.type: Easing.OutQuint } }
                        Behavior on y { NumberAnimation { duration: 260 * Theme.motion; easing.type: Easing.OutQuint } }
                        Behavior on rotation { NumberAnimation { duration: 260 * Theme.motion; easing.type: Easing.OutQuint } }
                    }
                }

                Rectangle {
                    id: box
                    x: grid.gap / 2; y: 8; width: 180; height: 270
                    radius: 12
                    color: Theme.slate
                    visible: !dash.shelf
                    opacity: cell.lifted ? 0 : offline ? 0.35 : 1
                    scale: cell.opening > 0 ? 1 : cell.previewing ? 1.05 : cell.pointerIn ? 1.02 : 1
                    Behavior on scale { NumberAnimation { duration: 220 * Theme.motion; easing.type: Easing.OutCubic } }
                    transform: [
                        // parallax tilt toward the pointer (up to 9 degrees), around the poster's centre
                        Rotation { origin.x: 90; origin.y: 135; axis { x: 0; y: 1; z: 0 } angle: 9 * cell.px * Theme.motion },
                        Rotation { origin.x: 90; origin.y: 135; axis { x: 1; y: 0; z: 0 } angle: -9 * cell.py * Theme.motion },
                        // Play: the cover swings open on its spine (left edge)
                        Rotation { origin.x: 0; origin.y: 135; axis { x: 0; y: 1; z: 0 } angle: -105 * cell.opening }
                    ]
                    // shadow
                    Rectangle { z: -1; anchors.fill: parent; anchors.topMargin: 10; anchors.margins: -2; radius: 14; color: "#66000000"; opacity: cell.pointerIn ? 1 : 0.6 }

                    Item {
                        id: art
                        anchors.fill: parent
                        visible: false
                        layer.enabled: true
                        Image {    // a little larger than the card, and shifted against the tilt: depth inside the frame
                            anchors { fill: parent; margins: -10 }
                            source: poster
                            asynchronous: true
                            fillMode: Image.PreserveAspectCrop
                            sourceSize.width: 400; sourceSize.height: 600
                            transform: Translate { x: -8 * cell.px * Theme.motion; y: -8 * cell.py * Theme.motion }
                        }
                        Text { visible: poster === ""; anchors { fill: parent; margins: 16 } text: title; color: Theme.text; font.pixelSize: 15; font.weight: Font.Bold; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
                        VideoOutput { id: vo; anchors.fill: parent; fillMode: VideoOutput.PreserveAspectCrop; visible: cell.previewing }
                        Rectangle {    // bottom gloss so badges and buttons stay legible on any poster
                            anchors.fill: parent
                            opacity: cell.pointerIn ? 1 : 0.55
                            Behavior on opacity { NumberAnimation { duration: 200 * Theme.motion } }
                            gradient: Gradient {
                                GradientStop { position: 0.0; color: "#00000000" }
                                GradientStop { position: 0.55; color: "#33000000" }
                                GradientStop { position: 1.0; color: "#E6000000" }
                            }
                        }
                        // light catching the glossy sleeve: a soft band that follows the pointer
                        Rectangle {
                            width: parent.width * 2; height: 140
                            x: -parent.width / 2 + cell.px * 50; y: parent.height * (0.5 + 0.5 * cell.py) - height / 2
                            rotation: -20
                            opacity: cell.pointerIn ? 0.16 * Theme.motion : 0
                            Behavior on opacity { NumberAnimation { duration: 200 * Theme.motion } }
                            gradient: Gradient {
                                GradientStop { position: 0.0; color: "#00FFFFFF" }
                                GradientStop { position: 0.5; color: "#FFFFFFFF" }
                                GradientStop { position: 1.0; color: "#00FFFFFF" }
                            }
                        }
                        Rectangle { anchors { left: parent.left; right: parent.right; bottom: parent.bottom } height: 4; color: "#99000000"; visible: progress > 0 && !done
                            Rectangle { width: parent.width * progress; height: parent.height; color: Theme.green } }
                        // once the cover has turned past its edge you see its inside, not a mirrored poster
                        Rectangle { anchors.fill: parent; color: Theme.slate; visible: cell.opening > 0.62 }
                    }
                    Item { id: mask; width: art.width; height: art.height; visible: false; layer.enabled: true; Rectangle { width: mask.width; height: mask.height; radius: 12; color: "black" } }
                    MultiEffect { source: art; anchors.fill: art; maskEnabled: true; maskSource: mask }
                    Rectangle { anchors.fill: parent; radius: 12; color: "transparent"
                        border.color: cell.previewing ? "#66FFFFFF" : cell.pointerIn ? "#33FFFFFF" : Theme.line
                        Behavior on border.color { ColorAnimation { duration: 200 * Theme.motion } } }

                    Rectangle { visible: done && cell.opening === 0; width: 24; height: 24; radius: 12; color: Theme.green; anchors { top: parent.top; right: parent.right; margins: 8 }
                        Text { anchors.centerIn: parent; text: "\u2713"; color: Theme.onGreen; font.pixelSize: 13; font.weight: Font.Bold } }
                    Rectangle { visible: badge !== "" && cell.opening === 0; height: 20; width: badgeText.implicitWidth + 12; radius: 5; color: "#BF000000"; border.color: Theme.line
                        anchors { top: parent.top; left: parent.left; margins: 8 }
                        Text { id: badgeText; anchors.centerIn: parent; text: badge.toUpperCase(); color: "#E6FFFFFF"; font.family: Theme.mono; font.pixelSize: 9; font.weight: Font.Bold } }
                }
                // ---- shelf view: the case's spine, standing on a shelf
                Rectangle {          // the shelf board under each row (the cells join into one board)
                    visible: dash.shelf
                    x: -1; y: 242; width: cell.width + 2; height: 12
                    gradient: Gradient {
                        GradientStop { position: 0; color: Qt.lighter(Theme.slate, 1.9) }
                        GradientStop { position: 0.25; color: Qt.lighter(Theme.slate, 1.35) }
                        GradientStop { position: 1; color: Theme.slate }
                    }
                    Rectangle { y: parent.height; width: parent.width; height: 10; gradient: Gradient {
                        GradientStop { position: 0; color: "#80000000" } GradientStop { position: 1; color: "#00000000" } } }
                }
                Item {
                    id: spineItem
                    visible: dash.shelf
                    x: grid.gap / 2; y: 16; width: 30; height: 226
                    readonly property bool pulled: spineHit.containsMouse
                    opacity: cell.lifted ? 0 : offline ? 0.35 : 1
                    z: pulled ? 3 : 0
                    // hover pulls the case half out toward you: up a little, a touch bigger, with a shadow
                    transform: Translate { y: spineItem.pulled ? -16 : 0
                        Behavior on y { NumberAnimation { duration: 220 * Theme.motion; easing.type: Easing.OutBack; easing.overshoot: 1.4 } } }
                    scale: pulled ? 1.06 : 1
                    Behavior on scale { NumberAnimation { duration: 220 * Theme.motion; easing.type: Easing.OutCubic } }
                    Rectangle { anchors.fill: parent; anchors.margins: -3; anchors.topMargin: 10; radius: 4; color: "#80000000"; opacity: spineItem.pulled ? 1 : 0.4; z: -1 }
                    Rectangle {
                        anchors.fill: parent
                        radius: 3
                        color: "#0E0E10"
                        border.color: spineItem.pulled ? "#66FFFFFF" : "#1FFFFFFF"
                        clip: true
                        Image { id: spineArt; anchors.fill: parent; anchors.margins: 1; source: spine; visible: status === Image.Ready; fillMode: Image.Stretch; asynchronous: true }
                        Item {
                            anchors.fill: parent
                            visible: !spineArt.visible
                            Rectangle { width: parent.width; height: 8; color: Theme.blue }
                            Text {
                                anchors.centerIn: parent
                                width: parent.height - 70
                                rotation: 90
                                text: title.toUpperCase()
                                color: "#FFFFFF"; font.pixelSize: 11; font.weight: Font.ExtraBold; font.letterSpacing: 0.6
                                horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight
                            }
                            Text { anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 26 } rotation: 90
                                text: year; color: "#80FFFFFF"; font.family: Theme.mono; font.pixelSize: 8 }
                            Text { anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 6 }
                                text: "MV"; color: Theme.blue; font.pixelSize: 8; font.weight: Font.ExtraBold }
                        }
                        Rectangle { visible: progress > 0 && !done; anchors.bottom: parent.bottom; width: parent.width * progress; height: 3; color: Theme.green }
                    }
                    Rectangle { visible: done; anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: -7 }
                        width: 10; height: 10; radius: 5; color: Theme.green; border.color: Theme.black; border.width: 2 }
                    MouseArea {
                        id: spineHit
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        // the box flies out spine-first and turns to show its cover
                        onClicked: detail.open(key, cell.mapToItem(detail, spineItem.x, spineItem.y, spineItem.width, spineItem.height), "spine")
                    }
                    Tip { visible: spineItem.pulled; delay: 300; text: title + (year ? "  \u00B7  " + year : "") }
                }

                // 500 ms debounce: sweeping the cursor across the grid does nothing
                Timer {
                    id: linger
                    interval: 500
                    onTriggered: { cell.hovered = true; dash.tintTo(poster); if (durationMs > 0) dash.startPreview(vo, videoUrl) }
                }
                MouseArea {
                    id: hit
                    x: box.x; y: box.y; width: box.width; height: box.height
                    visible: !dash.shelf
                    hoverEnabled: true
                    enabled: !dash.launchKey
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    cursorShape: Qt.PointingHandCursor
                    function openBox() { detail.open(key, cell.mapToItem(detail, box.x, box.y, box.width, box.height), "card") }
                    onEntered: { cell.pointerIn = true; linger.restart() }
                    onPositionChanged: (m) => {
                        cell.tx = Math.max(-1, Math.min(1, (m.x / width - 0.5) * 2))
                        cell.ty = Math.max(-1, Math.min(1, (m.y / height - 0.5) * 2))
                    }
                    onExited: { cell.pointerIn = false; cell.tx = 0; cell.ty = 0; linger.stop(); if (cell.hovered) dash.tintTo(dash.billboardArt); cell.hovered = false; dash.stopPreview(vo) }
                    onClicked: openBox()                 // the poster becomes the 3D box and grows into View More

                    // hover actions
                    Row {
                        anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 12 }
                        spacing: 8
                        opacity: cell.pointerIn && cell.opening === 0 ? 1 : 0
                        visible: opacity > 0
                        Behavior on opacity { NumberAnimation { duration: 160 * Theme.motion; easing.type: Easing.OutCubic } }
                        GlassButton { width: parent.width - 8 - 36; small: true; primary: true; label: offline ? "Offline" : "Play"; glyph: offline ? "" : "\u25B6"; enabled: !offline
                            onClicked: { var k = key; dash.launch(function() { Backend.play(k) }, k) } }
                        GlassButton { width: 36; small: true; label: ""; glyph: "\u24D8"; glyphColor: Theme.blue; onClicked: hit.openBox() }
                    }
                }
                Rectangle {          // folder offline (drive unplugged): the title stays, greyed, until it is back
                    visible: offline && !dash.shelf
                    x: box.x + 8; y: box.y + 8; height: 20; width: offText.implicitWidth + 12; radius: 5; color: "#E6000000"; border.color: Theme.amber
                    Text { id: offText; anchors.centerIn: parent; text: "OFFLINE"; color: Theme.amber; font.family: Theme.mono; font.pixelSize: 9; font.weight: Font.Bold }
                }
                Column {
                    x: box.x; y: box.y + box.height + 10; width: box.width; spacing: 3
                    visible: !dash.shelf
                    opacity: cell.lifted ? 0 : offline ? 0.5 : 1
                    Marquee { text: title; width: parent.width; active: cell.pointerIn; color: cell.pointerIn ? Theme.blue : Theme.text; font.pixelSize: 13; font.weight: Font.Bold; font.letterSpacing: -0.1 }
                    // the original title (Titles setting), small, under the one shown
                    Text { visible: subtitle !== ""; text: subtitle; width: parent.width; color: Theme.muted; font.pixelSize: 11; elide: Text.ElideRight }
                    Text { text: meta; width: parent.width; color: Theme.faint; font.family: Theme.mono; font.pixelSize: 11; elide: Text.ElideRight }
                }
            }
        }

        // ---- top bar: brand, folder tabs (segmented), utilities. Glass over the scrolling page.
        Rectangle {
            id: topBar
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: 60
            color: Theme.chrome
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }

            RowLayout {
                anchors { fill: parent; leftMargin: dash.gutter; rightMargin: dash.gutter }
                spacing: 16
                Row {
                    spacing: 10
                    Image { width: 32; height: 32; source: "brand/icon-128.png"; sourceSize: Qt.size(64, 64); smooth: true; mipmap: true }
                    Text { anchors.verticalCenter: parent.verticalCenter; text: "Media Vault"; color: "#FFFFFF"; font.pixelSize: 16; font.weight: Font.ExtraBold; font.letterSpacing: -0.3
                        visible: dash.width > 1080 }
                }
                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Rectangle {
                        anchors.centerIn: parent
                        width: Math.min(tabList.contentWidth + 8, parent.width)
                        height: 38; radius: 14
                        color: "#99000000"; border.color: Theme.line
                        ListView {
                            id: tabList
                            anchors { fill: parent; margins: 4 }
                            orientation: ListView.Horizontal
                            model: Tabs
                            spacing: 4
                            clip: true
                            boundsBehavior: Flickable.StopAtBounds
                            // Apple segmented control: one white pill that glides (and resizes) to the chosen tab
                            highlight: Rectangle { radius: 10; color: "#FFFFFF" }
                            highlightFollowsCurrentItem: true
                            highlightMoveDuration: 300 * Theme.motion
                            highlightResizeDuration: 300 * Theme.motion
                            highlightMoveVelocity: -1
                            highlightResizeVelocity: -1
                            delegate: Rectangle {
                                id: tab
                                readonly property bool on: tabId === dash.currentTab
                                property bool editing: false
                                // drag to reorder: this tab follows the pointer, the others slide aside to make room
                                property real dragX: 0
                                readonly property real shiftTarget: dash.tabDragFrom < 0 || index === dash.tabDragFrom ? 0
                                    : (dash.tabDragFrom < dash.tabDragTo && index > dash.tabDragFrom && index <= dash.tabDragTo) ? -(dash.tabDragW + tabList.spacing)
                                    : (dash.tabDragFrom > dash.tabDragTo && index >= dash.tabDragTo && index < dash.tabDragFrom) ? dash.tabDragW + tabList.spacing : 0
                                property real shift: shiftTarget
                                Behavior on shift { NumberAnimation { duration: 180 * Theme.motion; easing.type: Easing.OutCubic } }
                                transform: Translate { x: tab.dragX + tab.shift }
                                z: index === dash.tabDragFrom ? 3 : 1      // above the white pill (highlight, z 0) at all times
                                scale: index === dash.tabDragFrom ? 1.04 : 1
                                Behavior on scale { NumberAnimation { duration: 140 * Theme.motion } }
                                onOnChanged: if (on) { tabList.currentIndex = index; dash.currentTabName = name }
                                Component.onCompleted: if (on) { tabList.currentIndex = index; dash.currentTabName = name }
                                width: (editing ? Math.max(120, editor.implicitWidth) : tabName.implicitWidth) + 28
                                height: tabList.height; radius: 10
                                color: !on && tabArea.containsMouse ? Theme.fill : "transparent"
                                Behavior on width { NumberAnimation { duration: 200 * Theme.motion; easing.type: Easing.OutCubic } }
                                Text { id: tabName; visible: !tab.editing; anchors.centerIn: parent; text: name
                                    color: tab.on ? "#000000" : (tabArea.containsMouse ? "#FFFFFF" : "#99FFFFFF"); font.pixelSize: 12; font.weight: Font.Bold
                                    Behavior on color { ColorAnimation { duration: 200 * Theme.motion } } }
                                // double-click (or right-click) a folder tab to rename it; blank = the folder's own name
                                TextInput {
                                    id: editor
                                    visible: tab.editing
                                    anchors.centerIn: parent
                                    text: name
                                    color: tab.on ? "#000000" : "#FFFFFF"; selectionColor: Theme.blue; selectedTextColor: "#FFFFFF"
                                    font.pixelSize: 12; font.weight: Font.Bold
                                    function commit() { if (!tab.editing) return; tab.editing = false; Backend.renameTab(tabId, text) }
                                    onAccepted: commit()
                                    onActiveFocusChanged: if (!activeFocus) commit()
                                    Keys.onEscapePressed: { text = name; tab.editing = false }
                                }
                                Rectangle { visible: tab.editing; anchors.fill: parent; radius: 10; color: "transparent"; border.color: Theme.blue; border.width: 1.5 }
                                MouseArea {
                                    id: tabArea; anchors.fill: parent; hoverEnabled: true; enabled: !tab.editing
                                    cursorShape: dash.tabDragFrom === index ? Qt.ClosedHandCursor : Qt.PointingHandCursor
                                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                                    preventStealing: true
                                    property real pressX: 0
                                    property bool dragged: false
                                    function rename() { if (tabId < 0) return; tab.editing = true; editor.text = name; editor.forceActiveFocus(); editor.selectAll() }
                                    onPressed: (m) => { pressX = m.x; dragged = false }
                                    onPositionChanged: (m) => {
                                        if (!pressed || tabId < 0 || m.buttons !== Qt.LeftButton) return
                                        var dx = m.x - pressX
                                        if (!dragged && Math.abs(dx) < 6) return
                                        if (!dragged) { dragged = true; dash.tabDragFrom = index; dash.tabDragTo = index; dash.tabDragW = tab.width }
                                        tab.dragX = dx
                                        // where it would land: count the other folder tabs whose middle is left of this tab's middle
                                        var mid = tab.x + dx + tab.width / 2, to = 1
                                        for (var i = 1; i < tabList.count; i++) {
                                            var it = tabList.itemAtIndex(i)
                                            if (i !== index && it && it.x + it.width / 2 < mid) to++
                                        }
                                        dash.tabDragTo = Math.min(tabList.count - 1, to)
                                    }
                                    onReleased: {
                                        if (!dragged) return
                                        var to = dash.tabDragTo
                                        dash.tabDragFrom = -1; dash.tabDragTo = -1; tab.dragX = 0
                                        if (to !== index) Backend.moveTab(tabId, to - 1)      // All is index 0 and never moves
                                    }
                                    onClicked: (m) => {
                                        if (dragged) return
                                        if (m.button === Qt.RightButton) { rename(); return }
                                        if (tab.on) return
                                        dash.stagger = true; staggerOff.restart()
                                        dash.currentTab = tabId; dash.currentTabName = name
                                        Backend.selectTab(tabId); grid.keptY = -1; grid.userScrolled = false; grid.positionViewAtBeginning()
                                    }
                                    onDoubleClicked: rename()
                                }
                                Tip { visible: tabArea.containsMouse && tabId >= 0 && !tab.editing && dash.tabDragFrom < 0; delay: 1000
                                      text: "Drag to reorder \u00B7 double-click to rename"; y: parent.height + 8 }
                            }
                        }
                    }
                }
                Row {
                    spacing: 8
                    GlassButton { tip: "Add a folder; it becomes a tab"; small: true; label: "Add folder"; glyph: "+"; onClicked: Backend.pickFolder() }
                    GlassButton { id: insightsBtn; tip: "Watch time and favourite genres"; small: true; label: "Insights"; glyph: "●"; glyphColor: Theme.blue
                        active: insightsSheet.shown > 0.5; onClicked: insightsSheet.open(insightsBtn) }
                    GlassButton { tip: Backend.updateCount > 0 ? (Backend.updateCount === 1 ? "1 update is waiting (About & Updates)" : Backend.updateCount + " updates are waiting (About & Updates)")
                                                              : "Themes, playback, folders, help"
                        id: settingsBtn; small: true; label: "Settings"; glyph: "\u2699"; glyphColor: Theme.green
                        onClicked: settings.open(settingsBtn)
                        Badge { count: Backend.updateCount; anchors { right: parent.right; top: parent.top; rightMargin: -5; topMargin: -5 } } }
                }
            }
        }
    }

    // ---- overlays
    DetailView { id: detail; anchors.fill: parent; onChooseThumbnail: (key, source) => picker.begin(key, source); onPlayRequested: (start) => dash.launch(start, "", 450) }
    PickerView { id: picker; anchors.fill: parent }
    SettingsView { id: settings; anchors.fill: parent; onThemeChosen: (id) => dash.switchTheme(id)
        onConfigureFolder: (id, source) => folderConfig.show(id, source)
        onOpenTagManager: (source) => tagManager.show(source, 0) }
    FolderConfig { id: folderConfig; anchors.fill: parent; onChanged: settings.folders = Backend.directories() }
    TagManager { id: tagManager; anchors.fill: parent }
    FolderSheet { id: folderSheet; anchors.fill: parent }
    InsightsSheet { id: insightsSheet; anchors.fill: parent }
    Connections { target: Backend; function onFolderPicked(path, name) { folderSheet.open(path, name) } }

    Rectangle {
        id: toast
        z: 50
        opacity: 0
        visible: opacity > 0
        anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 24 + 12 * (1 - opacity) }
        width: Math.min(toastText.implicitWidth + 36, parent.width - 48); height: 40; radius: 12
        color: Theme.slate; border.color: "#33FFFFFF"
        Behavior on opacity { NumberAnimation { duration: 200 * Theme.motion; easing.type: Easing.OutCubic } }
        Text { id: toastText; anchors.centerIn: parent; width: Math.min(implicitWidth, parent.width - 36); elide: Text.ElideRight
            color: Theme.text; font.family: Theme.mono; font.pixelSize: 12 }
        Timer { id: toastHide; interval: 3500; onTriggered: toast.opacity = 0 }
    }
    Image { id: themeShot; anchors.fill: parent; z: 90; opacity: 0; visible: opacity > 0; cache: false }
    NumberAnimation { id: themeFade; target: themeShot; property: "opacity"; to: 0; duration: 450; easing.type: Easing.InOutQuad
        onFinished: themeShot.source = "" }

    Rectangle {
        id: curtain
        anchors.fill: parent
        z: 100
        color: "#000000"
        opacity: 0
        visible: opacity > 0
        MouseArea { anchors.fill: parent; hoverEnabled: true }     // nothing underneath reacts while it is dark
    }

    Connections {
        target: Backend
        function onToast(message) { toastText.text = message; toast.opacity = 1; toastHide.restart() }
        function onThumbnailsReady(n) { picker.show(n) }
    }
}
