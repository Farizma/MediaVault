// Frame a picture for a box face: the frame has the face's shape (2:3 front and back, a tall thin spine, a round
// disc). Drag to move the picture, scroll or use the slider to zoom, Turn for a quarter turn. The picture always
// covers the frame. Use sends the frame as fractions of the picture (as shown) and the turns to Backend.saveCroppedArt.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: crop
    property string key: ""
    property string face: "front"
    property string path: ""
    property url src: ""
    property int turns: 0
    property real zoom: 1                       // 1 = the picture just covers the frame
    property real panX: 0
    property real panY: 0
    property real shown: 0
    readonly property real aspect: face === "spine" ? 60 / 810 : face === "disc" ? 1 : 135 / 190
    readonly property string faceName: ({ front: "front cover", back: "back cover", spine: "spine", disc: "disc" })[face] || face
    visible: shown > 0.001
    z: 45
    Behavior on shown { NumberAnimation { duration: (crop.shown < 0.5 ? 300 : 200) * Theme.motion; easing.type: Easing.OutCubic } }

    function open(k, f, url, p) { key = k; face = f; src = url; path = p; turns = 0; zoom = 1; panX = 0; panY = 0; shown = 1; panel.forceActiveFocus() }
    function close() { shown = 0 }
    function use() {
        // the frame's corners, in the picture's own (unturned, unscaled) coordinates
        var a = frame.mapToItem(img, 0, 0), b = frame.mapToItem(img, frame.width, frame.height)
        var x0 = Math.min(a.x, b.x) / img.width, x1 = Math.max(a.x, b.x) / img.width
        var y0 = Math.min(a.y, b.y) / img.height, y1 = Math.max(a.y, b.y) / img.height
        Backend.saveCroppedArt(key, face, path, Math.max(0, x0), Math.max(0, y0), Math.min(1, x1) - Math.max(0, x0), Math.min(1, y1) - Math.max(0, y0), turns)
        close()
    }

    Rectangle { anchors.fill: parent; color: Theme.scrim; opacity: crop.shown
        MouseArea { anchors.fill: parent; onClicked: crop.close(); onWheel: (w) => w.accepted = true } }

    Rectangle {
        id: panel
        anchors.centerIn: parent
        width: Math.min(parent.width - 48, 980); height: Math.min(parent.height - 48, 760)
        radius: 18; color: Theme.graphite; border.color: Theme.lineStrong
        opacity: crop.shown; scale: 0.94 + 0.06 * crop.shown
        focus: true
        Keys.onEscapePressed: crop.close()
        Keys.onReturnPressed: crop.use()
        MouseArea { anchors.fill: parent }

        ColumnLayout {
            anchors { fill: parent; margins: 22 }
            spacing: 14
            RowLayout {
                Layout.fillWidth: true
                Column {
                    Layout.fillWidth: true
                    spacing: 2
                    Text { text: "Frame the " + crop.faceName; color: Theme.text; font.pixelSize: 20; font.weight: Font.ExtraBold }
                    Text { text: "Drag to move · scroll to zoom · Turn for a quarter turn. Only what is inside the frame is used."; color: Theme.faint; font.pixelSize: 12 }
                }
            }
            // the picture under a fixed frame
            Item {
                id: canvas
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                readonly property real fw: Math.min(width * 0.86, height * 0.86 * crop.aspect)
                readonly property real fh: fw / crop.aspect
                Rectangle { anchors.fill: parent; color: "#0A0A0C"; radius: 10 }
                Image {
                    id: img
                    source: crop.src
                    autoTransform: true                     // the same EXIF turn the saved copy gets
                    sourceSize: Qt.size(2400, 2400)
                    asynchronous: true
                    smooth: true
                    // turned picture's outline, and the scale at which it just covers the frame
                    readonly property bool sideways: crop.turns % 2 === 1
                    readonly property real nw: Math.max(1, implicitWidth)
                    readonly property real nh: Math.max(1, implicitHeight)
                    readonly property real cover: Math.max(canvas.fw / (sideways ? nh : nw), canvas.fh / (sideways ? nw : nh))
                    readonly property real s: cover * crop.zoom
                    width: nw * s; height: nh * s
                    readonly property real bw: sideways ? height : width       // what the frame sees
                    readonly property real bh: sideways ? width : height
                    x: (canvas.width - width) / 2 + crop.panX
                    y: (canvas.height - height) / 2 + crop.panY
                    rotation: crop.turns * 90
                    Behavior on rotation { NumberAnimation { duration: 220 * Theme.motion; easing.type: Easing.OutCubic } }
                }
                // keep the picture covering the frame, whatever the zoom and turn
                function clampPan() {
                    var mx = Math.max(0, (img.bw - fw) / 2), my = Math.max(0, (img.bh - fh) / 2)
                    crop.panX = Math.max(-mx, Math.min(mx, crop.panX)); crop.panY = Math.max(-my, Math.min(my, crop.panY))
                }
                Connections { target: crop; function onZoomChanged() { canvas.clampPan() } function onTurnsChanged() { canvas.clampPan() } }
                // the frame, and everything outside it darkened
                Item {
                    id: frame
                    width: canvas.fw; height: canvas.fh
                    anchors.centerIn: parent
                }
                Rectangle { x: 0; y: 0; width: canvas.width; height: frame.y; color: "#A6000000" }
                Rectangle { x: 0; y: frame.y + frame.height; width: canvas.width; height: canvas.height - frame.y - frame.height; color: "#A6000000" }
                Rectangle { x: 0; y: frame.y; width: frame.x; height: frame.height; color: "#A6000000" }
                Rectangle { x: frame.x + frame.width; y: frame.y; width: canvas.width - frame.x - frame.width; height: frame.height; color: "#A6000000" }
                Rectangle { x: frame.x; y: frame.y; width: frame.width; height: frame.height; color: "transparent"; border.color: "#FFFFFF"; border.width: 1.5
                    radius: crop.face === "disc" ? width / 2 : 2 }
                MouseArea {
                    anchors.fill: parent
                    cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                    property point last
                    onPressed: (m) => last = Qt.point(m.x, m.y)
                    onPositionChanged: (m) => { crop.panX += m.x - last.x; crop.panY += m.y - last.y; last = Qt.point(m.x, m.y); canvas.clampPan() }
                    onWheel: (w) => { crop.zoom = Math.max(1, Math.min(6, crop.zoom * (1 + (w.angleDelta.y || w.pixelDelta.y * 3) / 1200))) }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 12
                GlassButton { small: true; label: "Turn"; glyph: "↻"; onClicked: { crop.turns = (crop.turns + 1) % 4 } }
                Text { text: "Zoom"; color: Theme.muted; font.pixelSize: 12 }
                Slider {
                    id: zoomSlider
                    Layout.preferredWidth: 220
                    from: 1; to: 6; value: crop.zoom
                    onMoved: crop.zoom = value
                }
                Item { Layout.fillWidth: true }
                GlassButton { label: "Cancel"; onClicked: crop.close() }
                GlassButton { label: "Use image"; primary: true; onClicked: crop.use() }
            }
        }
    }
}
