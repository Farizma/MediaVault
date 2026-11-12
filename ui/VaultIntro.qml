// The opening: the Media Vault logo, drawn here from the same shapes as the icon, with its dial spinning while
// the library loads (it keeps spinning until everything is in, however long that takes). Then the dial clicks into
// place, the door swings open on its hinge and shows the dashboard inside, and the view zooms in through the
// opening until the dashboard fills the window. Reduced motion: a short fade instead.
//
//   VaultIntro { ready: ...; onZoomChanged: ... }      `zoom` (0.86 -> 1) is for the content underneath
import QtQuick

Item {
    id: root
    property bool ready: false              // the library is loaded
    property real zoom: 0.86                // what the content underneath should scale to (1 when the vault is open)
    readonly property bool done: phase === "done"
    property string phase: "spin"           // spin -> open -> zoom -> done
    property real holeR: 0                  // the round opening the dashboard shows through
    property real dialAngle: 0
    property real doorAngle: 0              // 0 closed .. 105 open
    property real tileFade: 1               // the logo's square background, gone once the door opens
    property real ringScale: 1
    readonly property real s: Math.min(width, height) * 0.30          // the logo's size
    readonly property real diag: Math.sqrt(width * width + height * height)
    visible: phase !== "done"
    z: 1000

    // the minimum show: one and a half turns of the dial even when everything is already loaded
    Timer { id: minSpin; interval: 900; running: true; onTriggered: root.tryOpen() }
    onReadyChanged: tryOpen()
    function tryOpen() {
        if (!ready || minSpin.running || phase !== "spin") return
        if (Theme.motion > 0) openUp.start(); else quick.start()
    }

    MouseArea { anchors.fill: parent; hoverEnabled: true }       // nothing underneath is clickable until it is open

    // everything outside the opening is the page colour: a ring whose hole is the opening (works on any renderer)
    Rectangle {
        readonly property real b: root.diag
        anchors.centerIn: parent
        width: 2 * (root.holeR + b); height: width; radius: width / 2
        color: "transparent"
        border.width: b
        border.color: Theme.black
    }

    Item {
        id: logo
        anchors.centerIn: parent
        width: root.s; height: root.s
        scale: root.ringScale

        // the icon's rounded square
        Rectangle {
            anchors.fill: parent
            radius: width * 0.22
            opacity: root.tileFade
            gradient: Gradient {
                GradientStop { position: 0; color: "#26262A" }
                GradientStop { position: 1; color: "#121214" }
            }
        }
        // the dial: ring and eight ticks, turning like a combination lock
        Item {
            anchors.fill: parent
            rotation: root.dialAngle
            Rectangle {
                anchors.centerIn: parent
                width: parent.width * 0.656; height: width; radius: width / 2
                color: "transparent"; border.color: "#EBFFFFFF"; border.width: parent.width * 0.035
            }
            Repeater {
                model: 8
                Rectangle {
                    width: logo.width * 0.035; height: logo.width * 0.04; radius: width / 2
                    color: "#FFFFFF"
                    x: logo.width / 2 - width / 2; y: logo.width * 0.117
                    transform: Rotation { origin.x: width / 2; origin.y: logo.width / 2 - logo.width * 0.117; angle: index * 45 }
                }
            }
        }
        // the door: the dark disc with the bars, hinged on its left edge
        Item {
            id: door
            readonly property real r: logo.width * 0.242
            x: logo.width / 2 - r; y: logo.height / 2 - r
            width: 2 * r; height: 2 * r
            opacity: 1 - Math.max(0, (root.doorAngle - 70) / 35)
            transform: Rotation { origin.x: 0; origin.y: door.r; axis { x: 0; y: 1; z: 0 } angle: -root.doorAngle }
            Rectangle {
                anchors.fill: parent; radius: width / 2
                color: "#0E0E10"
                border.width: logo.width * 0.027
                border.color: "#0A84FF"
                Rectangle {        // the green half of the icon's blue-to-green ring
                    anchors.fill: parent; anchors.margins: parent.border.width * 0.45; radius: width / 2
                    color: "transparent"; border.width: parent.border.width * 0.45; border.color: "#5530D158"
                }
            }
            Row {                  // the bars of the icon (a shelf of cases)
                anchors.horizontalCenter: parent.horizontalCenter
                y: door.r * 0.72
                spacing: door.r * 0.06
                Repeater {
                    model: [["#0A84FF", 0.53], ["#FFFFFF", 0.63], ["#30D158", 0.48], ["#FF9F0A", 0.58]]
                    Rectangle {
                        width: door.r * 0.27; height: door.r * modelData[1] * 1.6; radius: width * 0.24
                        color: modelData[0]
                        anchors.bottom: parent.bottom
                        rotation: index === 3 ? 14 : 0
                    }
                }
            }
            Rectangle { x: door.r * 0.35; y: door.r * 1.42; width: door.r * 1.3; height: door.r * 0.11; radius: height / 2; color: "#E6FFFFFF" }
        }
    }

    // while loading: the dial turns steadily, a turn every 1.2 s
    NumberAnimation on dialAngle {
        id: spinning
        running: root.phase === "spin" && Theme.motion > 0
        from: 0; to: 360; duration: 1200; loops: Animation.Infinite
    }

    SequentialAnimation {
        id: openUp
        ScriptAction { script: { spinning.stop(); root.phase = "open"; settle.from = root.dialAngle; settle.to = Math.ceil(root.dialAngle / 360) * 360 + 45 } }
        // the dial clicks into place
        NumberAnimation { id: settle; target: root; property: "dialAngle"; duration: 380; easing.type: Easing.OutBack; easing.overshoot: 1.6 }
        // the door swings open on its hinge; the dashboard shows through the opening behind it
        ParallelAnimation {
            NumberAnimation { target: root; property: "tileFade"; to: 0; duration: 260; easing.type: Easing.OutCubic }
            NumberAnimation { target: root; property: "holeR"; to: logo.width * 0.242; duration: 300; easing.type: Easing.OutCubic }
            NumberAnimation { target: root; property: "doorAngle"; to: 105; duration: 520; easing.type: Easing.InOutCubic }
        }
        ScriptAction { script: root.phase = "zoom" }
        // through the opening: it widens past the edges while the dashboard comes up to full size
        ParallelAnimation {
            NumberAnimation { target: root; property: "holeR"; to: root.diag * 0.6; duration: 650; easing.type: Easing.InOutCubic }
            NumberAnimation { target: root; property: "ringScale"; to: 6; duration: 650; easing.type: Easing.InCubic }
            NumberAnimation { target: logo; property: "opacity"; to: 0; duration: 420; easing.type: Easing.InCubic }
            NumberAnimation { target: root; property: "zoom"; to: 1; duration: 650; easing.type: Easing.InOutCubic }
        }
        ScriptAction { script: root.phase = "done" }
    }
    // reduced motion: no spin, no swing, just a short fade
    SequentialAnimation {
        id: quick
        ScriptAction { script: root.zoom = 1 }
        NumberAnimation { target: root; property: "opacity"; to: 0; duration: 150 }
        ScriptAction { script: root.phase = "done" }
    }
}
