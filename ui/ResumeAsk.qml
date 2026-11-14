// "Resume from 42:10, or start over?" A small card over everything; Enter resumes, Esc or a click outside cancels.
// Turn it off in Settings > Playback (then titles simply resume).
import QtQuick

Item {
    id: root
    property string at: ""
    property var then: null                 // then(fromStart)
    property real shown: 0
    function ask(time, callback) { at = time; then = callback; shown = 1; card.forceActiveFocus() }
    function choose(fromStart) { var f = then; then = null; shown = 0; if (f) f(fromStart) }
    function cancel() { then = null; shown = 0 }
    visible: shown > 0.001
    z: 70
    Behavior on shown { NumberAnimation { duration: (root.shown < 0.5 ? 220 : 150) * Theme.motion; easing.type: Easing.OutCubic } }

    Rectangle { anchors.fill: parent; color: Theme.scrim; opacity: root.shown
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: (m) => { if (m.button === Qt.LeftButton) root.cancel() }; onWheel: (w) => w.accepted = true } }

    Rectangle {
        id: card
        anchors.centerIn: parent
        width: col.implicitWidth + 56; height: col.implicitHeight + 48
        radius: 18
        color: Theme.panel
        border.color: Theme.lineStrong
        opacity: root.shown
        scale: 0.96 + 0.04 * root.shown
        Keys.onEscapePressed: root.cancel()
        Keys.onReturnPressed: root.choose(false)
        Keys.onEnterPressed: root.choose(false)
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }
        Column {
            id: col
            anchors.centerIn: parent
            spacing: 16
            Column {
                spacing: 4
                Text { text: "Pick up where you stopped?"; color: Theme.text; font.pixelSize: 18; font.weight: Font.ExtraBold; font.letterSpacing: -0.3 }
                Text { text: "You stopped at " + root.at; color: Theme.faint; font.family: Theme.mono; font.pixelSize: 11 }
            }
            Row {
                spacing: 10
                GlassButton { primary: true; glyph: "▶"; label: "Resume from " + root.at; onClicked: root.choose(false) }
                GlassButton { label: "Start over"; onClicked: root.choose(true) }
            }
        }
    }
}
