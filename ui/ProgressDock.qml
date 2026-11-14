// Progress pills under the top bar: one per long job (scraping a folder, downloading artwork, a component or an
// update). They drop in, fill as the job goes, turn green when it is done and lift away a moment later.
// Jobs come from Backend.jobs (utils/progress.py); a ListModel keeps each pill alive between updates so only new
// ones animate in.
import QtQuick

Item {
    id: root
    width: 400
    height: list.contentHeight
    readonly property int pillH: 58

    ListModel { id: model }
    function sync() {
        var jobs = Backend.jobs || [], seen = {}
        for (var i = 0; i < jobs.length; i++) {
            var j = jobs[i]; seen[j.id] = true
            var row = -1
            for (var k = 0; k < model.count; k++) if (model.get(k).jid === j.id) { row = k; break }
            var data = { jid: j.id, label: j.label, detail: j.detail || "", done: j.done, total: j.total, unit: j.unit || "", state: j.state }
            if (row < 0) model.append(data); else model.set(row, data)
        }
        for (var m = model.count - 1; m >= 0; m--) if (!seen[model.get(m).jid]) model.remove(m)
    }
    Connections { target: Backend; function onJobsChanged() { root.sync() } }
    Component.onCompleted: sync()

    function amount(d) {
        if (d.unit === "bytes") {
            var mb = function(b) { return (b / 1048576).toFixed(b < 10485760 ? 1 : 0) }
            return d.total > 0 ? mb(d.done) + " / " + mb(d.total) + " MB" : mb(d.done) + " MB"
        }
        return d.total > 0 ? d.done + " / " + d.total : ""
    }

    ListView {
        id: list
        anchors { left: parent.left; right: parent.right; top: parent.top }
        height: contentHeight
        interactive: false
        spacing: 8
        model: model
        add: Transition {
            ParallelAnimation {
                NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 220 * Theme.motion; easing.type: Easing.OutCubic }
                NumberAnimation { property: "scale"; from: 0.96; to: 1; duration: 280 * Theme.motion; easing.type: Easing.OutBack; easing.overshoot: 1.2 }
            }
        }
        remove: Transition {
            ParallelAnimation {
                NumberAnimation { property: "opacity"; to: 0; duration: 180 * Theme.motion; easing.type: Easing.InCubic }
                NumberAnimation { property: "scale"; to: 0.96; duration: 180 * Theme.motion; easing.type: Easing.InCubic }
            }
        }
        displaced: Transition { NumberAnimation { properties: "y"; duration: 240 * Theme.motion; easing.type: Easing.OutCubic } }

        delegate: Rectangle {
            id: pill
            width: list.width
            height: root.pillH
            radius: 14
            color: Qt.rgba(Qt.color(Theme.slate).r, Qt.color(Theme.slate).g, Qt.color(Theme.slate).b, 0.96)
            border.color: model.state === "failed" ? Theme.red : "#33FFFFFF"
            readonly property bool finished: model.state !== "running"
            readonly property real frac: model.total > 0 ? Math.min(1, model.done / model.total) : (finished ? 1 : 0)
            readonly property color tone: model.state === "failed" ? Theme.red : model.state === "done" ? Theme.green : Theme.blue
            // drops in from just under the top bar
            transform: Translate { id: drop; y: -14 }
            Component.onCompleted: dropIn.start()
            NumberAnimation { id: dropIn; target: drop; property: "y"; to: 0; duration: 300 * Theme.motion; easing.type: Easing.OutCubic }

            Rectangle { z: -1; anchors.fill: parent; anchors.topMargin: 6; anchors.margins: -2; radius: 16; color: "#59000000" }   // shadow

            Spinner { id: pillSpin; anchors { left: parent.left; leftMargin: 14; verticalCenter: title.verticalCenter }
                size: 12; color: Theme.blue; running: !pill.finished }
            Text {
                id: title
                anchors { left: pillSpin.running ? pillSpin.right : parent.left; leftMargin: pillSpin.running ? 8 : 14; right: count.left; rightMargin: 10; top: parent.top; topMargin: 10 }
                text: model.label; elide: Text.ElideRight
                color: Theme.text; font.pixelSize: 12; font.weight: Font.Bold
            }
            Text {
                id: count
                anchors { right: parent.right; rightMargin: 14; verticalCenter: title.verticalCenter }
                text: pill.finished ? (model.state === "done" ? "✓ Done" : "Stopped") : root.amount(model)
                color: pill.finished ? pill.tone : Theme.muted; font.family: Theme.mono; font.pixelSize: 11
            }
            Text {
                anchors { left: parent.left; leftMargin: 14; right: parent.right; rightMargin: 14; top: title.bottom; topMargin: 2 }
                text: model.detail; elide: Text.ElideMiddle
                color: Theme.faint; font.pixelSize: 11
            }
            // the bar: fills smoothly; with no total yet a short segment sweeps across instead
            Rectangle {
                id: track
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 12; bottomMargin: 9 }
                height: 4; radius: 2; color: Theme.fill
                clip: true
                Rectangle {
                    visible: model.total > 0 || pill.finished
                    height: parent.height; radius: 2; color: pill.tone
                    width: Math.max(height, parent.width * pill.frac)
                    Behavior on width { NumberAnimation { duration: 260 * Theme.motion; easing.type: Easing.OutCubic } }
                    Behavior on color { ColorAnimation { duration: 200 * Theme.motion } }
                }
                Rectangle {
                    id: sweep
                    visible: model.total <= 0 && !pill.finished
                    height: parent.height; radius: 2; width: parent.width * 0.3; color: pill.tone
                    NumberAnimation on x {
                        running: sweep.visible && Theme.motion > 0
                        from: -sweep.width; to: track.width; duration: 1100; loops: Animation.Infinite; easing.type: Easing.InOutSine
                    }
                }
            }
        }
    }
}
