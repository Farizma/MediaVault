// 3D DVD box that needs no GPU. Each face is an ordinary 2D item; the box's own 3D maths (rotate, perspective)
// turns every face into a projected quad, and a perspective transform (a homography) maps the item onto it.
// That runs on any Qt renderer: Direct3D, OpenGL, WARP, or Qt Quick's pure software renderer.
// Faces facing away are hidden and the rest are drawn far-to-near, which is exact for a closed box.
//
// Spins slowly on its own; drag to spin it yourself, it coasts after you let go.
// Front = poster (or your own art), back = your back art or title + description, spine = your spine art or the title.
// `opened` swings the front cover open on its spine and shows the disc (the play animation).
import QtQuick

Item {
    id: root
    property url front
    property url back
    property url spine                     // empty: a spine is drawn from the title and year
    property url disc                      // disc art (else the poster is used for the disc)
    property string title: ""
    property string year: ""
    property real yaw: -28
    property real dim: 0                   // 0..1: greys the whole box (carousel neighbours that are not in focus)
    property real opened: 0                // 0 = closed, 1 = cover open, disc showing
    property bool spinning: true           // passive spin while nobody is touching it
    property bool hint: true               // show "Drag to spin" (its row is always reserved, so the box never jumps)
    readonly property bool dragging: drag.pressed || coast.running

    // a real keep case is 135 x 190 x 14 mm: same proportions, so real cover and spine scans fit without cropping
    readonly property real boxW: 213
    readonly property real boxH: 300
    readonly property real boxD: 22
    // camera far enough back that the box fits at any angle; it backs off further while the cover swings open
    readonly property real camZ: 740
    readonly property real fov: 30
    readonly property real viewH: height - 24
    property real zoom: 1                  // scroll wheel over the box: 0.7 .. 1.8 (a longer lens, so nothing distorts)
    Behavior on zoom { NumberAnimation { duration: 160 * Theme.motion; easing.type: Easing.OutCubic } }
    readonly property real focal: viewH / (2 * Math.tan(fov * Math.PI / 360)) * zoom
    // on-screen height of the front face when it faces the camera: DetailView lines the box up with a card
    readonly property real faceH: boxH * focal / (camZ - boxD / 2)
    readonly property real faceCY: viewH / 2
    implicitWidth: 360
    implicitHeight: 470

    // ---- geometry: every face's projected corners (tl, tr, br, bl as seen from outside), depth and lighting
    readonly property var geo: {
        var t = yaw * Math.PI / 180, c = Math.cos(t), s = Math.sin(t)
        var cz = camZ + 260 * opened, cx = width / 2, cy = viewH / 2, f = focal
        var W = boxW / 2, H = boxH / 2, D = boxD / 2
        var L = [-0.32, 0.38, 0.87]            // light from the upper left, toward the box
        function P(x, y, z) {
            var X = x * c + z * s, Z = -x * s + z * c, k = f / (cz - Z)
            return { x: cx + X * k, y: cy - y * k, z: Z }
        }
        function lit(nx, ny, nz) {             // 0 = full light, 1 = in shadow
            var X = nx * c + nz * s, Z = -nx * s + nz * c
            return 1 - Math.max(0, X * L[0] + ny * L[1] + Z * L[2])
        }
        function face(q, n) {
            var cross = (q[1].x - q[0].x) * (q[3].y - q[0].y) - (q[1].y - q[0].y) * (q[3].x - q[0].x)
            return { q: q, show: cross > 1, z: (q[0].z + q[1].z + q[2].z + q[3].z) / 4, shade: n }
        }
        // the cover, hinged on the spine edge: angle a swings it toward the camera
        var a = -110 * opened * Math.PI / 180, ca = Math.cos(a), sa = Math.sin(a)
        function lid(u, y) { return P(-W + u * ca, y, D - u * sa) }
        var lidN = [-sa, 0, ca]                // the cover's outward normal after the swing
        return {
            front:  face([lid(0, H), lid(2 * W, H), lid(2 * W, -H), lid(0, -H)], lit(lidN[0], 0, lidN[2])),
            liner:  face([lid(2 * W, H), lid(0, H), lid(0, -H), lid(2 * W, -H)], lit(-lidN[0], 0, -lidN[2])),
            back:   face([P(W, H, -D), P(-W, H, -D), P(-W, -H, -D), P(W, -H, -D)], lit(0, 0, -1)),
            spine:  face([P(-W, H, -D), P(-W, H, D), P(-W, -H, D), P(-W, -H, -D)], lit(-1, 0, 0)),
            edge:   face([P(W, H, D), P(W, H, -D), P(W, -H, -D), P(W, -H, D)], lit(1, 0, 0)),
            top:    face([P(-W, H, -D), P(W, H, -D), P(W, H, D), P(-W, H, D)], lit(0, 1, 0)),
            bottom: face([P(-W, -H, D), P(W, -H, D), P(W, -H, -D), P(-W, -H, -D)], lit(0, -1, 0)),
            tray:   face([P(-W, H, -D + 0.5), P(W, H, -D + 0.5), P(W, -H, -D + 0.5), P(-W, -H, -D + 0.5)], lit(0, 0, 1)),
            disc:   face([P(-86, 86, -D + 3), P(86, 86, -D + 3), P(86, -86, -D + 3), P(-86, -86, -D + 3)], 0)
        }
    }

    // perspective transform taking an item's own w x h rectangle onto a projected quad (square-to-quad homography)
    function homography(w, h, q) {
        var x0 = q[0].x, y0 = q[0].y, x1 = q[1].x, y1 = q[1].y, x2 = q[2].x, y2 = q[2].y, x3 = q[3].x, y3 = q[3].y
        var dx1 = x1 - x2, dx2 = x3 - x2, dx3 = x0 - x1 + x2 - x3
        var dy1 = y1 - y2, dy2 = y3 - y2, dy3 = y0 - y1 + y2 - y3
        var g = 0, k = 0
        var det = dx1 * dy2 - dx2 * dy1
        if (Math.abs(det) > 1e-9 && (Math.abs(dx3) > 1e-9 || Math.abs(dy3) > 1e-9)) {
            g = (dx3 * dy2 - dx2 * dy3) / det
            k = (dx1 * dy3 - dx3 * dy1) / det
        }
        var a = x1 - x0 + g * x1, b = x3 - x0 + k * x3, d = y1 - y0 + g * y1, e = y3 - y0 + k * y3
        return Qt.matrix4x4(a / w, b / h, 0, x0,
                            d / w, e / h, 0, y0,
                            0,     0,     1, 0,
                            g / w, k / h, 0, 1)
    }

    // one face: an item of size w x h, mapped onto its quad, shaded by how far it turns from the light
    component Face: Item {
        id: face
        property var g
        default property alias content: body.data
        visible: g.show
        z: g.z
        Item { id: body; anchors.fill: parent; clip: true }
        Rectangle { anchors.fill: parent; color: "#000000"; opacity: 0.6 * face.g.shade }
        Rectangle { anchors.fill: parent; color: "#2C2C2F"; opacity: 0.72 * root.dim; visible: root.dim > 0 }
        transform: Matrix4x4 { matrix: root.homography(face.width, face.height, face.g.q) }
    }

    Item {
        id: scene
        anchors.fill: parent
        // inside of the case (seen once the cover opens)
        Face { g: root.geo.tray; visible: root.opened > 0; width: 426; height: 600
            Rectangle { anchors.fill: parent; color: "#141416" }
            Repeater { model: 3; Rectangle { x: 26; y: 120 + index * 150; width: 374; height: 2; color: "#1F1F22" } }
        }
        // the disc, seated in the tray; it spins up as the cover opens
        Face { g: root.geo.disc; visible: root.opened > 0 && root.geo.disc.show; width: 344; height: 344
            Disc { anchors.fill: parent; source: root.disc; spin: 540 * root.opened }
        }
        Face { g: root.geo.back; width: 426; height: 600
            Image { anchors.fill: parent; source: root.back; fillMode: Image.PreserveAspectCrop; asynchronous: true; sourceSize.width: 426 }
        }
        Face { g: root.geo.top; width: 426; height: 44; Rectangle { anchors.fill: parent; color: "#2C2C2E" } }
        Face { g: root.geo.bottom; width: 426; height: 44; Rectangle { anchors.fill: parent; color: "#232325" } }
        Face { g: root.geo.edge; width: 44; height: 600   // the opening side: the cover's lip over the tray
            Rectangle { anchors.fill: parent; color: "#2C2C2E" }
            Rectangle { x: 20; width: 4; height: parent.height; color: "#1F1F22" }
        }
        Face { g: root.geo.spine; width: 44; height: 600
            Image { id: spineArt; anchors.fill: parent; source: root.spine; visible: status === Image.Ready; fillMode: Image.Stretch; asynchronous: true }
            Rectangle {                     // no spine art: title and year, like a shelf of real cases
                anchors.fill: parent; visible: !spineArt.visible; color: "#0E0E10"
                Rectangle { width: parent.width; height: 10; color: Theme.blue }
                Text {
                    anchors.centerIn: parent
                    width: parent.height - 150
                    rotation: 90
                    text: root.title.toUpperCase()
                    color: "#FFFFFF"; font.pixelSize: 22; font.weight: Font.ExtraBold; font.letterSpacing: 1
                    horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight
                }
                Text { anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 44 } rotation: 90
                    text: root.year; color: "#99FFFFFF"; font.family: Theme.mono; font.pixelSize: 14 }
                Text { anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 10 }
                    text: "MV"; color: Theme.blue; font.pixelSize: 13; font.weight: Font.ExtraBold }
            }
        }
        // the cover: outside (poster) and inside (liner); only the side facing you is drawn
        Face { g: root.geo.liner; width: 426; height: 600; Rectangle { anchors.fill: parent; color: "#1C1C1E" } }
        Face { g: root.geo.front; width: 426; height: 600
            Image { anchors.fill: parent; source: root.front; fillMode: Image.PreserveAspectCrop; asynchronous: true; sourceSize.width: 426 }
            Rectangle {                     // the sleeve's gloss slides across as the box turns
                width: parent.width * 0.7; height: parent.height * 1.4; y: -parent.height * 0.2
                x: parent.width * (0.15 + 0.9 * Math.sin(root.yaw * Math.PI / 180)) - width / 2
                rotation: 14
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: "#00FFFFFF" }
                    GradientStop { position: 0.5; color: "#1FFFFFFF" }
                    GradientStop { position: 1.0; color: "#00FFFFFF" }
                }
            }
        }
    }

    // passive spin: 20 degrees a second, paused while you drag, and for a moment after it stops coasting
    FrameAnimation {
        running: root.spinning && root.visible && !root.dragging && !rest.running && Theme.motion > 0
        onTriggered: root.yaw -= 20 * frameTime
    }
    Timer { id: rest; interval: 1500 }

    // 1:1 drag, then momentum from the release velocity
    WheelHandler {
        enabled: root.enabled
        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
        onWheel: (ev) => {
            var d = ev.pixelDelta.y !== 0 ? ev.pixelDelta.y / 400 : ev.angleDelta.y / 1200
            root.zoom = Math.max(0.7, Math.min(1.8, root.zoom * (1 + d)))
            ev.accepted = true
        }
    }
    MouseArea {
        id: drag
        anchors.fill: parent
        cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
        property real lastX: 0
        property real lastT: 0
        property real velocity: 0
        onPressed: (m) => { coast.stop(); lastX = m.x; lastT = Date.now(); velocity = 0 }
        onPositionChanged: (m) => {
            var dx = (m.x - lastX) * 0.6
            root.yaw += dx
            var now = Date.now()
            velocity = dx / Math.max(1, now - lastT) * 16     // degrees per frame
            lastX = m.x; lastT = now
        }
        onReleased: {
            if (Theme.motion > 0 && Math.abs(velocity) > 0.3 && Date.now() - lastT < 80) coast.start()
            else rest.restart()
        }
    }
    Timer {
        id: coast
        interval: 16; repeat: true
        onTriggered: {
            root.yaw += drag.velocity
            drag.velocity *= 0.95
            if (Math.abs(drag.velocity) < 0.05) { stop(); rest.restart() }
        }
    }
    Text {
        anchors { bottom: parent.bottom; horizontalCenter: parent.horizontalCenter }
        text: "Drag to spin \u00B7 scroll to zoom"; color: Theme.faint; font.family: Theme.mono; font.pixelSize: 10
        opacity: root.hint ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 200 * Theme.motion } }
    }
}
