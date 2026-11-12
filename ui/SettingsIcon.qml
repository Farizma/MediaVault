// A settings-category icon in the macOS System Settings manner: a white symbol on a coloured rounded square.
// kind: "appearance" | "playback" | "folders" | "integrations" | "backups"
import QtQuick

Rectangle {
    id: root
    property string kind: "appearance"
    property color tint: Theme.blue
    width: 24; height: 24; radius: 7
    color: tint
    gradient: Gradient {               // a soft top-down sheen, like the system icons
        GradientStop { position: 0; color: Qt.lighter(root.tint, 1.18) }
        GradientStop { position: 1; color: root.tint }
    }
    Canvas {
        id: glyph
        anchors.centerIn: parent
        width: 14; height: 14
        property string kind: root.kind
        onKindChanged: requestPaint()
        onPaint: {
            var c = getContext("2d"); c.reset()
            c.fillStyle = "#FFFFFF"; c.strokeStyle = "#FFFFFF"; c.lineWidth = 1.6; c.lineJoin = "round"; c.lineCap = "round"
            switch (kind) {
            case "appearance":       // contrast: a circle, left half filled
                c.beginPath(); c.arc(7, 7, 5.6, 0, Math.PI * 2); c.stroke()
                c.beginPath(); c.arc(7, 7, 5.6, Math.PI / 2, Math.PI * 1.5); c.closePath(); c.fill()
                break
            case "playback":         // play
                c.beginPath(); c.moveTo(4, 2.2); c.lineTo(12, 7); c.lineTo(4, 11.8); c.closePath(); c.fill()
                break
            case "folders":          // folder with a tab
                c.beginPath(); c.moveTo(1, 3.2); c.lineTo(5.2, 3.2); c.lineTo(6.6, 4.6); c.lineTo(13, 4.6)
                c.lineTo(13, 11.8); c.lineTo(1, 11.8); c.closePath(); c.fill()
                break
            case "integrations":     // key: ring, shaft, two teeth
                c.beginPath(); c.arc(4.4, 7, 2.8, 0, Math.PI * 2); c.stroke()
                c.beginPath(); c.moveTo(7.2, 7); c.lineTo(13, 7); c.moveTo(11, 7); c.lineTo(11, 9.6); c.moveTo(13, 7); c.lineTo(13, 9); c.stroke()
                break
            case "health":           // a pulse line
                c.beginPath(); c.moveTo(1, 7.5); c.lineTo(4, 7.5); c.lineTo(5.6, 3); c.lineTo(8.2, 12); c.lineTo(10, 7.5); c.lineTo(13, 7.5); c.stroke()
                break
            case "streaming":        // a screen with a triangle under it (AirPlay-like)
                c.beginPath(); c.moveTo(3.4, 9.6); c.lineTo(1.4, 9.6); c.lineTo(1.4, 1.6); c.lineTo(12.6, 1.6); c.lineTo(12.6, 9.6); c.lineTo(10.6, 9.6); c.stroke()
                c.beginPath(); c.moveTo(7, 8); c.lineTo(10.6, 13); c.lineTo(3.4, 13); c.closePath(); c.fill()
                break
            case "help":             // question mark
                c.beginPath(); c.arc(7, 4.8, 3, Math.PI * 1.05, Math.PI * 2.35); c.lineTo(7, 9); c.stroke()
                c.beginPath(); c.arc(7, 12, 1.1, 0, Math.PI * 2); c.fill()
                break
            case "components":       // stacked layers
                c.beginPath(); c.moveTo(7, 1.5); c.lineTo(12.5, 4.3); c.lineTo(7, 7.1); c.lineTo(1.5, 4.3); c.closePath(); c.stroke()
                c.beginPath(); c.moveTo(1.5, 7); c.lineTo(7, 9.8); c.lineTo(12.5, 7); c.stroke()
                c.beginPath(); c.moveTo(1.5, 9.7); c.lineTo(7, 12.5); c.lineTo(12.5, 9.7); c.stroke()
                break
            case "privacy":          // a padlock
                c.beginPath(); c.arc(7, 5.4, 3, Math.PI, 0); c.stroke()
                c.beginPath(); c.moveTo(2.4, 6); c.lineTo(11.6, 6); c.lineTo(11.6, 12.6); c.lineTo(2.4, 12.6); c.closePath(); c.fill()
                break
            case "backups":          // circular arrow (restore / update)
                c.beginPath(); c.arc(7, 7, 5, -Math.PI * 0.15, Math.PI * 1.45); c.stroke()
                c.beginPath(); c.moveTo(12.6, 1.2); c.lineTo(12.4, 5.4); c.lineTo(8.4, 4.6); c.stroke()
                break
            }
        }
    }
}
