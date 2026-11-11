// "View More". Clicking a poster lifts it out of the grid as a 3D DVD box: the box spins while it flies and grows
// into the left pane of this sheet; closing (x, Esc, or a click outside the sheet) flies it back onto its card.
// Play turns the box to face you, swings the cover open on its spine and hands over to the dashboard,
// which fades to black and starts the player.
// Editable: title, description, tags, rating, notes, box art. Read-only (locked): everything read from the file.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    property string itemKey: ""
    property var d: ({})
    // box sets: a carousel of the set's own box and each film. `cur` is what the 3D box shows.
    property int slide: 0
    readonly property var slides: d.isSet ? (d.slides || []) : []
    readonly property int count: slides.length
    readonly property var cur: count > 0 ? slides[Math.min(slide, count - 1)] : d
    // what the right pane describes: the set's own page on its first slide, else the film shown (full details)
    readonly property bool setSlide: d.isSet === true && !cur.uuid
    property var fd: ({})
    readonly property var info: d.isSet && cur.uuid ? fd : d
    readonly property string infoKey: info.key || itemKey
    // right-pane sections, in the user's order; which ones apply depends on what is shown
    property var order: Backend.detailSections().map(function(x) { return x.id })
    property bool renaming: false            // box sets: the title is a dropdown until "Rename" is chosen
    property var titleEditor: null
    function showSection(id) {
        switch (id) {
        case "title": return true
        case "rating": return !setSlide
        case "meta": return (info.facts || []).length > 0
        case "synopsis": case "tags": case "notes": return !setSlide
        case "cast": return !setSlide && (info.cast || []).length > 0
        case "gallery": return !setSlide
        case "boxset": return info.canSet === true
        case "list": return (d.episodes || []).length > 0
        }
        return false
    }
    function goTo(uuid) {
        var target = slides.findIndex(function(x) { return x.uuid === uuid })
        if (target < 0) target = 0          // "" = the box set itself
        step(target - slide)
    }
    onCurChanged: fd = (d.isSet && cur.uuid) ? Backend.detail(cur.uuid) : ({})
    // after a film joins or leaves a set: the set may have shrunk to nothing, or this film's page changed
    function afterSetChange() {
        if (d.isSet) {
            var next = Backend.detail(itemKey)
            if (!next.key || !next.isSet || (next.episodes || []).length === 0) { close(); return }
        }
        refresh()
    }
    function refresh() { var s = slide; d = Backend.detail(itemKey); slide = Math.min(s, Math.max(0, (d.slides || []).length - 1)); if (d.isSet && cur.uuid) fd = Backend.detail(cur.uuid) }
    function wrap(i) { return (i % count + count) % count }
    // jump: how many slides to move (the arrows move one; a click in the films list may move several)
    function step(jump) {
        if (count < 2 || jump === 0 || turnOut.running || turnIn.running || closing || launching || f < 1) return
        var dir = jump > 0 ? 1 : -1
        turnOut.dir = dir; turnOut.jump = jump
        // the next edge-on angle (90 + 180k) in the turning direction
        var y = box.yaw, k = Math.floor((y - 90) / 180)
        var edge = dir > 0 ? (k + 1) * 180 + 90 : (90 + 180 * k < y ? 90 + 180 * k : 90 + 180 * (k - 1))
        turnOutYaw.to = edge
        turnOutSwipe.to = -46 * dir
        box.spinning = false
        turnOut.start()
    }
    property real f: 0                       // 0 = box sits on its card, 1 = box settled in the sheet
    property rect from: Qt.rect(0, 0, 0, 0)  // what opened it, in this item's coordinates: a card's poster, or a button
    property bool fromCard: false            // a poster: the box IS the poster (fully visible from the start)
    property bool closing: false
    property bool launching: false
    readonly property real sheetIn: Math.max(0, Math.min(1, (f - 0.35) / 0.65))   // the sheet arrives in the second half
    signal chooseThumbnail(string key, var source)
    signal playRequested(var start)          // start() begins playback; the dashboard runs the fade to black first

    visible: false
    focus: visible
    z: 20

    property real startYaw: 0
    // kind: "card" (a poster), "spine" (shelf view: flies out spine-first) or "button" (grows out of a button)
    function open(key, rect, kind) {
        if (kind === true) kind = "card"
        itemKey = key
        slide = 0
        renaming = false
        order = Backend.detailSections().map(function(x) { return x.id })
        d = Backend.detail(key)
        from = rect || Qt.rect(width / 2 - 20, height / 2 - 20, 40, 40)
        fromCard = kind === "card" || kind === "spine"
        startYaw = kind === "spine" ? 90 : 0
        closing = false; launching = false
        pullOut.stop(); packUp.stop(); spread = 0; neighFade = 1
        box.spinning = Qt.binding(function() { return root.f === 1 && !root.closing && !root.launching && !root.turning })
        box.opened = 0
        box.zoom = 1
        box.yaw = startYaw                   // front-on (poster) or side-on (spine): looks exactly like what it came from
        visible = true
        forceActiveFocus()
        flyOut.stop()
        flyIn.restart()
    }
    function closeMenus() { titleMenu.close(); setMenu.close(); matchMenu.close(); castMenu.close() }
    function close() {
        if (!visible || closing || launching) return
        closeMenus()
        closing = true
        flyIn.stop(); turnOut.stop(); turnIn.stop(); pullOut.stop(); box.swipe = 0; root.neighFade = 1
        box.spinning = false
        if (count > 1 && (spread > 0.01 || slide !== 0)) {
            // quick: the films slide back into the set; a film in focus turns edge-on and becomes the set's box
            packUp.turnHome = slide !== 0
            var y = box.yaw, k = Math.floor((y - 90) / 180)
            packYaw.to = slide !== 0 ? (k + 1) * 180 + 90 : y
            packUp.restart()
            return
        }
        flyHome()
    }
    function flyHome() {
        // spin on in the same direction and land front-on, so the box turns back into the flat poster
        var target = Math.floor((box.yaw - startYaw) / 360) * 360 + startYaw
        if (box.yaw - target < 180) target -= 360
        flyOutYaw.to = target
        flyOut.restart()
    }
    function dismiss() {                     // instant, used once the player has taken over the screen
        closeMenus()
        flyIn.stop(); flyOut.stop(); launchBox.stop(); turnOut.stop(); turnIn.stop(); box.swipe = 0; root.neighFade = 1
        pullOut.stop(); packUp.stop(); spread = 0
        visible = false; closing = false; launching = false; f = 0; box.opened = 0
    }
    // episode: a file's uuid ("" = this card); fromStart: ignore where you stopped last time
    function play(episode, fromStart) {
        if (launching) return
        launching = true
        var key = episode || itemKey, again = fromStart === true
        launchYaw.to = Math.floor(box.yaw / 360) * 360 + 20     // face the camera, turned a little to show the hinge
        launchBox.restart()
        playRequested(function() { Backend.playFrom(key, again) })
    }
    Keys.onEscapePressed: close()
    Keys.onLeftPressed: step(-1)
    Keys.onRightPressed: step(1)

    // carousel turn: the box spins edge-on, swaps to the neighbouring film there (unseen), then turns on to face
    // you, sliding in from the side the arrow points to. The greyed covers behind it cross-fade to the new neighbours.
    ParallelAnimation {
        id: turnOut
        property int dir: 1
        property int jump: 1
        NumberAnimation { id: turnOutYaw; target: box; property: "yaw"; duration: 170 * Theme.motion; easing.type: Easing.InCubic }
        NumberAnimation { id: turnOutSwipe; target: box; property: "swipe"; duration: 170 * Theme.motion; easing.type: Easing.InCubic }
        NumberAnimation { target: root; property: "neighFade"; to: 0; duration: 140 * Theme.motion }
        onFinished: {
            root.slide = root.wrap(root.slide + jump)
            box.yaw = -90 * dir                   // the new box, edge-on from the other side
            box.swipe = 46 * dir
            turnInYaw.to = -20 * dir              // lands facing you, turned a little to show its depth
            turnIn.start()
        }
    }
    ParallelAnimation {
        id: turnIn
        NumberAnimation { id: turnInYaw; target: box; property: "yaw"; duration: 320 * Theme.motion; easing.type: Easing.OutCubic }
        NumberAnimation { target: box; property: "swipe"; to: 0; duration: 320 * Theme.motion; easing.type: Easing.OutCubic }
        NumberAnimation { target: root; property: "neighFade"; to: 1; duration: 260 * Theme.motion }
        onFinished: box.spinning = Qt.binding(function() { return root.f === 1 && !root.closing && !root.launching && !root.turning })
    }
    readonly property bool turning: turnOut.running || turnIn.running

    // box sets: the films are pulled out of the set's box into a floating carousel (spread 0 -> 1), bob in a slow
    // wave while idle, and slide back into the box when you leave (spread -> 0) before it flies home
    property real spread: 0
    property real neighFade: 1
    property real wave: 0
    NumberAnimation on wave {
        from: 0; to: Math.PI * 2; duration: 2800; loops: Animation.Infinite
        running: root.visible && root.count > 1 && root.f === 1 && Theme.motion > 0
    }
    NumberAnimation { id: pullOut; target: root; property: "spread"; to: 1; duration: 520 * Theme.motion; easing.type: Easing.OutBack; easing.overshoot: 1.15 }
    ParallelAnimation {
        id: packUp
        property bool turnHome: false
        NumberAnimation { target: root; property: "spread"; to: 0; duration: 170 * Theme.motion; easing.type: Easing.InCubic }
        NumberAnimation { id: packYaw; target: box; property: "yaw"; duration: 170 * Theme.motion; easing.type: Easing.InCubic }
        onFinished: {
            if (turnHome) { root.slide = 0; box.yaw = -90 }   // swapped while edge-on: the set's own box flies home
            root.flyHome()
        }
    }

    ParallelAnimation {
        id: flyIn
        NumberAnimation { target: root; property: "f"; from: 0; to: 1; duration: 700 * Theme.motion; easing.type: Easing.OutCubic }
        NumberAnimation { target: box; property: "yaw"; from: root.startYaw; to: -388; duration: 700 * Theme.motion; easing.type: Easing.OutCubic }
        onFinished: if (root.count > 1 && !root.closing) pullOut.restart()
    }
    ParallelAnimation {
        id: flyOut
        NumberAnimation { target: root; property: "f"; to: 0; duration: (root.count > 1 ? 360 : 480) * Theme.motion; easing.type: Easing.InOutCubic }
        NumberAnimation { id: flyOutYaw; target: box; property: "yaw"; duration: (root.count > 1 ? 360 : 480) * Theme.motion; easing.type: Easing.InOutCubic }
        onFinished: { root.visible = false; root.closing = false; Backend.reload() }   // edits show in the grid now
    }
    SequentialAnimation {
        id: launchBox
        NumberAnimation { id: launchYaw; target: box; property: "yaw"; duration: 450 * Theme.motion; easing.type: Easing.OutCubic }
        NumberAnimation { target: box; property: "opened"; from: 0; to: 1; duration: 700 * Theme.motion; easing.type: Easing.OutCubic }
    }

    // dim + click-outside-to-close
    Rectangle { anchors.fill: parent; color: Theme.scrim; opacity: root.f }
    MouseArea {
        anchors.fill: parent
        onClicked: root.close()
        onWheel: (w) => w.accepted = true     // the grid must not scroll away under the box: it flies back to its card
    }

    Rectangle {
        id: sheet
        anchors.centerIn: parent
        // grows with the window (up to a comfortable maximum) instead of staying a fixed card on a big screen
        width: Math.min(root.width - 48, Math.max(1120, Math.min(1900, root.width * 0.84)))
        height: Math.min(root.height - 48, Math.max(720, Math.min(1240, root.height * 0.88)))
        radius: 16
        color: Theme.panel
        border.color: Theme.lineStrong
        clip: true
        opacity: root.sheetIn
        // grows out of whatever opened it (the card or the button) and shrinks back into it
        transform: Scale { origin.x: root.from.x + root.from.width / 2 - sheet.x; origin.y: root.from.y + root.from.height / 2 - sheet.y
                           xScale: 0.06 + 0.94 * root.sheetIn; yScale: xScale }
        MouseArea { anchors.fill: parent }            // clicks on the sheet must not close the view

        // left pane: the box lands here (the box itself lives above the sheet, see DvdBox below)
        Rectangle {
            id: stage
            width: Math.max(380, Math.round(sheet.width * 0.42))
            height: sheet.height
            radius: sheet.radius
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#E6000000" }
                GradientStop { position: 1.0; color: Theme.graphite }
            }
            Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.line }

            Column {
                visible: root.count > 1
                anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: 20 }
                spacing: 8
                Text { anchors.horizontalCenter: parent.horizontalCenter; text: (root.cur.label || "").toUpperCase()
                    color: Theme.faint; font.family: Theme.mono; font.pixelSize: 10; font.weight: Font.Bold }
                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 6
                    Repeater {
                        model: root.count
                        Rectangle { width: index === root.slide ? 16 : 6; height: 6; radius: 3; color: index === root.slide ? Theme.text : "#4DFFFFFF"
                            Behavior on width { NumberAnimation { duration: 220 * Theme.motion; easing.type: Easing.OutCubic } } }
                    }
                }
            }

            // box art: your own covers for titles the scraper missed (or art you prefer)
            Column {
                id: artTools
                anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 18 }
                spacing: 8
                Text { anchors.horizontalCenter: parent.horizontalCenter; text: "ADD / CHANGE BOX ART ASSETS"; color: Theme.faint; font.family: Theme.mono; font.pixelSize: 10 }
                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 6
                    Repeater {
                        model: [["wrap", "Whole cover", false], ["front", "Front", root.cur.customFront], ["spine", "Spine", root.cur.customSpine], ["back", "Back", root.cur.customBack], ["disc", "Disc", root.cur.customDisc]]
                        GlassButton { small: true; label: modelData[1] + (modelData[2] ? " \u2713" : "\u2026"); onClicked: Backend.pickBoxArt(root.cur.key || root.itemKey, modelData[0])
                            tip: modelData[0] === "wrap" ? "One scan of the whole sleeve (back, spine and front side by side): Media Vault finds the spine and wraps it round the box" : "" }
                    }
                    GlassButton {
                        small: true; label: "Reset"
                        visible: root.cur.customFront === true || root.cur.customBack === true || root.cur.customSpine === true || root.cur.customDisc === true
                        onClicked: ["front", "spine", "back", "disc"].forEach(function(f) { Backend.resetBoxArt(root.cur.key || root.itemKey, f) })
                    }
                }
            }
        }

        // right pane: metadata
        Item {
            id: pane
            anchors { left: stage.right; right: parent.right; top: parent.top; bottom: parent.bottom }
            transform: Translate { x: 24 * (1 - root.sheetIn) }

            Flickable {
                id: flick
                SmoothWheel { view: flick; step: 160 }
                anchors { left: parent.left; right: parent.right; top: parent.top; bottom: actions.top; leftMargin: 32; rightMargin: 20; topMargin: 28; bottomMargin: 12 }
                contentHeight: col.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar {}
                ColumnLayout {
                    id: col
                    width: flick.width - 14
                    spacing: 14

                    // fixed header: what this is, and the tools for it
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.rightMargin: 48                 // clear of the close button
                        spacing: 10
                        Text {
                            text: root.setSlide ? "BOX SET · " + (root.d.episodes || []).length + " FILMS"
                                  : root.d.isSet ? (root.cur.label + " · " + (root.d.title || "")).toUpperCase()
                                  : ((root.d.isShow ? "SERIES" : "MOVIE") + (root.d.year ? " · " + root.d.year : ""))
                            elide: Text.ElideRight; Layout.fillWidth: true
                            color: Theme.faint; font.family: Theme.mono; font.pixelSize: 11; font.weight: Font.Bold
                        }
                        GlassButton { small: true; visible: root.setSlide; label: "Ungroup"; tip: "Split this box set back into separate films"
                            onClicked: { Backend.ungroupSet(root.itemKey); root.close() } }
                        GlassButton { id: matchBtn; small: true; visible: root.info.canMatch === true; label: "Fix Scraped Data\u2026"
                            tip: matchMenu.opened ? "" : "Wrong title or cover? Search TMDB yourself"; onClicked: matchMenu.begin() }
                    }
                    // the sections, in the order chosen in Settings > Appearance > View More layout
                    Repeater {
                        model: root.order
                        Loader {
                            Layout.fillWidth: true
                            Layout.topMargin: modelData === "title" ? -8 : 0
                            active: root.showSection(modelData)
                            visible: active
                            sourceComponent: ({ title: secTitle, rating: secRating, meta: secMeta, synopsis: secSynopsis, cast: secCast, gallery: secGallery,
                                                tags: secTags, boxset: secBoxSet, notes: secNotes, list: secList })[modelData] || null
                        }
                    }
                }
            }

            component Caption: Text { color: Theme.faint; font.family: Theme.mono; font.pixelSize: 11 }

            // ---- title. In a box set it is also a dropdown of the set's films (the arrow says so)
            Component {
                id: secTitle
                ColumnLayout {
                id: titleCol
                spacing: 2
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    TextMetrics { id: tm; font: titleField.font; text: titleField.text }
                    Field {
                        id: titleField
                        readonly property bool picker: root.d.isSet === true && !root.renaming
                        Layout.preferredWidth: picker ? Math.min(tm.advanceWidth + 6, titleCol.width - 48) : titleCol.width - 40
                        Layout.rightMargin: picker ? 0 : 40
                        text: root.info.title || ""
                        font.pixelSize: 28; font.weight: Font.ExtraBold; font.letterSpacing: -0.6
                        leftPadding: 0; rightPadding: 0
                        readOnly: picker
                        // not editing: a marquee shows the title (and scrolls it on hover); click to edit
                        color: activeFocus && !picker ? Theme.text : "transparent"
                        HoverHandler { id: titleHover }
                        Marquee {
                            visible: !titleField.activeFocus || titleField.picker
                            anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter }
                            text: titleField.text; font: titleField.font; color: Theme.text
                            active: titleHover.hovered
                        }
                        background: Rectangle { color: "transparent"; Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1
                            color: titleField.activeFocus && !titleField.picker ? Theme.blue : "transparent" } }
                        MouseArea { anchors.fill: parent; visible: titleField.picker; cursorShape: Qt.PointingHandCursor; onClicked: titleMenu.begin(chev) }
                        onActiveFocusChanged: if (!activeFocus && !picker) {
                            if (text !== root.info.title) { Backend.setTitle(root.infoKey, text); root.info.title = text }
                            root.renaming = false
                        }
                        Component.onCompleted: root.titleEditor = titleField
                    }
                    // dropdown arrow, right after the title
                    Rectangle {
                        id: chev
                        visible: root.d.isSet === true
                        width: 28; height: 28; radius: 14
                        color: chevArea.containsMouse || titleMenu.opened ? Qt.rgba(1, 1, 1, 0.14) : Qt.rgba(1, 1, 1, 0.06)
                        Behavior on color { ColorAnimation { duration: 120 * Theme.motion } }
                        Canvas {
                            anchors.centerIn: parent; width: 12; height: 8
                            rotation: titleMenu.opened ? 180 : 0
                            Behavior on rotation { NumberAnimation { duration: 200 * Theme.motion; easing.type: Easing.OutCubic } }
                            onPaint: { var c = getContext("2d"); c.reset(); c.strokeStyle = "#FFFFFF"; c.lineWidth = 1.8; c.lineCap = "round"; c.lineJoin = "round"
                                c.beginPath(); c.moveTo(1.5, 1.5); c.lineTo(6, 6); c.lineTo(10.5, 1.5); c.stroke() }
                        }
                        MouseArea { id: chevArea; anchors.fill: parent; anchors.margins: -4; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: titleMenu.begin(chev) }
                    }
                    Item { Layout.fillWidth: true }
                }
                // the original title (or the English one, with Titles set to Original): small, searchable too
                Text {
                    visible: (root.info.subtitle || "") !== ""
                    Layout.fillWidth: true
                    Layout.rightMargin: 40
                    text: root.info.subtitle || ""
                    color: Theme.muted; font.pixelSize: 15; font.weight: Font.Medium
                    elide: Text.ElideRight
                }
                // every other title: English, Romanized, Native, then other languages (folded away until asked for)
                ColumnLayout {
                    id: altGrid
                    property bool showOther: false
                    visible: (root.info.altTitles || []).length > 0
                    Layout.fillWidth: true
                    Layout.rightMargin: 40
                    Layout.topMargin: 6
                    spacing: 4
                    Repeater {
                        model: root.info.altTitles || []
                        delegate: Item {     // one row per group: its name, then its titles
                            readonly property bool folded: modelData.group === "other" && !altGrid.showOther
                            Layout.fillWidth: true
                            implicitHeight: altRow.implicitHeight
                            RowLayout {
                                id: altRow
                                width: altGrid.width
                                spacing: 12
                                Text { Layout.preferredWidth: 104; Layout.alignment: Qt.AlignTop; topPadding: 1
                                    text: modelData.label.toUpperCase(); color: Theme.faint; font.family: Theme.mono; font.pixelSize: 10 }
                                Text {
                                    Layout.fillWidth: true
                                    text: parent.parent.folded ? modelData.titles.length + (modelData.titles.length === 1 ? " title" : " titles") + " \u2014 show"
                                                               : modelData.titles.join("  \u00B7  ")
                                    color: parent.parent.folded ? Theme.blue : Theme.muted
                                    font.pixelSize: 12; wrapMode: Text.Wrap
                                    MouseArea { anchors.fill: parent; enabled: modelData.group === "other"
                                        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                                        onClicked: altGrid.showOther = !altGrid.showOther }
                                }
                            }
                        }
                    }
                }
                }
            }

            // ---- star ratings: the audience score (scraped) and yours
            Component {
                id: secRating
                ColumnLayout {
                    spacing: 6
                    // TMDB / IMDb: five stars out of 10
                    RowLayout {
                        visible: root.info.score !== undefined && root.info.score !== null && root.info.scoreSource !== "anilist"
                        spacing: 10
                        Caption { text: "AUDIENCE"; Layout.preferredWidth: 84 }
                        Item {
                            implicitWidth: audBack.implicitWidth; implicitHeight: audBack.implicitHeight
                            Text { id: audBack; text: "\u2605\u2605\u2605\u2605\u2605"; color: Theme.edge; font.pixelSize: 18 }
                            Item {   // filled part: the score as a fraction of five stars
                                width: audBack.width * Math.max(0, Math.min(1, (root.info.score || 0) / 10)); height: audBack.height; clip: true
                                Text { text: "\u2605\u2605\u2605\u2605\u2605"; color: Theme.amber; font.pixelSize: 18 }
                            }
                        }
                        Text { text: (root.info.score || 0).toFixed(1) + " / 10"; color: Theme.dim; font.family: Theme.mono; font.pixelSize: 12 }
                    }
                    // AniList: its average score as a percentage, with AniList's own colours (green 75+, orange 61+, red below)
                    RowLayout {
                        readonly property int pct: Math.round((root.info.score || 0) * 10)
                        readonly property color tone: pct >= 75 ? "#7BD555" : pct >= 61 ? "#F79A63" : "#E85D75"
                        visible: root.info.score !== undefined && root.info.score !== null && root.info.scoreSource === "anilist"
                        spacing: 10
                        Caption { text: "ANILIST"; Layout.preferredWidth: 84 }
                        Text { text: parent.pct + "%"; color: parent.tone; font.pixelSize: 20; font.weight: Font.ExtraBold }
                        Rectangle {
                            Layout.preferredWidth: 120; Layout.preferredHeight: 6; radius: 3; color: Theme.fill
                            Rectangle { width: parent.width * Math.min(1, parent.parent.pct / 100); height: parent.height; radius: 3; color: parent.parent.tone }
                        }
                        Text { text: "average score"; color: Theme.dim; font.family: Theme.mono; font.pixelSize: 11 }
                    }
                    RowLayout {
                        spacing: 10
                        Caption { text: "YOUR SCORE"; Layout.preferredWidth: 84 }
                        Row {
                            id: stars
                            spacing: 2
                            property int value: root.info.rating || 0
                            Repeater {
                                model: 5
                                Text {
                                    text: index < stars.value ? "\u2605" : "\u2606"
                                    color: index < stars.value ? Theme.green : "#4DFFFFFF"; font.pixelSize: 22
                                    MouseArea {
                                        anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                        onClicked: { stars.value = (stars.value === index + 1) ? 0 : index + 1; Backend.setRating(root.infoKey, stars.value) }
                                    }
                                }
                            }
                        }
                        Text { visible: stars.value === 0; text: "Tap to rate"; color: Theme.faint; font.pixelSize: 11 }
                    }
                }
            }

            // ---- read-only facts from the file (resolution, codec, file type, audio, frame rate, length)
            Component {
                id: secMeta
                Flow {
                    spacing: 6
                    Repeater {
                        model: root.info.facts || []
                        Rectangle {
                            height: 26; width: lockRow.implicitWidth + 18; radius: 6; color: "#99000000"; border.color: Theme.line
                            Row {
                                id: lockRow; anchors.centerIn: parent; spacing: 6
                                Text { text: modelData.label.toUpperCase(); color: "#66FFFFFF"; font.family: Theme.mono; font.pixelSize: 10; anchors.verticalCenter: parent.verticalCenter }
                                Text { text: modelData.value; color: "#D9FFFFFF"; font.family: Theme.mono; font.pixelSize: 11; anchors.verticalCenter: parent.verticalCenter }
                            }
                        }
                    }
                }
            }

            Component {
                id: secSynopsis
                ColumnLayout {
                    spacing: 8
                    Caption { text: "SYNOPSIS" }
                    Area {
                        Layout.fillWidth: true; Layout.preferredHeight: 104
                        placeholderText: "Description"
                        text: root.info.synopsis || ""
                        onActiveFocusChanged: if (!activeFocus && text !== root.info.synopsis) { Backend.setSynopsis(root.infoKey, text); root.info.synopsis = text }
                    }
                }
            }

            // ---- cast: photo, name and part, scrolling sideways
            Component {
                id: secCast
                ColumnLayout {
                    spacing: 8
                    Caption { text: "CAST" }
                    ListView {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 132
                        orientation: ListView.Horizontal
                        spacing: 12
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        model: root.info.cast || []
                        ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }
                        delegate: Column {
                            width: 76
                            spacing: 5
                            Rectangle {
                                width: 64; height: 64; radius: 32
                                anchors.horizontalCenter: parent.horizontalCenter
                                color: Theme.slate; border.color: Theme.line
                                Image { anchors.fill: parent; source: modelData.photo; fillMode: Image.PreserveAspectCrop; asynchronous: true
                                    sourceSize.width: 128; sourceSize.height: 128; visible: modelData.photo !== "" }   // saved round already
                                Text { visible: modelData.photo === ""; anchors.centerIn: parent; color: "#B3FFFFFF"; font.pixelSize: 18; font.weight: Font.Bold
                                    text: modelData.name.split(" ").filter(function(w) { return w.length }).slice(0, 2).map(function(w) { return w[0] }).join("") }
                            }
                            Text { width: parent.width; text: modelData.name; color: Theme.text; font.pixelSize: 11; font.weight: Font.DemiBold
                                horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight }
                            Text { width: parent.width; text: modelData.role; color: Theme.faint; font.pixelSize: 10
                                horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight }
                        }
                    }
                }
            }

            // ---- Gallery: wide stills (scraped, or your own); they also play behind the recommended carousel
            Component {
                id: secGallery
                ColumnLayout {
                    spacing: 8
                    RowLayout {
                        Layout.fillWidth: true
                        Caption { text: "GALLERY"; Layout.fillWidth: true }
                        GlassButton { small: true; label: "Add images\u2026"; glyph: "+"; onClicked: Backend.addGalleryImages(root.infoKey) }
                    }
                    ListView {
                        id: galleryList
                        visible: (root.info.gallery || []).length > 0
                        Layout.fillWidth: true
                        Layout.preferredHeight: 104
                        orientation: ListView.Horizontal
                        spacing: 10
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        model: root.info.gallery || []
                        ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }
                        delegate: Rectangle {
                            width: 160; height: 90; radius: 8; color: Theme.slate; border.color: shotArea.containsMouse ? "#66FFFFFF" : Theme.line
                            clip: true
                            Image { anchors.fill: parent; source: modelData.url; fillMode: Image.PreserveAspectCrop; asynchronous: true
                                sourceSize.width: 320; sourceSize.height: 180 }
                            MouseArea { id: shotArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: lightbox.open(index) }
                            Rectangle {      // remove
                                visible: shotArea.containsMouse || xArea.containsMouse
                                anchors { top: parent.top; right: parent.right; margins: 5 }
                                width: 22; height: 22; radius: 11; color: xArea.containsMouse ? Theme.red : "#CC000000"
                                Text { anchors.centerIn: parent; text: "\u2715"; color: "#FFFFFF"; font.pixelSize: 10 }
                                MouseArea { id: xArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                    onClicked: Backend.removeGalleryImage(root.infoKey, modelData.name) }
                            }
                            Rectangle { visible: modelData.custom; anchors { left: parent.left; bottom: parent.bottom; margins: 5 } width: 34; height: 16; radius: 4
                                color: "#CC000000"; Text { anchors.centerIn: parent; text: "YOURS"; color: "#FFFFFF"; font.family: Theme.mono; font.pixelSize: 8 } }
                        }
                    }
                    Text { visible: (root.info.gallery || []).length === 0; Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.faint; font.pixelSize: 12
                        text: "No images yet. Stills from TMDB or AniList arrive with scraping (Gallery images in the folder's scrape options, or Fetch missing), or add your own." }
                }
            }

            Component {
                id: secTags
                ColumnLayout {
                    spacing: 8
                    Caption { text: "TAGS" }
                    Flow {
                        Layout.fillWidth: true; spacing: 6
                        Repeater {
                            model: root.info.tags || []
                            Pill {
                                // genres (blue, scraped), automatic tags from folders and file names (grey), yours (green)
                                // studios (amber, from AniList, kept) and genres (blue, scraped) cannot be removed here
                                readonly property bool fixed: modelData.genre || modelData.studio
                                label: (modelData.genre ? modelData.name.substring(6) : modelData.studio ? modelData.name.substring(7)
                                        : modelData.auto ? modelData.name.substring(5) : modelData.name) + (fixed ? "" : "   \u00D7")
                                accent: modelData.genre ? Theme.blue : modelData.studio ? Theme.amber : modelData.auto ? Theme.muted : Theme.green
                                onClicked: if (!fixed) { Backend.removeTag(root.infoKey, modelData.name); root.refresh() }
                            }
                        }
                    }
                    TagField {
                        Layout.fillWidth: true
                        placeholderText: "Add a tag and press Enter (your tags are suggested as you type)"
                        exclude: (root.info.tags || []).map(function(t) { return t.name })
                        onChosen: (name) => { Backend.addTag(root.infoKey, name); root.refresh() }
                    }
                }
            }

            // ---- box set membership: films only. Add to a set (or a new one), move to another, or take it out
            Component {
                id: secBoxSet
                ColumnLayout {
                    spacing: 8
                    Caption { text: "BOX SET" }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 6
                        Pill { visible: !!(root.info.boxSet && root.info.boxSet.key); label: (root.info.boxSet && root.info.boxSet.name || "") + "   \u00D7"
                            accent: Theme.amber; onClicked: { Backend.removeFromSet(root.infoKey); root.afterSetChange() } }
                        GlassButton { id: setBtn; small: true; label: root.info.boxSet && root.info.boxSet.key ? "Move to another\u2026" : "Add to a box set\u2026"
                            onClicked: setMenu.begin(setBtn) }
                    }
                }
            }

            Component {
                id: secNotes
                ColumnLayout {
                    spacing: 8
                    Caption { text: "PRIVATE NOTES" }
                    Area {
                        Layout.fillWidth: true; Layout.preferredHeight: 72
                        placeholderText: "Only you see these"
                        text: root.info.note || ""
                        onActiveFocusChanged: if (!activeFocus) Backend.setNote(root.infoKey, text)
                    }
                }
            }

            // ---- episodes of a series, or the films of a box set
            Component {
                id: secList
                ColumnLayout {
                    spacing: 4
                    Caption { text: root.d.isSet ? "FILMS" : "EPISODES"; Layout.bottomMargin: 4 }
                    Repeater {
                        model: root.d.episodes || []
                        Rectangle {
                            Layout.fillWidth: true; height: 38; radius: 10
                            readonly property bool shown: root.count > 0 && root.cur.uuid === modelData.uuid
                            color: epArea.containsMouse ? Theme.fillHover : Theme.slate
                            border.color: shown ? Theme.blue : Theme.line
                            Behavior on border.color { ColorAnimation { duration: 160 * Theme.motion } }
                            clip: true
                            Marquee { x: 14; anchors.verticalCenter: parent.verticalCenter; text: modelData.title; color: Theme.text; font.pixelSize: 13; font.weight: Font.Medium; width: parent.width - 56; active: epArea.containsMouse }
                            Text { visible: modelData.done && !(root.d.isSet && epArea.containsMouse); anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter } text: "\u2713"; color: Theme.green; font.pixelSize: 15; font.weight: Font.Bold }
                            Rectangle { visible: modelData.progress > 0; anchors.bottom: parent.bottom; height: 3; width: parent.width * modelData.progress; color: Theme.green }
                            Rectangle {     // box set: take this film out of the set
                                z: 2
                                visible: root.d.isSet === true && (epArea.containsMouse || outArea.containsMouse)
                                anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter }
                                width: outText.implicitWidth + 16; height: 24; radius: 6
                                color: outArea.containsMouse ? Qt.rgba(1, 1, 1, 0.16) : Qt.rgba(1, 1, 1, 0.08)
                                Text { id: outText; anchors.centerIn: parent; text: "Remove from set"; color: "#CCFFFFFF"; font.pixelSize: 11 }
                                MouseArea { id: outArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                    onClicked: { Backend.removeFromSet(modelData.uuid); root.afterSetChange() } }
                            }
                            MouseArea { id: epArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                // a box set: show that film on the carousel (click again to play); a series: play the episode
                                onClicked: {
                                    if (root.count === 0 || parent.shown) { root.play(modelData.uuid, false); return }
                                    root.goTo(modelData.uuid)
                                } }
                        }
                    }
                }
            }
            // actions stay pinned under the scrolling fields, so Play is never below the fold
            Item {
                id: actions
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                height: 76
                Rectangle { width: parent.width; height: 1; color: Theme.line }
                Row {
                    anchors { left: parent.left; leftMargin: 32; verticalCenter: parent.verticalCenter }
                    spacing: 10
                    // part-watched: Resume (where you stopped) and Play from start; otherwise just Play
                    GlassButton { label: root.info.resume ? "Resume" : "Play"; glyph: "\u25B6"; primary: true
                        tip: root.info.resume ? "From " + root.info.resumeAt : ""; onClicked: root.play(root.cur.uuid || "", false) }
                    GlassButton { visible: root.info.resume === true; label: "From start"; glyph: "\u21BA"; tip: "Play from the beginning"
                        onClicked: root.play(root.cur.uuid || "", true) }
                    GlassButton { visible: !root.setSlide; tip: "Choose thumbnail: pick a frame from the video as the cover"; id: thumbBtn; label: pane.width < 640 ? "" : "Choose thumbnail"; iconKind: "snapshot"; glyphColor: Theme.blue; onClicked: root.chooseThumbnail(root.infoKey, thumbBtn) }
                    GlassButton { tip: "Play on AirPlay or Chromecast"; id: castBtn; label: pane.width < 640 ? "" : "Play on\u2026"; iconKind: "airplay"; glyphColor: Theme.green
                        onClicked: { castMenu.devices = Backend.devices(); if (castMenu.devices.length === 0) Backend.findDevices(); castMenu.open() } }
                }
            }
        }

        // close
        Rectangle {
            anchors { top: parent.top; right: parent.right; margins: 16 }
            width: 34; height: 34; radius: 17
            color: closeArea.containsMouse ? Qt.rgba(1, 1, 1, 0.20) : Theme.fillHover
            border.color: Theme.line
            scale: closeArea.pressed ? 0.94 : 1
            Behavior on scale { NumberAnimation { duration: 120 * Theme.motion } }
            Text { anchors.centerIn: parent; text: "\u2715"; color: "#B3FFFFFF"; font.pixelSize: 14 }
            MouseArea { id: closeArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.close() }
        }
    }

    // ---- the box. Above the sheet so it can fly in from the grid; lined up face-to-face with the card it came from.
    // the films either side of the one in focus: real boxes, still (no spin), greyed, bobbing a beat behind
    Repeater {
        model: root.count > 2 ? [-1, 1] : root.count === 2 ? [1] : []
        DvdBox {
            readonly property int dir: modelData
            readonly property var s: root.slides[root.wrap(root.slide + dir)] || ({})
            width: box.width; height: box.height
            x: box.restX; y: box.restY
            front: s.cover || ""; back: s.back || ""; spine: s.spine || ""; disc: s.disc || ""
            title: s.title || ""; year: s.year || ""
            yaw: -dir * 30                       // turned in toward the box in focus
            spinning: false; hint: false; enabled: false
            dim: 0.5
            visible: root.visible && root.spread > 0.01
            opacity: Math.min(1, root.spread) * root.neighFade * (root.closing ? root.spread : 1)
            transform: [
                Scale { origin.x: box.width / 2; origin.y: box.faceCY; xScale: 0.5 + 0.12 * root.spread; yScale: xScale },
                // out of the set: sideways to its place, lifted a little on the way (an arc), then the wave
                Translate { x: dir * Math.min(stage.width * 0.34, stage.width / 2 - 72) * root.spread
                            y: -28 * Math.sin(Math.PI * Math.min(1, root.spread)) + root.spread * 5 * Math.sin(root.wave - dir * 1.1) }
            ]
        }
    }

    DvdBox {
        id: box
        // as big as the stage allows: from under the film label down to just above the box-art buttons
        height: Math.max(300, sheet.height - 150)
        width: Math.min(stage.width - 24, height * 0.92)
        front: root.cur.cover || ""
        back: root.cur.back || ""
        spine: root.cur.spine || ""
        disc: root.cur.disc || ""
        title: root.cur.title || ""
        year: root.cur.year || ""
        property real swipe: 0                 // carousel: sideways slide while turning to the next film
        readonly property real bob: root.spread * 5 * Math.sin(root.wave)   // idle wave, in step with the films beside it
        hint: root.f === 1 && !root.launching
        spinning: root.f === 1 && !root.closing && !root.launching && !root.turning
        enabled: root.f === 1 && !root.closing && !root.launching && !root.turning
        // resting place: centred in the left pane, above the box-art buttons
        readonly property real restX: sheet.x + (stage.width - width) / 2
        readonly property real restY: sheet.y + sheet.height - 80 - height     // its hint line sits just above the art buttons
        readonly property real restCx: restX + width / 2
        readonly property real restCy: restY + faceCY
        // start: the card's poster (or, without a card, a smaller box in the same place)
        readonly property real k: Math.max(0.05, root.from.height / faceH)
        readonly property real startCx: root.from.x + root.from.width / 2
        readonly property real startCy: root.from.y + root.from.height / 2
        x: restX
        y: restY
        opacity: root.fromCard ? 1 : root.f
        transform: [
            Scale { origin.x: box.width / 2; origin.y: box.faceCY; xScale: box.k + (1 - box.k) * root.f; yScale: xScale },
            Translate { x: (box.startCx - box.restCx) * (1 - root.f) + box.swipe; y: (box.startCy - box.restCy) * (1 - root.f) + box.bob }
        ]
    }

    // carousel arrows: above the box layer so the box's drag area never swallows the click
    Repeater {
        model: root.count > 1 ? [-1, 1] : []
        Rectangle {
            readonly property int dir: modelData
            z: 22
            width: 34; height: 34; radius: 17
            x: dir < 0 ? sheet.x + 12 : sheet.x + stage.width - width - 12
            y: box.restY + box.faceCY - height / 2
            opacity: root.sheetIn * (arrowArea.containsMouse ? 1 : 0.7)
            visible: root.visible && !root.launching
            color: arrowArea.containsMouse ? Qt.rgba(1, 1, 1, 0.16) : Qt.rgba(1, 1, 1, 0.06)
            border.color: Theme.line
            scale: arrowArea.pressed ? 0.92 : 1
            Behavior on scale { NumberAnimation { duration: 120 * Theme.motion } }
            Behavior on color { ColorAnimation { duration: 120 * Theme.motion } }
            Canvas {                                 // thin chevron
                anchors.centerIn: parent; width: 12; height: 14
                onPaint: { var c = getContext("2d"); c.reset(); c.strokeStyle = "#FFFFFF"; c.lineWidth = 1.8; c.lineCap = "round"; c.lineJoin = "round"
                    c.beginPath(); if (parent.dir < 0) { c.moveTo(8.5, 2); c.lineTo(3.5, 7); c.lineTo(8.5, 12) } else { c.moveTo(3.5, 2); c.lineTo(8.5, 7); c.lineTo(3.5, 12) } c.stroke() }
            }
            MouseArea { id: arrowArea; anchors.fill: parent; anchors.margins: -6; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.step(parent.dir) }
        }
    }

    // Play on another device (AirPlay / Chromecast): grows out of its button
    Popup {
        id: castMenu
        property var devices: []
        parent: castBtn
        y: -height - 8
        width: 280
        padding: 8
        transformOrigin: Item.Bottom
        enter: Transition { ParallelAnimation {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 160 * Theme.motion }
            NumberAnimation { property: "scale"; from: 0.6; to: 1; duration: 240 * Theme.motion; easing.type: Easing.OutBack; easing.overshoot: 1.1 } } }
        exit: Transition { ParallelAnimation {
            NumberAnimation { property: "opacity"; to: 0; duration: 140 * Theme.motion }
            NumberAnimation { property: "scale"; to: 0.6; duration: 160 * Theme.motion; easing.type: Easing.InCubic } } }
        background: Rectangle { radius: 14; color: Theme.panel; border.color: "#33FFFFFF" }
        contentItem: Column {
            spacing: 2
            Text { text: "PLAY ON"; color: Theme.faint; font.family: Theme.mono; font.pixelSize: 10; leftPadding: 8; bottomPadding: 4; topPadding: 2 }
            Repeater {
                model: castMenu.devices
                Rectangle {
                    width: 264; height: 40; radius: 8
                    color: devArea.containsMouse ? Qt.rgba(1, 1, 1, 0.12) : "transparent"
                    Column { anchors { left: parent.left; leftMargin: 10; verticalCenter: parent.verticalCenter }
                        Text { text: modelData.name; color: "#FFFFFF"; font.pixelSize: 13; font.weight: Font.DemiBold }
                        Text { text: modelData.kind; color: Theme.faint; font.pixelSize: 10 } }
                    MouseArea { id: devArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: { Backend.castKey(modelData.id, root.infoKey); castMenu.close() } }
                }
            }
            Text { visible: castMenu.devices.length === 0; width: 264; wrapMode: Text.Wrap; padding: 8; color: Theme.faint; font.pixelSize: 12
                text: Backend.castSupport().airplay || Backend.castSupport().chromecast ? "Looking for devices on your network\u2026" : "Install AirPlay and Chromecast support in Settings \u203A Streaming." }
        }
    }

    // Gallery viewer: one image at a time, as big as the window allows; arrows or the keyboard to page, Esc to close
    Item {
        id: lightbox
        property int index: 0
        readonly property var shots: root.info.gallery || []
        property real shown: 0
        function open(i) { index = i; shown = 1; forceActiveFocus() }
        function close() { shown = 0; root.forceActiveFocus() }
        anchors.fill: parent
        z: 44
        visible: shown > 0.001
        opacity: shown
        Behavior on shown { NumberAnimation { duration: 220 * Theme.motion; easing.type: Easing.OutCubic } }
        Keys.onEscapePressed: close()
        Keys.onLeftPressed: index = (index - 1 + shots.length) % Math.max(1, shots.length)
        Keys.onRightPressed: index = (index + 1) % Math.max(1, shots.length)
        Rectangle { anchors.fill: parent; color: "#F0000000" }
        MouseArea { anchors.fill: parent; onClicked: lightbox.close(); onWheel: (w) => w.accepted = true }
        Image {
            anchors { fill: parent; margins: 64 }
            source: lightbox.shots.length ? lightbox.shots[Math.min(lightbox.index, lightbox.shots.length - 1)].url : ""
            fillMode: Image.PreserveAspectFit; asynchronous: true; smooth: true
            scale: 0.96 + 0.04 * lightbox.shown
        }
        Text { anchors { bottom: parent.bottom; horizontalCenter: parent.horizontalCenter; bottomMargin: 24 }
            text: (lightbox.index + 1) + " / " + lightbox.shots.length + "   \u00B7   \u2190 \u2192 to page, Esc to close"
            color: Theme.faint; font.family: Theme.mono; font.pixelSize: 11 }
        Repeater {
            model: lightbox.shots.length > 1 ? [-1, 1] : []
            Rectangle {
                width: 44; height: 44; radius: 22; color: navArea.containsMouse ? Qt.rgba(1, 1, 1, 0.18) : Qt.rgba(1, 1, 1, 0.08)
                anchors.verticalCenter: parent.verticalCenter
                x: modelData < 0 ? 16 : lightbox.width - width - 16
                Text { anchors.centerIn: parent; text: modelData < 0 ? "\u2039" : "\u203A"; color: "#FFFFFF"; font.pixelSize: 24 }
                MouseArea { id: navArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                    onClicked: lightbox.index = (lightbox.index + modelData + lightbox.shots.length) % lightbox.shots.length }
            }
        }
    }

    // custom box art: the crop editor opens on the picture you picked
    ArtCropper { id: cropper; anchors.fill: parent }

    // Fix Scraped Data: search TMDB, AniList and OMDb by hand; picking a result re-pulls the title, details, genres, cover and disc
    Popup {
        id: matchMenu
        property var results: []
        property string phase: ""           // "", "searching", "applying", or an error message
        function begin() {
            results = []; phase = ""
            q.text = (root.info.title || "").replace(/\s*\(\d{4}\)$/, ""); yr.text = root.info.isShow ? "" : (root.info.year || "")
            open(); q.forceActiveFocus(); q.selectAll()
            search()
        }
        function search() { if (q.text.trim() === "") return; phase = "searching"; Backend.searchMatch(root.infoKey, q.text, yr.text) }
        parent: matchBtn
        x: matchBtn.width - width
        y: matchBtn.height + 8
        width: 460
        padding: 12
        modal: false
        focus: true
        transformOrigin: Item.TopRight
        enter: Transition { ParallelAnimation {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 160 * Theme.motion }
            NumberAnimation { property: "scale"; from: 0.6; to: 1; duration: 240 * Theme.motion; easing.type: Easing.OutBack; easing.overshoot: 1.1 } } }
        exit: Transition { ParallelAnimation {
            NumberAnimation { property: "opacity"; to: 0; duration: 140 * Theme.motion }
            NumberAnimation { property: "scale"; to: 0.6; duration: 160 * Theme.motion; easing.type: Easing.InCubic } } }
        background: Rectangle { radius: 14; color: Theme.graphite; border.color: "#33FFFFFF" }
        contentItem: ColumnLayout {
            spacing: 10
            Text { text: "FIX SCRAPED DATA"; color: Theme.faint; font.family: Theme.mono; font.pixelSize: 10 }
            RowLayout {
                Layout.fillWidth: true
                spacing: 6
                Field { id: q; Layout.fillWidth: true; placeholderText: "Title"; onAccepted: matchMenu.search() }
                Field { id: yr; Layout.preferredWidth: 72; placeholderText: "Year"; inputMethodHints: Qt.ImhDigitsOnly
                    validator: RegularExpressionValidator { regularExpression: /[0-9]{0,4}/ }
                    onAccepted: matchMenu.search() }
                GlassButton { small: true; label: "Search"; onClicked: matchMenu.search() }
            }
            Text {
                visible: matchMenu.phase !== "" || matchMenu.results.length === 0
                Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: 12
                text: matchMenu.phase === "searching" ? "Searching every database\u2026" : matchMenu.phase === "applying" ? "Updating title, details and artwork\u2026"
                      : matchMenu.phase !== "" ? matchMenu.phase : "No results. Try the original title, or leave the year empty."
            }
            ListView {
                id: matchList
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(contentHeight, 330)
                visible: matchMenu.results.length > 0 && matchMenu.phase !== "applying"
                clip: true
                spacing: 4
                model: matchMenu.results
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar {}
                delegate: Rectangle {
                    width: matchList.width - 6; height: 74; radius: 10
                    color: mArea.containsMouse ? Qt.rgba(1, 1, 1, 0.10) : "transparent"
                    Behavior on color { ColorAnimation { duration: 120 * Theme.motion } }
                    Rectangle {
                        id: mThumb
                        x: 6; anchors.verticalCenter: parent.verticalCenter
                        width: 42; height: 63; radius: 5; color: Theme.slate; clip: true
                        Image { anchors.fill: parent; source: modelData.thumb; fillMode: Image.PreserveAspectCrop; asynchronous: true }
                    }
                    Column {
                        anchors { left: mThumb.right; leftMargin: 12; right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter }
                        spacing: 3
                        Row {
                            width: parent.width
                            spacing: 8
                            Rectangle {     // where this result comes from
                                anchors.verticalCenter: parent.verticalCenter
                                width: srcText.implicitWidth + 10; height: 16; radius: 4; color: "transparent"
                                border.color: modelData.source === "anilist" ? Theme.blue : modelData.source === "omdb" ? Theme.amber : Theme.green
                                Text { id: srcText; anchors.centerIn: parent; font.family: Theme.mono; font.pixelSize: 9
                                    text: modelData.source === "anilist" ? "ANILIST" : modelData.source === "omdb" ? "IMDB" : "TMDB"
                                    color: parent.border.color }
                            }
                            Text { width: parent.width - x; elide: Text.ElideRight; color: Theme.text; font.pixelSize: 13; font.weight: Font.DemiBold
                                text: modelData.title + (modelData.year ? "  \u00B7  " + modelData.year : "") }
                        }
                        Text { width: parent.width; maximumLineCount: 2; wrapMode: Text.Wrap; elide: Text.ElideRight; color: Theme.faint; font.pixelSize: 11
                            text: modelData.overview || "No description." }
                    }
                    MouseArea { id: mArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: { matchMenu.phase = "applying"; Backend.applyMatch(root.infoKey, modelData.source, modelData.id) } }
                }
            }
        }
    }

    // box sets: the title is a dropdown of the set and its films; picking one turns the carousel to it
    Popup {
        id: titleMenu
        function begin(btn) { parent = btn; open() }
        focus: true
        x: -width + parent.width + 8
        y: parent ? parent.height + 8 : 0
        width: 320
        padding: 8
        transformOrigin: Item.TopRight
        enter: Transition { ParallelAnimation {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 160 * Theme.motion }
            NumberAnimation { property: "scale"; from: 0.6; to: 1; duration: 240 * Theme.motion; easing.type: Easing.OutBack; easing.overshoot: 1.1 } } }
        exit: Transition { ParallelAnimation {
            NumberAnimation { property: "opacity"; to: 0; duration: 140 * Theme.motion }
            NumberAnimation { property: "scale"; to: 0.6; duration: 160 * Theme.motion; easing.type: Easing.InCubic } } }
        background: Rectangle { radius: 14; color: Theme.graphite; border.color: "#33FFFFFF" }
        contentItem: Column {
            spacing: 2
            Repeater {
                model: root.slides
                Rectangle {
                    width: 304; height: 44; radius: 8
                    readonly property bool here: index === root.slide
                    color: tArea.containsMouse ? Qt.rgba(1, 1, 1, 0.12) : here ? Qt.rgba(1, 1, 1, 0.06) : "transparent"
                    Image { id: tThumb; x: 8; anchors.verticalCenter: parent.verticalCenter; width: 24; height: 36; source: modelData.cover
                        fillMode: Image.PreserveAspectCrop; sourceSize.width: 48; sourceSize.height: 72; asynchronous: true }
                    Column {
                        anchors { left: tThumb.right; leftMargin: 10; right: tCheck.left; rightMargin: 8; verticalCenter: parent.verticalCenter }
                        Text { width: parent.width; elide: Text.ElideRight; color: "#FFFFFF"; font.pixelSize: 13; font.weight: here ? Font.Bold : Font.Medium
                            text: modelData.title + (modelData.uuid && modelData.year ? "  \u00B7  " + modelData.year : "") }
                        Text { text: modelData.label; color: Theme.faint; font.pixelSize: 10 }
                    }
                    Text { id: tCheck; anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
                        text: here ? "\u2713" : ""; color: Theme.blue; font.pixelSize: 14; font.weight: Font.Bold }
                    MouseArea { id: tArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: { titleMenu.close(); root.step(index - root.slide) } }
                }
            }
            Rectangle { width: 304; height: 1; color: Theme.line }
            Rectangle {
                width: 304; height: 34; radius: 8
                color: rArea.containsMouse ? Qt.rgba(1, 1, 1, 0.12) : "transparent"
                Text { x: 12; anchors.verticalCenter: parent.verticalCenter; text: "Rename \u201C" + (root.info.title || "") + "\u201D\u2026"
                    width: 280; elide: Text.ElideRight; color: "#CCFFFFFF"; font.pixelSize: 12 }
                MouseArea { id: rArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                    onClicked: { titleMenu.close(); root.renaming = true; if (root.titleEditor) { root.titleEditor.forceActiveFocus(); root.titleEditor.selectAll() } } }
            }
        }
    }

    // add the film to a box set: an existing one, or a new one you name
    Popup {
        id: setMenu
        property var sets: []
        focus: true
        function begin(btn) {
            parent = btn
            var mine = root.info.boxSet && root.info.boxSet.key
            sets = Backend.boxSets().filter(function(b) { return b.key !== mine })
            newSet.text = ""
            open()
        }
        function pick(id, name) {
            Backend.addToSet(root.infoKey, id, name)
            close()
            root.afterSetChange()
        }
        y: -height - 8
        width: 300
        padding: 8
        transformOrigin: Item.Bottom
        enter: Transition { ParallelAnimation {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 160 * Theme.motion }
            NumberAnimation { property: "scale"; from: 0.6; to: 1; duration: 240 * Theme.motion; easing.type: Easing.OutBack; easing.overshoot: 1.1 } } }
        exit: Transition { ParallelAnimation {
            NumberAnimation { property: "opacity"; to: 0; duration: 140 * Theme.motion }
            NumberAnimation { property: "scale"; to: 0.6; duration: 160 * Theme.motion; easing.type: Easing.InCubic } } }
        background: Rectangle { radius: 14; color: Theme.graphite; border.color: "#33FFFFFF" }
        contentItem: Column {
            spacing: 2
            Text { text: "ADD TO BOX SET"; color: Theme.faint; font.family: Theme.mono; font.pixelSize: 10; leftPadding: 8; bottomPadding: 4; topPadding: 2 }
            ListView {
                width: 284
                height: Math.min(contentHeight, 240)
                clip: true
                model: setMenu.sets
                boundsBehavior: Flickable.StopAtBounds
                delegate: Rectangle {
                    width: 284; height: 38; radius: 8
                    color: sArea.containsMouse ? Qt.rgba(1, 1, 1, 0.12) : "transparent"
                    Text { anchors { left: parent.left; leftMargin: 10; right: setCount.left; rightMargin: 8; verticalCenter: parent.verticalCenter }
                        text: modelData.name; color: "#FFFFFF"; font.pixelSize: 13; elide: Text.ElideRight }
                    Text { id: setCount; anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter }
                        text: modelData.films + (modelData.films === 1 ? " film" : " films"); color: Theme.faint; font.pixelSize: 11 }
                    MouseArea { id: sArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: setMenu.pick(modelData.id, modelData.name) }
                }
            }
            Text { visible: setMenu.sets.length === 0; text: "No other box sets yet."; color: Theme.faint; font.pixelSize: 12; leftPadding: 8; topPadding: 4; bottomPadding: 4 }
            Rectangle { width: 284; height: 1; color: Theme.line }
            Row {
                spacing: 6
                topPadding: 6
                Field { id: newSet; width: 206; placeholderText: "New box set name"; onAccepted: if (text.trim() !== "") setMenu.pick(0, text) }
                GlassButton { small: true; label: "Create"; enabled: newSet.text.trim() !== ""; opacity: enabled ? 1 : 0.4; onClicked: setMenu.pick(0, newSet.text) }
            }
        }
    }

    Connections {
        target: Backend
        function onMatchResults(key, list) { if (key === root.infoKey) { matchMenu.results = list; matchMenu.phase = "" } }
        function onMatchFailed(key, why) { if (key === root.infoKey) matchMenu.phase = why }
        function onMatchApplied(key, newKey) { if (key === root.infoKey) { matchMenu.close(); root.refresh() } }
        function onDevicesFound(list) { castMenu.devices = list }
        function onArtPicked(key, face, url, path) { if (root.visible) cropper.open(key, face, url, path) }
        function onBoxArtChanged(key) { if ((key === root.infoKey || key === root.cur.key) && root.visible) root.refresh() }
    }
}
