// Tag Manager: tag many titles at once, look after every tag (rename, merge, delete, keep out of the All tab), and
// write rules: "if <field> <test> <value>, tag with <tag>". Opened from Settings > Library, or the Tags button.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Sheet {
    id: root
    maxWidth: 1180
    maxHeight: 860
    scrolls: false
    title: "Tag Manager"
    sub: "Tag many titles at once, tidy up your tags, and let rules tag new titles for you."
    property int tab: 0                       // 0 = tag titles, 1 = tags, 2 = rules
    property var titles: []
    property var picked: ({})                 // key -> true
    property int pickedCount: 0
    property var tags: []
    property var hiddenAll: []
    property var rulesInfo: ({ rules: [], fields: [], tests: [], folders: [] })
    property var rules: []
    property bool dirty: false

    function show(source, which) { tab = which || 0; reload(); open(source) }
    function reload() {
        titles = Backend.taggingTitles(search.text, tagFilter.value)
        tags = Backend.tagSummary()
        hiddenAll = Backend.hiddenFrom("all_tags")
        rulesInfo = Backend.tagRules()
        rules = JSON.parse(JSON.stringify(rulesInfo.rules))
        dirty = false
        prune()
    }
    function prune() {          // keep only picks that are still listed
        var keep = {}, n = 0
        for (var i = 0; i < titles.length; i++) if (picked[titles[i].key]) { keep[titles[i].key] = true; n++ }
        picked = keep; pickedCount = n
    }
    function toggle(key) { var p = Object.assign({}, picked); if (p[key]) delete p[key]; else p[key] = true; picked = p; pickedCount = Object.keys(p).length }
    function pickAll(on) { var p = {}; if (on) titles.forEach(function(t) { p[t.key] = true }); picked = p; pickedCount = on ? titles.length : 0 }
    function pickedKeys() { return Object.keys(picked) }
    function tagOptions() {
        return [{ value: "", label: "All titles" }].concat(tags.map(function(t) {
            return { value: t.name, label: (t.kind === "genre" ? "Genre: " : t.kind === "auto" ? "Auto: " : t.kind === "studio" ? "Studio: " : "") + t.label + "  (" + t.count + ")" } }))
    }
    function fieldKind(id) { var f = rulesInfo.fields.find(function(x) { return x.value === id }); return f ? f.kind : "text" }
    function testsFor(field) { var k = fieldKind(field); return rulesInfo.tests.filter(function(t) { return t.kinds.indexOf(k) >= 0 }) }
    function setRule(i, key, value) {
        var r = rules.slice(); r[i] = Object.assign({}, r[i]); r[i][key] = value
        if (key === "field" && !testsFor(value).some(function(t) { return t.value === r[i].test })) r[i].test = testsFor(value)[0].value
        rules = r; dirty = true
    }
    function addRule() { rules = rules.concat([{ field: "file", test: "contains", value: "", tag: "", on: true, folders: [] }]); dirty = true }
    function removeRule(i) { var r = rules.slice(); r.splice(i, 1); rules = r; dirty = true }
    function saveRules(apply) { rules = Backend.saveTagRules(rules); dirty = false; if (apply) Backend.applyTagRules() }

    Connections { target: Backend; function onLibraryChanged() { if (root.isOpen) { root.titles = Backend.taggingTitles(search.text, tagFilter.value); root.tags = Backend.tagSummary(); root.prune() } } }
    Timer { id: searchDelay; interval: 200; onTriggered: { root.titles = Backend.taggingTitles(search.text, tagFilter.value); root.prune() } }

    component Caption: Text { color: Theme.faint; font.family: Theme.mono; font.pixelSize: 10 }

    ColumnLayout {
        anchors.fill: parent
        spacing: 14

        // tabs
        Rectangle {
            id: tabsBar
            Layout.preferredWidth: 420; Layout.preferredHeight: 36; radius: 11; color: "#99000000"; border.color: Theme.line
            Rectangle { width: (parent.width - 6) / 3; height: parent.height - 6; y: 3; radius: 9; color: Theme.text
                x: 3 + width * root.tab
                Behavior on x { NumberAnimation { duration: 260 * Theme.motion; easing.type: Easing.OutCubic } } }
            Row {
                id: tabRow
                anchors { fill: parent; margins: 3 }
                Repeater {
                    model: ["Tag titles", "Tags", "Rules"]
                    Item {
                        width: tabRow.width / 3; height: tabRow.height
                        Text { anchors.centerIn: parent; text: modelData + (index === 2 && root.dirty ? " •" : ""); font.pixelSize: 12; font.weight: Font.Bold
                            color: root.tab === index ? Theme.black : Theme.muted }
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.tab = index }
                    }
                }
            }
        }

        // ---------------------------------------------------------------- 1. tag titles in bulk
        ColumnLayout {
            visible: root.tab === 0
            Layout.fillWidth: true; Layout.fillHeight: true
            spacing: 10
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                Field { id: search; Layout.fillWidth: true; placeholderText: "Find titles: words from the title, original title, tags, year, codec …"
                    onTextEdited: searchDelay.restart() }
                Dropdown { id: tagFilter; Layout.preferredWidth: 240; options: root.tagOptions(); value: ""
                    onChosen: (v) => { root.titles = Backend.taggingTitles(search.text, v); root.prune() } }
                GlassButton { small: true; label: root.pickedCount === root.titles.length && root.titles.length > 0 ? "Select none" : "Select all " + root.titles.length
                    onClicked: root.pickAll(!(root.pickedCount === root.titles.length && root.titles.length > 0)) }
            }
            Rectangle {
                Layout.fillWidth: true; Layout.fillHeight: true
                radius: 12; color: Theme.slate; border.color: Theme.line; clip: true
                ListView {
                    id: titleList
                    anchors { fill: parent; margins: 6 }
                    model: root.titles
                    spacing: 2
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar {}
                    SmoothWheel { view: titleList; step: 160 }
                    delegate: Rectangle {
                        readonly property bool on: root.picked[modelData.key] === true
                        width: titleList.width - 10; height: 52; radius: 9
                        color: on ? Qt.rgba(Qt.color(Theme.green).r, Qt.color(Theme.green).g, Qt.color(Theme.green).b, 0.14)
                                  : rowArea.containsMouse ? Theme.fillHover : "transparent"
                        Behavior on color { ColorAnimation { duration: 120 * Theme.motion } }
                        Rectangle {      // check box
                            x: 10; anchors.verticalCenter: parent.verticalCenter
                            width: 20; height: 20; radius: 6
                            color: parent.on ? Theme.green : "transparent"; border.color: parent.on ? Theme.green : Theme.lineStrong; border.width: 1.5
                            Text { anchors.centerIn: parent; visible: parent.parent.on; text: "✓"; color: Theme.onGreen; font.pixelSize: 13; font.weight: Font.Bold }
                        }
                        Rectangle {
                            id: thumb
                            x: 42; anchors.verticalCenter: parent.verticalCenter
                            width: 28; height: 42; radius: 4; color: Theme.fill; clip: true
                            Image { anchors.fill: parent; source: modelData.poster; fillMode: Image.PreserveAspectCrop; asynchronous: true; sourceSize: Qt.size(56, 84) }
                        }
                        Column {
                            anchors { left: thumb.right; leftMargin: 12; verticalCenter: parent.verticalCenter }
                            width: 300
                            Text { width: parent.width; text: modelData.title + (modelData.year ? "  ·  " + modelData.year : ""); color: Theme.text; font.pixelSize: 13; font.weight: Font.DemiBold; elide: Text.ElideRight }
                            Text { width: parent.width; visible: modelData.subtitle !== ""; text: modelData.subtitle; color: Theme.muted; font.pixelSize: 11; elide: Text.ElideRight }
                        }
                        Text {
                            anchors { left: parent.left; leftMargin: 400; right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
                            text: modelData.tags.join("  ·  "); color: Theme.faint; font.pixelSize: 11; elide: Text.ElideRight
                        }
                        MouseArea { id: rowArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                            onClicked: (m) => {
                                // Shift-click: everything from the last one picked down to this one
                                if ((m.modifiers & Qt.ShiftModifier) && root.lastPick >= 0) {
                                    var p = Object.assign({}, root.picked), a = Math.min(root.lastPick, index), b = Math.max(root.lastPick, index)
                                    for (var i = a; i <= b; i++) p[root.titles[i].key] = true
                                    root.picked = p; root.pickedCount = Object.keys(p).length
                                } else root.toggle(modelData.key)
                                root.lastPick = index
                            } }
                    }
                    Text { anchors.centerIn: parent; visible: root.titles.length === 0; text: "No titles match."; color: Theme.faint; font.pixelSize: 13 }
                }
            }
            // what to do with the picked titles
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                Text { text: root.pickedCount === 0 ? "Pick titles (Shift-click picks a run)" : root.pickedCount + " picked"; color: root.pickedCount ? Theme.text : Theme.faint
                    font.pixelSize: 13; font.weight: Font.DemiBold; Layout.preferredWidth: 220 }
                TagField { id: newTag; Layout.fillWidth: true; placeholderText: "Tag to add, e.g. Kids or Rewatch"; enabled: root.pickedCount > 0
                    onChosen: (name) => Backend.bulkTag(root.pickedKeys(), name, true) }
                GlassButton { label: "Add tag"; primary: true; enabled: root.pickedCount > 0 && newTag.text.trim() !== ""; opacity: enabled ? 1 : 0.4
                    onClicked: newTag.take(newTag.text.trim()) }
                Dropdown {
                    id: removeDrop
                    Layout.preferredWidth: 200
                    enabled: root.pickedCount > 0
                    opacity: enabled ? 1 : 0.4
                    prefix: "Remove: "
                    // your tags on the picked titles (computed ones change by rule, genres by Fix Scraped Data)
                    options: {
                        var seen = {}, out = [{ value: "", label: "choose a tag" }]
                        root.titles.forEach(function(t) { if (root.picked[t.key]) t.tags.forEach(function(g) { seen[g] = true }) })
                        root.tags.forEach(function(t) { if (t.kind === "user" && seen[t.label]) out.push({ value: t.name, label: t.label }) })
                        return out
                    }
                    value: ""
                    onChosen: (v) => { if (v !== "") Backend.bulkTag(root.pickedKeys(), v, false); value = "" }
                }
            }
        }

        // ---------------------------------------------------------------- 2. every tag
        ColumnLayout {
            visible: root.tab === 1
            Layout.fillWidth: true; Layout.fillHeight: true
            spacing: 10
            RowLayout {
                Layout.fillWidth: true
                Field { id: tagSearch; Layout.fillWidth: true; placeholderText: "Find a tag" }
                Text { text: "Rename onto an existing tag to merge them. Computed tags change through Rules."; color: Theme.faint; font.pixelSize: 11 }
            }
            Rectangle {
                Layout.fillWidth: true; Layout.fillHeight: true
                radius: 12; color: Theme.slate; border.color: Theme.line; clip: true
                ListView {
                    id: tagList
                    anchors { fill: parent; margins: 6 }
                    model: root.tags.filter(function(t) { return tagSearch.text === "" || t.label.toLowerCase().indexOf(tagSearch.text.toLowerCase()) >= 0 })
                    spacing: 2
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar {}
                    SmoothWheel { view: tagList; step: 160 }
                    delegate: Rectangle {
                        width: tagList.width - 10; height: 46; radius: 9
                        color: tagRowArea.containsMouse ? Theme.fillHover : "transparent"
                        readonly property bool hidden: root.hiddenAll.indexOf(modelData.name) >= 0
                        MouseArea { id: tagRowArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                        RowLayout {
                            anchors { fill: parent; leftMargin: 12; rightMargin: 8 }
                            spacing: 10
                            Rectangle { implicitWidth: kindText.implicitWidth + 12; implicitHeight: 20; radius: 6; color: "transparent"
                                border.color: modelData.kind === "user" ? Theme.green : modelData.kind === "genre" ? Theme.blue : modelData.kind === "studio" ? Theme.amber : Theme.lineStrong
                                Text { id: kindText; anchors.centerIn: parent; text: ({ user: "YOURS", genre: "GENRE", studio: "STUDIO" })[modelData.kind] || "AUTO"
                                    color: modelData.kind === "user" ? Theme.green : modelData.kind === "genre" ? Theme.blue : modelData.kind === "studio" ? Theme.amber : Theme.muted; font.family: Theme.mono; font.pixelSize: 9 } }
                            Field {
                                Layout.fillWidth: true
                                text: modelData.label
                                readOnly: modelData.kind === "auto" || modelData.kind === "studio"
                                topPadding: 4; bottomPadding: 4
                                onEditingFinished: if (text.trim() !== "" && text !== modelData.label) {
                                    Backend.renameTag(modelData.name, modelData.kind === "genre" ? "genre:" + text.trim() : text.trim()); root.tags = Backend.tagSummary() }
                            }
                            Text { text: modelData.count + (modelData.count === 1 ? " title" : " titles"); color: Theme.faint; font.family: Theme.mono; font.pixelSize: 11; Layout.preferredWidth: 80 }
                            Pill { Layout.preferredWidth: 128; label: parent.parent.hidden ? "Hidden from All" : "In All"; selected: parent.parent.hidden; accent: Theme.red
                                onClicked: { Backend.toggleHidden("all_tags", modelData.name); root.hiddenAll = Backend.hiddenFrom("all_tags") } }
                            GlassButton { small: true; label: "Show titles"; onClicked: { tagFilter.value = modelData.name; root.titles = Backend.taggingTitles("", modelData.name); search.text = ""; root.tab = 0 } }
                            GlassButton { small: true; label: "Delete"; enabled: modelData.kind !== "auto" && modelData.kind !== "studio"; opacity: enabled ? 1 : 0; glyphColor: Theme.red
                                onClicked: { Backend.deleteTag(modelData.name); root.tags = Backend.tagSummary() } }
                        }
                    }
                    Text { anchors.centerIn: parent; visible: root.tags.length === 0; text: "No tags yet."; color: Theme.faint; font.pixelSize: 13 }
                }
            }
        }

        // ---------------------------------------------------------------- 3. rules
        ColumnLayout {
            visible: root.tab === 2
            Layout.fillWidth: true; Layout.fillHeight: true
            spacing: 10
            Text { Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.faint; font.pixelSize: 12
                text: "Each rule tags every title it matches, now and as new files arrive. Rule tags are computed: change or delete the rule and its tags follow. Tags you add by hand are never touched." }
            Rectangle {
                Layout.fillWidth: true; Layout.fillHeight: true
                radius: 12; color: Theme.slate; border.color: Theme.line; clip: true
                ListView {
                    id: ruleList
                    anchors { fill: parent; margins: 8 }
                    model: root.rules
                    spacing: 6
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar {}
                    SmoothWheel { view: ruleList; step: 160 }
                    delegate: Rectangle {
                        width: ruleList.width - 10; height: 52; radius: 10
                        color: Theme.fill; border.color: Theme.line
                        opacity: modelData.on === false ? 0.55 : 1
                        // how many titles it matches right now, worked out a moment after an edit
                        property int matches: -1
                        Timer { id: count; interval: 350; running: true; onTriggered: parent.matches = Backend.previewTagRule(modelData) }
                        Component.onCompleted: count.restart()
                        RowLayout {
                            anchors { fill: parent; leftMargin: 10; rightMargin: 8 }
                            spacing: 8
                            Switch { checked: modelData.on !== false; onToggled: root.setRule(index, "on", checked)
                                indicator: Rectangle { implicitWidth: 34; implicitHeight: 20; radius: 10; color: parent.checked ? Theme.green : Theme.fillHover
                                    Rectangle { width: 16; height: 16; radius: 8; y: 2; x: parent.parent.checked ? 16 : 2; color: Theme.text
                                        Behavior on x { NumberAnimation { duration: 160 * Theme.motion } } } } }
                            Text { text: "If"; color: Theme.muted; font.pixelSize: 13 }
                            Dropdown { Layout.preferredWidth: 170; options: root.rulesInfo.fields; value: modelData.field; onChosen: (v) => root.setRule(index, "field", v) }
                            Dropdown { Layout.preferredWidth: 160; options: root.testsFor(modelData.field); value: modelData.test; onChosen: (v) => root.setRule(index, "test", v) }
                            Field { Layout.fillWidth: true; Layout.minimumWidth: 120; text: modelData.value; placeholderText: root.fieldKind(modelData.field) === "number" ? "a number" : "text"
                                onEditingFinished: if (text !== modelData.value) root.setRule(index, "value", text) }
                            Text { text: "tag"; color: Theme.muted; font.pixelSize: 13 }
                            Field { Layout.preferredWidth: 150; text: modelData.tag; placeholderText: "tag name"
                                onEditingFinished: if (text !== modelData.tag) root.setRule(index, "tag", text) }
                            Dropdown {
                                Layout.preferredWidth: 150
                                options: [{ value: "", label: "All folders" }].concat(root.rulesInfo.folders.map(function(f) { return { value: String(f.id), label: f.name } }))
                                value: (modelData.folders || []).length ? String(modelData.folders[0]) : ""
                                onChosen: (v) => root.setRule(index, "folders", v === "" ? [] : [parseInt(v)])
                            }
                            Text { text: parent.parent.matches < 0 ? "" : parent.parent.matches + " match" + (parent.parent.matches === 1 ? "" : "es")
                                color: Theme.faint; font.family: Theme.mono; font.pixelSize: 10; Layout.preferredWidth: 70 }
                            GlassButton { small: true; label: "✕"; implicitWidth: 30; tip: "Delete this rule"; onClicked: root.removeRule(index) }
                        }
                    }
                    Column {
                        anchors.centerIn: parent
                        visible: root.rules.length === 0
                        spacing: 6
                        Text { anchors.horizontalCenter: parent.horizontalCenter; text: "No rules yet"; color: Theme.text; font.pixelSize: 15; font.weight: Font.Bold }
                        Text { anchors.horizontalCenter: parent.horizontalCenter; text: "For example: if Folder path contains Kids, tag Kids. If Age rating is R, tag Grown-ups."; color: Theme.faint; font.pixelSize: 12 }
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                GlassButton { label: "Add rule"; glyph: "+"; onClicked: root.addRule() }
                Item { Layout.fillWidth: true }
                Text { visible: root.dirty; text: "Unsaved changes"; color: Theme.amber; font.pixelSize: 12 }
                GlassButton { label: "Save"; enabled: root.dirty; opacity: enabled ? 1 : 0.4; onClicked: root.saveRules(false) }
                GlassButton { label: "Save and tag the library"; primary: true; onClicked: root.saveRules(true) }
            }
        }
    }
    property int lastPick: -1
}
