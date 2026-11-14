// The opening: the Media Vault icon itself (ui/brand/intro-*.png, cut from icon.svg by tools/make_intro_art.py),
// with its dial spinning while the library loads (it keeps spinning until everything is in, however long that takes).
// Then the dial clicks into place, the door swings open on its hinge and the dashboard shows through the opening, and
// the view flies in through the opening until the dashboard fills the window. Everything outside the opening stays
// fully opaque the whole way. Reduced motion: a short fade instead.
//
//   VaultIntro { ready: ...; onZoomChanged: ... }      `zoom` (0.86 -> 1) is for the content underneath
import QtQuick

Item {
    id: root
    property bool ready: false              // the library is loaded
    property real zoom: 0.86                // what the content underneath should scale to (1 when the vault is open)
    readonly property bool done: phase === "done"
    property string phase: "spin"           // spin -> open -> zoom -> done
    property real dialAngle: 0
    property real doorAngle: 0              // 0 closed .. 105 open
    property real opening: 0                // 0 shut .. 1: the hole behind the door reaches the rim
    property real ringScale: 1              // the whole logo, growing as the view flies in
    readonly property real s: Math.min(width, height) * 0.30          // the logo's size
    readonly property real diag: Math.sqrt(width * width + height * height)
    readonly property real rimR: s * 58.5 / 256                        // the inside edge of the blue-to-green rim
    // the hole the dashboard shows through: the rim's inside, growing with the logo, never wider
    readonly property real holeR: rimR * opening * ringScale
    // how far the logo grows: until the opening is wider than the window
    readonly property real flyScale: (diag / 2 + 40) / Math.max(1, rimR)
    visible: phase !== "done"
    z: 1000

    // the minimum show: one and a half turns of the dial even when everything is already loaded
    Timer { id: minSpin; interval: 900; running: true; onTriggered: root.tryOpen() }
    onReadyChanged: tryOpen()
    function tryOpen() {
        if (!ready || minSpin.running || phase !== "spin") return
        if (Theme.motion > 0) openUp.start(); else quick.start()
    }

    MouseArea { anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.AllButtons }       // nothing underneath is clickable until it is open

    // the page colour everywhere but the opening: a ring whose hole is the opening (works on any renderer)
    Rectangle {
        readonly property real b: root.diag * 2
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
        component Layer: Image {
            anchors.fill: parent
            sourceSize: Qt.size(1024, 1024)
            smooth: true; mipmap: true
        }
        // the icon's rounded square, the opening cut out of it: around the opening it stays solid. Until the door
        // swings, the door covers the opening; behind it the page colour fills the hole, then the dashboard does.
        Layer { source: "brand/intro-tile.png" }
        // the dial: ring and eight ticks, turning like a combination lock
        Layer { source: "brand/intro-dial.png"; rotation: root.dialAngle }
        // the door: the dark disc with the shelf, hinged on its left edge
        Layer {
            source: "brand/intro-door.png"
            opacity: 1 - Math.max(0, (root.doorAngle - 70) / 35)
            transform: Rotation { origin.x: logo.width * (128 - 62) / 256; origin.y: logo.height / 2
                                  axis { x: 0; y: 1; z: 0 } angle: -root.doorAngle }
        }
        // the rim of the opening, in front of the door's edge
        Layer { source: "brand/intro-rim.png" }
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
            NumberAnimation { target: root; property: "opening"; to: 1; duration: 300; easing.type: Easing.OutCubic }
            NumberAnimation { target: root; property: "doorAngle"; to: 105; duration: 520; easing.type: Easing.InOutCubic }
        }
        ScriptAction { script: root.phase = "zoom" }
        // through the opening: the whole logo grows (the solid frame with it) until the opening is wider than the
        // window, while the dashboard comes up to full size
        ParallelAnimation {
            NumberAnimation { target: root; property: "ringScale"; to: root.flyScale; duration: 700; easing.type: Easing.InCubic }
            NumberAnimation { target: root; property: "zoom"; to: 1; duration: 700; easing.type: Easing.InOutCubic }
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
