// What a folder scrapes: a chip per part (titles, synopsis, genres, box art, disc art, box sets, actors, photos).
// Tap to turn one on or off. Actor photos need Actors. `selected` is the list of part ids that are on.
import QtQuick

Flow {
    id: root
    property var selected: []
    property var parts: Backend.scrapeParts()
    signal edited(string csv)
    spacing: 6

    function has(id) { return selected.indexOf(id) >= 0 }
    function flip(id) {
        var next = selected.slice()
        var i = next.indexOf(id)
        if (i >= 0) next.splice(i, 1); else next.push(id)
        if (id === "cast" && i >= 0) next = next.filter(function(p) { return p !== "photos" })   // no actors, no photos
        if (id === "photos" && i < 0 && next.indexOf("cast") < 0) next.push("cast")
        selected = next
        edited(next.join(","))
    }

    Repeater {
        model: root.parts
        Pill {
            label: (root.has(modelData.id) ? "✓  " : "") + modelData.label
            selected: root.has(modelData.id)
            accent: Theme.blue
            opacity: root.enabled ? 1 : 0.4
            onClicked: if (root.enabled) root.flip(modelData.id)
        }
    }
}
