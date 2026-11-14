// Fix Scraped Data: a window of its own over View More.
//   1. Search: every source at once (TMDB, AniList, IMDb via OMDb), or paste a TMDB / AniList / MyAnimeList / IMDb
//      link. Pick one result or several (picks stay while you search again for another source).
//   2. Choose: each picked result's details side by side, field by field: which title, synopsis, poster, banner,
//      Gallery images (several sources can be combined), genres, score, age rating, cast... or keep what you have.
//   3. Apply: only what you chose is written. Your own box art, Gallery images, tags and notes are never touched.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Effects

Item {
    id: root
    visible: shown > 0.001
    z: 40
    property real shown: 0
    Behavior on shown { NumberAnimation { duration: 220 * Theme.motion; easing.type: Easing.OutCubic } }

    property string key: ""
    property bool isShow: false
    property var current: ({})                 // what the title has now (the "Keep yours" choice)
    property string step: "search"             // search -> choose (-> applying)
    property string phase: ""                  // "", "searching", "loading", "applying", or an error
    property var results: []
    property var picks: []                     // [{pid, source, id, title, year, thumb, overview}] in the order picked
    property var details: []                   // step 2: [{pid, source, title, year, fields}]
    property var choices: ({})                 // field -> pid ("" = keep yours); gallery -> [pid]
    property string primary: ""
    property var uploads: ({})                 // field -> [{pid: "file:<path>", source: "file", fields}] from "Upload file"
    readonly property var uploadable: ["poster", "banner", "disc", "gallery"]

    readonly property var fields: [
        ["title", "Title", "text"], ["year", "Year", "text"], ["synopsis", "Synopsis", "long"],
        ["poster", "Poster", "poster"], ["banner", "Banner", "banner"], ["disc", "Disc art", "disc"], ["gallery", "Gallery images", "gallery"],
        ["genres", "Genres", "text"], ["score", "Score", "text"], ["rating", "Age rating", "text"],
        ["titles", "Other titles", "text"], ["cast", "Cast", "text"], ["boxset", "Box set", "text"]]

    function open(itemKey, title, year, show, now) {
        key = itemKey; isShow = show; current = now || ({})
        step = "search"; phase = ""; results = []; picks = []; details = []; choices = ({}); primary = ""; uploads = ({})
        q.text = (title || "").replace(/\s*\(\d{4}\)$/, ""); yr.text = show ? "" : (year || "")
        shown = 1
        q.forceActiveFocus(); q.selectAll()
        search()
    }
    function close() { shown = 0; parent.forceActiveFocus() }
    function search() { if (q.text.trim() === "") return; phase = "searching"; Backend.searchMatch(key, q.text, yr.text) }
    function pid(r) { return r.source + "|" + r.id }
    function picked(r) { var p = pid(r); return picks.some(function(x) { return x.pid === p }) }
    function toggle(r) {
        var p = pid(r)
        if (picked(r)) picks = picks.filter(function(x) { return x.pid !== p })
        else if (picks.length < 6) picks = picks.concat([{ pid: p, source: r.source, id: r.id, title: r.title, year: r.year, thumb: r.thumb }])
    }
    function next() {
        if (picks.length === 0) return
        step = "choose"; phase = "loading"; details = []
        Backend.matchDetails(key, picks.map(function(x) { return { source: x.source, id: x.id, title: x.title } }))
    }
    function has(d, f) { var v = d.fields[f]; return f === "gallery" ? d.fields.galleryCount > 0 : (v !== undefined && v !== "") }
    function defaults() {     // each field from the first picked result that has it; the Gallery from the first with images
        var c = {}
        fields.forEach(function(f) {
            if (f[0] === "gallery") {
                var g = details.filter(function(d) { return root.has(d, "gallery") })
                c.gallery = g.length ? [g[0].pid] : []
            } else {
                var d = details.find(function(d) { return root.has(d, f[0]) })
                c[f[0]] = d ? d.pid : ""
            }
        })
        choices = c
        var linkable = details.filter(function(d) { return d.source !== "fanart" })
        primary = linkable.length ? linkable[0].pid : ""
    }
    // "Upload file": your own picture for a field; it is chosen at once (added to the Gallery's choices)
    function addUploads(f, files) {
        var u = Object.assign({}, uploads), list = (u[f] || []).slice()
        files.forEach(function(x) {
            var fields = {}; fields[f] = x.url
            if (f === "gallery") { fields.gallery = [x.url]; fields.galleryCount = 1 }
            var tile = { pid: x.choice, source: "file", fields: fields }
            if (f === "gallery") list.push(tile); else list = [tile]
            if (f === "gallery") { if (!chosen(f, x.choice)) choose(f, x.choice) } else choose(f, x.choice)
        })
        u[f] = list
        uploads = u
    }
    function choose(f, p) {
        var c = Object.assign({}, choices)
        if (f === "gallery") {
            var g = (c.gallery || []).slice(), i = g.indexOf(p)
            if (p === "") g = []
            else if (i >= 0) g.splice(i, 1); else g.push(p)
            c.gallery = g
        } else c[f] = p
        choices = c
    }
    function chosen(f, p) { return f === "gallery" ? (p === "" ? (choices.gallery || []).length === 0 : (choices.gallery || []).indexOf(p) >= 0) : choices[f] === p }
    function apply() { phase = "applying"; Backend.applyMatchParts(key, choices, primary) }
    function srcName(s) { return ({ anilist: "AniList", omdb: "IMDb", tvmaze: "TVmaze", mal: "MyAnimeList", kitsu: "Kitsu",
                                     fanart: "fanart.tv", file: "Your file" })[s] || "TMDB" }
    function srcColor(s) { return ({ anilist: Theme.blue, omdb: Theme.amber, tvmaze: "#64D2FF", mal: "#7D9BFF", kitsu: "#FF7A66",
                                     fanart: "#BF5AF2", file: Theme.text })[s] || Theme.green }

    Connections {
        target: Backend
        function onMatchResults(k, list) { if (k === root.key && root.step === "search") { root.results = list; root.phase = "" } }
        function onMatchFailed(k, why) { if (k === root.key) root.phase = why }
        function onMatchDetailsReady(k, list) { if (k === root.key) { root.details = list; root.phase = ""; root.defaults() } }
        function onMatchApplied(k, newKey) { if (k === root.key) { root.phase = ""; root.close() } }
        function onMatchFilesPicked(k, f, files) { if (k === root.key) root.addUploads(f, files) }
    }

    Keys.onEscapePressed: close()

    // dim, and eat every click and scroll meant for View More underneath
    Rectangle { anchors.fill: parent; color: Theme.scrim; opacity: root.shown }
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onWheel: (w) => w.accepted = true; onClicked: root.close() }

    component Chip: Rectangle {
        property string source: ""
        width: chipText.implicitWidth + 10; height: 16; radius: 4; color: "transparent"; border.color: root.srcColor(source)
        Text { id: chipText; anchors.centerIn: parent; text: root.srcName(source).toUpperCase(); color: parent.border.color
            font.family: Theme.mono; font.pixelSize: 9; font.weight: Font.Bold }
    }

    Rectangle {
        id: panel
        anchors.centerIn: parent
        width: Math.min(parent.width - 64, 1180)
        height: Math.min(parent.height - 64, 860)
        radius: 16
        color: Theme.panel
        border.color: Theme.lineStrong
        clip: true
        opacity: root.shown
        scale: 0.96 + 0.04 * root.shown
        MouseArea { anchors.fill: parent; onWheel: (w) => w.accepted = false }    // clicks inside stay inside

        // ---- header
        Item {
            id: head
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: 76
            Column {
                anchors { left: parent.left; leftMargin: 28; verticalCenter: parent.verticalCenter }
                spacing: 3
                Text { text: "Fix Scraped Data"; color: Theme.text; font.pixelSize: 20; font.weight: Font.ExtraBold }
                Text { text: root.current.title || ""; color: Theme.faint; font.pixelSize: 12; elide: Text.ElideRight; width: 520 }
            }
            Row {       // where you are: 1 Search, 2 Choose
                anchors.centerIn: parent
                spacing: 10
                Repeater {
                    model: [["search", "1  Search"], ["choose", "2  Choose data"]]
                    Rectangle {
                        readonly property bool on: root.step === modelData[0]
                        width: stepText.implicitWidth + 24; height: 28; radius: 14
                        color: on ? Theme.text : Qt.rgba(1, 1, 1, 0.06)
                        Behavior on color { ColorAnimation { duration: 180 * Theme.motion } }
                        Text { id: stepText; anchors.centerIn: parent; text: modelData[1]; font.pixelSize: 12; font.weight: Font.Bold
                            color: parent.on ? Theme.black : Theme.muted }
                    }
                }
            }
            Rectangle {
                anchors { right: parent.right; rightMargin: 20; verticalCenter: parent.verticalCenter }
                width: 34; height: 34; radius: 17; color: xArea.containsMouse ? Qt.rgba(1, 1, 1, 0.2) : Theme.fillHover; border.color: Theme.line
                Text { anchors.centerIn: parent; text: "\u2715"; color: "#B3FFFFFF"; font.pixelSize: 14 }
                MouseArea { id: xArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.close() }
            }
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }
        }

        // ---- step 1: search every source, pick one or more
        Item {
            id: searchStep
            anchors { left: parent.left; right: parent.right; top: head.bottom; bottom: foot.top }
            visible: opacity > 0.01
            opacity: root.step === "search" ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 200 * Theme.motion } }
            transform: Translate { x: root.step === "search" ? 0 : -28
                Behavior on x { NumberAnimation { duration: 260 * Theme.motion; easing.type: Easing.OutCubic } } }

            RowLayout {
                id: bar
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: 24 }
                spacing: 8
                Field { id: q; Layout.fillWidth: true; placeholderText: "Title, or paste a TMDB / AniList / MyAnimeList / IMDb link"; onAccepted: root.search() }
                Field { id: yr; Layout.preferredWidth: 84; placeholderText: "Year"; inputMethodHints: Qt.ImhDigitsOnly
                    validator: RegularExpressionValidator { regularExpression: /[0-9]{0,4}/ }
                    onAccepted: root.search() }
                GlassButton { small: true; primary: true; label: "Search"; onClicked: root.search() }
            }
            Text {
                id: status
                anchors { left: parent.left; right: parent.right; top: bar.bottom; margins: 24; topMargin: 12 }
                wrapMode: Text.Wrap; color: root.phase !== "" && root.phase !== "searching" ? Theme.amber : Theme.faint; font.pixelSize: 12
                text: root.phase === "searching" ? "Searching TMDB, TVmaze, IMDb, AniList, MyAnimeList and Kitsu\u2026"
                      : root.phase !== "" ? root.phase
                      : root.results.length === 0 ? "No results. Try the original title, or leave the year empty."
                      : "Pick one result, or several from different sites to mix their details. Search again to add more; picks stay."
            }
            GridView {
                id: resultGrid
                anchors { left: parent.left; right: parent.right; top: status.bottom; bottom: parent.bottom; leftMargin: 18; rightMargin: 18; topMargin: 12 }
                clip: true
                cellWidth: Math.floor(width / Math.max(1, Math.floor(width / 186)))
                cellHeight: 318
                model: root.results
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar {}
                SmoothWheel { view: resultGrid; step: 160 }
                delegate: Item {
                    width: resultGrid.cellWidth; height: resultGrid.cellHeight
                    readonly property bool on: root.picked(modelData)
                    Rectangle {
                        id: card
                        anchors { fill: parent; margins: 6 }
                        radius: 12
                        color: cardArea.containsMouse ? Theme.fillHover : Qt.rgba(1, 1, 1, 0.03)
                        border.color: parent.on ? Theme.blue : Theme.line
                        border.width: parent.on ? 2 : 1
                        scale: cardArea.pressed ? 0.97 : 1
                        Behavior on scale { NumberAnimation { duration: 140 * Theme.motion; easing.type: Easing.OutCubic } }
                        Behavior on border.color { ColorAnimation { duration: 140 * Theme.motion } }
                        Rectangle {
                            id: thumb
                            x: 10; y: 10; width: parent.width - 20; height: width * 1.5 > 190 ? 190 : width * 1.5
                            radius: 8; color: Theme.slate; clip: true
                            Image { anchors.fill: parent; source: modelData.thumb || ""; fillMode: Image.PreserveAspectCrop; asynchronous: true
                                sourceSize.width: 240 }
                        }
                        Rectangle {      // picked
                            anchors { top: thumb.top; right: thumb.right; margins: 6 }
                            width: 24; height: 24; radius: 12
                            color: parent.parent.on ? Theme.blue : "#99000000"; border.color: "#66FFFFFF"
                            scale: parent.parent.on ? 1 : 0.85
                            Behavior on scale { NumberAnimation { duration: 180 * Theme.motion; easing.type: Easing.OutBack } }
                            Text { anchors.centerIn: parent; text: "\u2713"; color: "#FFFFFF"; font.pixelSize: 13; font.weight: Font.Bold; visible: parent.parent.parent.on }
                        }
                        Column {
                            anchors { left: parent.left; right: parent.right; top: thumb.bottom; margins: 10 }
                            spacing: 4
                            Row { spacing: 6; Chip { source: modelData.source }
                                Text { text: modelData.year || ""; color: Theme.faint; font.family: Theme.mono; font.pixelSize: 10 } }
                            Text { width: parent.width; text: modelData.title; color: Theme.text; font.pixelSize: 13; font.weight: Font.DemiBold
                                wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight }
                            Text { width: parent.width; text: modelData.overview || ""; color: Theme.faint; font.pixelSize: 11
                                wrapMode: Text.Wrap; maximumLineCount: 3; elide: Text.ElideRight }
                        }
                        MouseArea { id: cardArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.toggle(modelData) }
                    }
                }
            }
        }

        // ---- step 2: field by field, from which result
        Item {
            id: chooseStep
            anchors { left: parent.left; right: parent.right; top: head.bottom; bottom: foot.top }
            visible: opacity > 0.01
            opacity: root.step === "choose" ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 200 * Theme.motion } }
            transform: Translate { x: root.step === "choose" ? 0 : 28
                Behavior on x { NumberAnimation { duration: 260 * Theme.motion; easing.type: Easing.OutCubic } } }

            Text {
                anchors.centerIn: parent
                visible: root.phase === "loading" || (root.phase !== "" && root.phase !== "applying" && root.details.length === 0)
                text: root.phase === "loading" ? "Getting the details of " + root.picks.length + (root.picks.length === 1 ? " result\u2026" : " results\u2026") : root.phase
                color: root.phase === "loading" ? Theme.faint : Theme.amber; font.pixelSize: 13
            }

            Flickable {
                id: chooseFlick
                anchors { fill: parent; margins: 0 }
                visible: root.details.length > 0
                contentHeight: chooseCol.implicitHeight + 40
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar {}
                SmoothWheel { view: chooseFlick; step: 160 }
                ColumnLayout {
                    id: chooseCol
                    x: 28; y: 20
                    width: chooseFlick.width - 56
                    spacing: 18

                    // which result the title is linked to (its ids: later lookups ask about this one)
                    RowLayout {
                        visible: root.details.length > 1
                        spacing: 10
                        Text { Layout.preferredWidth: 130; text: "LINKED TO"; color: Theme.faint; font.family: Theme.mono; font.pixelSize: 11 }
                        Flow {
                            Layout.fillWidth: true; spacing: 6
                            Repeater {
                                model: root.details.filter(function(d) { return d.source !== "fanart" })    // art only: not a title
                                Pill { label: root.srcName(modelData.source) + " \u00B7 " + modelData.title; selected: root.primary === modelData.pid
                                    accent: root.srcColor(modelData.source); onClicked: root.primary = modelData.pid }
                            }
                        }
                    }

                    Repeater {
                        model: root.fields
                        RowLayout {
                            id: fieldRow
                            readonly property string f: modelData[0]
                            readonly property string kind: modelData[2]
                            readonly property var offers: root.details.filter(function(d) { return root.has(d, fieldRow.f) })
                                                          .concat(root.uploads[fieldRow.f] || [])
                            readonly property bool canUpload: root.uploadable.indexOf(fieldRow.f) >= 0
                            visible: offers.length > 0 || canUpload
                            Layout.fillWidth: true
                            spacing: 10
                            Text { Layout.preferredWidth: 130; Layout.alignment: Qt.AlignTop; topPadding: 8
                                text: modelData[1].toUpperCase(); color: Theme.faint; font.family: Theme.mono; font.pixelSize: 11
                                wrapMode: Text.Wrap }
                            ListView {
                                id: offerList
                                Layout.fillWidth: true
                                Layout.preferredHeight: fieldRow.kind === "poster" ? 214 : fieldRow.kind === "banner" ? 170 : fieldRow.kind === "disc" ? 176
                                                      : fieldRow.kind === "gallery" ? 176 : fieldRow.kind === "long" ? 150 : 74
                                orientation: ListView.Horizontal
                                spacing: 10
                                clip: true
                                boundsBehavior: Flickable.StopAtBounds
                                // "keep yours" first, then each result that has this field, your files, and "Upload file"
                                model: [{ pid: "", source: "", fields: root.current }].concat(fieldRow.offers)
                                       .concat(fieldRow.canUpload ? [{ pid: "__upload", source: "", fields: {} }] : [])
                                ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }
                                delegate: Rectangle {
                                    id: tile
                                    readonly property bool add: modelData.pid === "__upload"
                                    readonly property bool mine: modelData.pid === ""
                                    readonly property bool on: root.chosen(fieldRow.f, modelData.pid)
                                    readonly property var v: modelData.fields || ({})
                                    width: add ? 132 : fieldRow.kind === "poster" ? 132 : fieldRow.kind === "banner" ? 262 : fieldRow.kind === "gallery" ? 262
                                         : fieldRow.kind === "disc" ? 150 : fieldRow.kind === "long" ? 340 : 230
                                    height: offerList.height - 8
                                    radius: 10
                                    color: tileArea.containsMouse ? Theme.fillHover : Qt.rgba(1, 1, 1, 0.03)
                                    border.color: on ? Theme.blue : add && tileArea.containsMouse ? "#66FFFFFF" : Theme.line
                                    border.width: on && !add ? 2 : 1
                                    Behavior on border.color { ColorAnimation { duration: 140 * Theme.motion } }
                                    scale: tileArea.pressed ? 0.97 : 1
                                    Behavior on scale { NumberAnimation { duration: 140 * Theme.motion; easing.type: Easing.OutCubic } }
                                    // "Upload file": a tile that opens a file chooser
                                    Column {
                                        visible: tile.add
                                        anchors.centerIn: parent
                                        spacing: 6
                                        Text { anchors.horizontalCenter: parent.horizontalCenter; text: "+"; color: Theme.muted; font.pixelSize: 26; font.weight: Font.Light }
                                        Text { anchors.horizontalCenter: parent.horizontalCenter; text: fieldRow.f === "gallery" ? "Upload files\u2026" : "Upload file\u2026"
                                            color: Theme.muted; font.pixelSize: 12; font.weight: Font.DemiBold }
                                    }
                                    Row {
                                        id: tileHead
                                        visible: !tile.add
                                        x: 10; y: 8; spacing: 6
                                        Chip { visible: !tile.mine; source: modelData.source || "tmdb" }
                                        Text { visible: tile.mine; text: fieldRow.f === "gallery" ? "KEEP THE CURRENT IMAGES" : "KEEP YOURS"
                                            color: Theme.muted; font.family: Theme.mono; font.pixelSize: 9; font.weight: Font.Bold }
                                    }
                                    Rectangle {      // chosen
                                        visible: !tile.add
                                        anchors { top: parent.top; right: parent.right; margins: 7 }
                                        width: 18; height: 18; radius: fieldRow.f === "gallery" ? 5 : 9
                                        color: tile.on ? Theme.blue : "transparent"; border.color: tile.on ? Theme.blue : "#4DFFFFFF"
                                        Text { anchors.centerIn: parent; text: "\u2713"; color: "#FFFFFF"; font.pixelSize: 11; visible: tile.on }
                                    }
                                    Item {
                                        visible: !tile.add
                                        anchors { left: parent.left; right: parent.right; top: tileHead.bottom; bottom: parent.bottom; margins: 10; topMargin: 6 }
                                        // disc art: round, like the disc in the box
                                        Item {
                                            visible: fieldRow.kind === "disc"
                                            anchors.centerIn: parent
                                            width: Math.min(parent.width, parent.height); height: width
                                            Image { id: discImg; anchors.fill: parent; fillMode: Image.PreserveAspectCrop; asynchronous: true; visible: false
                                                source: parent.visible ? (tile.v.disc || "") : ""; sourceSize.width: 300 }
                                            Rectangle { id: discMask; anchors.fill: parent; radius: width / 2; visible: false; layer.enabled: true }
                                            Rectangle { anchors.fill: parent; radius: width / 2; color: Theme.slate }
                                            MultiEffect { anchors.fill: parent; source: discImg; maskEnabled: true; maskSource: discMask; visible: !!tile.v.disc }
                                            Text { anchors.centerIn: parent; visible: !tile.v.disc; text: "None"; color: Theme.faint; font.pixelSize: 11 }
                                        }
                                        // text
                                        Text {
                                            visible: fieldRow.kind === "text" || fieldRow.kind === "long"
                                            anchors.fill: parent
                                            text: (tile.v[fieldRow.f] || (tile.mine ? "(none)" : "")) + ""
                                            color: tile.mine && !tile.v[fieldRow.f] ? Theme.faint : Theme.text
                                            font.pixelSize: fieldRow.f === "title" ? 14 : 12
                                            font.weight: fieldRow.f === "title" ? Font.DemiBold : Font.Normal
                                            wrapMode: Text.Wrap; elide: Text.ElideRight
                                            maximumLineCount: fieldRow.kind === "long" ? 6 : 2
                                        }
                                        // poster / banner
                                        Rectangle {
                                            visible: fieldRow.kind === "poster" || fieldRow.kind === "banner"
                                            anchors.fill: parent; radius: 6; color: Theme.slate; clip: true
                                            Image { anchors.fill: parent; fillMode: Image.PreserveAspectCrop; asynchronous: true
                                                source: parent.visible ? (tile.v[fieldRow.f] || "") : ""; sourceSize.width: 520 }
                                            Text { anchors.centerIn: parent; visible: !tile.v[fieldRow.f]; text: "None"; color: Theme.faint; font.pixelSize: 11 }
                                        }
                                        // gallery: the first images and how many
                                        Item {
                                            visible: fieldRow.kind === "gallery"
                                            anchors.fill: parent
                                            Grid {
                                                columns: 3; spacing: 4
                                                Repeater {
                                                    model: parent.parent.visible ? (tile.v.gallery || []).slice(0, 6) : []
                                                    Rectangle { width: 76; height: 43; radius: 4; color: Theme.slate; clip: true
                                                        Image { anchors.fill: parent; source: modelData; fillMode: Image.PreserveAspectCrop; asynchronous: true; sourceSize.width: 160 } }
                                                }
                                            }
                                            Text { anchors { left: parent.left; bottom: parent.bottom }
                                                text: tile.mine ? (tile.v.galleryCount ? tile.v.galleryCount + " now (yours are always kept)" : "Your own images are always kept")
                                                                : tile.v.galleryCount + (tile.v.galleryCount === 1 ? " image" : " images")
                                                color: Theme.faint; font.pixelSize: 11 }
                                        }
                                    }
                                    MouseArea { id: tileArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                        onClicked: tile.add ? Backend.pickMatchFiles(root.key, fieldRow.f) : root.choose(fieldRow.f, modelData.pid) }
                                }
                            }
                        }
                    }
                }
            }
        }

        // ---- footer: what is picked, and the way on
        Item {
            id: foot
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
            height: 72
            Rectangle { width: parent.width; height: 1; color: Theme.line }
            Row {       // step 1: the picks so far, as small chips (click one to drop it)
                visible: root.step === "search"
                anchors { left: parent.left; leftMargin: 24; verticalCenter: parent.verticalCenter }
                spacing: 6
                Text { anchors.verticalCenter: parent.verticalCenter; text: root.picks.length === 0 ? "Nothing picked yet" : root.picks.length + " picked:"
                    color: Theme.faint; font.pixelSize: 12 }
                Repeater {
                    model: root.picks
                    Pill { label: root.srcName(modelData.source) + " \u00B7 " + modelData.title + "   \u00D7"; accent: root.srcColor(modelData.source)
                        onClicked: root.toggle(modelData) }
                }
            }
            Text {
                visible: root.step === "choose"
                anchors { left: parent.left; leftMargin: 24; verticalCenter: parent.verticalCenter }
                text: root.phase === "applying" ? "Applying\u2026" : "Only the fields you choose change. A file you upload becomes your own art; tags and notes always stay."
                color: Theme.faint; font.pixelSize: 12
            }
            Row {
                anchors { right: parent.right; rightMargin: 24; verticalCenter: parent.verticalCenter }
                spacing: 8
                GlassButton { small: true; label: root.step === "search" ? "Cancel" : "Back"
                    onClicked: if (root.step === "search") root.close(); else { root.step = "search"; root.phase = "" } }
                GlassButton { small: true; primary: true; visible: root.step === "search"; enabled: root.picks.length > 0
                    label: "Next"; onClicked: root.next() }
                GlassButton { small: true; primary: true; visible: root.step === "choose"
                    enabled: root.details.length > 0 && root.phase !== "applying"
                    label: root.phase === "applying" ? "Applying\u2026" : "Apply"; onClicked: root.apply() }
            }
        }
    }
}
