// A tag box that suggests the library's tags as you type: yours, then genres, studios and automatic ones, most used
// first; ones starting with what you typed lead. Up / Down pick a suggestion, Enter or Tab takes it, Esc closes the list. `exclude`: tags the title
// already has. Emits `chosen(name)`; Enter with no suggestion picked adds exactly what was typed.
import QtQuick
import QtQuick.Controls

Field {
    id: root
    property var exclude: []
    property var known: []                       // [{name, label, kind}], filled when the box gets focus
    property int pick: -1
    signal chosen(string name)

    readonly property var matches: {
        var q = text.trim().toLowerCase()
        if (q === "") return []
        var ex = exclude.map(function(t) { return String(t).toLowerCase().replace(/^auto:/, "") })     // "auto:Rated R" = "Rated R"
        var starts = [], has = []
        for (var i = 0; i < known.length; i++) {
            var t = known[i], l = t.label.toLowerCase()
            if (ex.indexOf(t.name.toLowerCase()) >= 0 || ex.indexOf(l) >= 0) continue      // the title has it already
            if (l.indexOf(q) === 0) starts.push(t); else if (l.indexOf(q) > 0) has.push(t)
        }
        return starts.concat(has).slice(0, 8)
    }
    onMatchesChanged: pick = -1
    onActiveFocusChanged: if (activeFocus) known = Backend.tagNames()

    function take(name) { chosen(name); text = ""; pick = -1 }
    onAccepted: { var t = pick >= 0 ? matches[pick].name : text.trim(); if (t !== "") take(t) }
    Keys.onDownPressed: if (matches.length) pick = (pick + 1) % matches.length
    Keys.onUpPressed: if (matches.length) pick = pick <= 0 ? matches.length - 1 : pick - 1
    Keys.onTabPressed: (e) => { if (matches.length) { take(matches[Math.max(0, pick)].name); e.accepted = true } else e.accepted = false }
    Keys.onEscapePressed: (e) => { if (matches.length) { text = ""; e.accepted = true } else e.accepted = false }

    Popup {
        id: list
        y: root.height + 4
        width: root.width
        padding: 4
        visible: root.activeFocus && root.matches.length > 0
        closePolicy: Popup.NoAutoClose
        background: Rectangle { radius: 10; color: Theme.graphite; border.color: Theme.edge }
        contentItem: Column {
            spacing: 1
            Repeater {
                model: root.matches
                Rectangle {
                    width: list.availableWidth; height: 30; radius: 7
                    color: index === root.pick || rowArea.containsMouse ? Theme.fillHover : "transparent"
                    Text {
                        anchors { left: parent.left; leftMargin: 10; verticalCenter: parent.verticalCenter }
                        // what you typed in bold, inside the suggestion
                        textFormat: Text.StyledText
                        text: {
                            var q = root.text.trim(), t = modelData.label, i = t.toLowerCase().indexOf(q.toLowerCase())
                            function esc(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;") }
                            return i < 0 ? esc(t) : esc(t.substring(0, i)) + "<b>" + esc(t.substring(i, i + q.length)) + "</b>" + esc(t.substring(i + q.length))
                        }
                        color: Theme.text; font.pixelSize: 12
                    }
                    Text { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter }
                        text: (modelData.kind ? modelData.kind.toUpperCase() : "") + (index === root.pick ? "  ↵" : "")
                        color: Theme.faint; font.family: Theme.mono; font.pixelSize: 10 }
                    MouseArea { id: rowArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: root.take(modelData.name) }
                }
            }
        }
    }
}
