// Line icons for the player bar, drawn on a canvas so they stay crisp at any size (no GPU needed).
// kinds: airplay, pip, snapshot, back, forward, panel, blackout
import QtQuick

Canvas {
    id: c
    property string kind: ""
    property color color: Theme.text
    implicitWidth: 22; implicitHeight: 22
    onKindChanged: requestPaint()
    onColorChanged: requestPaint()
    onWidthChanged: requestPaint()

    function rrect(ctx, x, y, w, h, r) {
        ctx.beginPath()
        ctx.moveTo(x + r, y); ctx.lineTo(x + w - r, y); ctx.arcTo(x + w, y, x + w, y + r, r)
        ctx.lineTo(x + w, y + h - r); ctx.arcTo(x + w, y + h, x + w - r, y + h, r)
        ctx.lineTo(x + r, y + h); ctx.arcTo(x, y + h, x, y + h - r, r)
        ctx.lineTo(x, y + r); ctx.arcTo(x, y, x + r, y, r)
        ctx.closePath()
    }

    onPaint: {
        const ctx = getContext("2d"), s = width / 22
        ctx.reset()
        ctx.scale(s, s)
        ctx.strokeStyle = color; ctx.fillStyle = color
        ctx.lineWidth = 1.7; ctx.lineCap = "round"; ctx.lineJoin = "round"
        if (kind === "airplay") {                       // screen with a triangle rising into its bottom edge
            ctx.beginPath()
            ctx.moveTo(6.5, 16); ctx.lineTo(4.5, 16); ctx.arcTo(2.5, 16, 2.5, 14, 2)
            ctx.lineTo(2.5, 5.5); ctx.arcTo(2.5, 3.5, 4.5, 3.5, 2)
            ctx.lineTo(17.5, 3.5); ctx.arcTo(19.5, 3.5, 19.5, 5.5, 2)
            ctx.lineTo(19.5, 14); ctx.arcTo(19.5, 16, 17.5, 16, 2); ctx.lineTo(15.5, 16)
            ctx.stroke()
            ctx.beginPath(); ctx.moveTo(11, 12.5); ctx.lineTo(16, 19.5); ctx.lineTo(6, 19.5); ctx.closePath(); ctx.fill()
        } else if (kind === "pip") {                    // big frame, small filled frame overlapping its corner
            rrect(ctx, 2, 3.5, 15, 11, 2); ctx.stroke()
            ctx.clearRect(9.6, 10.1, 11.4, 9.4)
            rrect(ctx, 10.5, 11, 9.5, 7.5, 1.6); ctx.fill()
        } else if (kind === "snapshot") {               // camera inside a dotted square
            ctx.save(); ctx.lineWidth = 1.4
            const dots = [1.5, 5.5, 9.5, 12.5, 16.5, 20.5]
            for (const d of dots) for (const e of [1.5, 20.5]) {
                ctx.beginPath(); ctx.arc(d, e, 0.75, 0, Math.PI * 2); ctx.fill()
                ctx.beginPath(); ctx.arc(e, d, 0.75, 0, Math.PI * 2); ctx.fill()
            }
            ctx.restore()
            ctx.beginPath()
            ctx.moveTo(6, 8); ctx.lineTo(8, 8); ctx.lineTo(9, 6.5); ctx.lineTo(13, 6.5); ctx.lineTo(14, 8); ctx.lineTo(16, 8)
            ctx.arcTo(17, 8, 17, 9, 1); ctx.lineTo(17, 15); ctx.arcTo(17, 16, 16, 16, 1)
            ctx.lineTo(6, 16); ctx.arcTo(5, 16, 5, 15, 1); ctx.lineTo(5, 9); ctx.arcTo(5, 8, 6, 8, 1)
            ctx.stroke()
            ctx.beginPath(); ctx.arc(11, 12, 2.3, 0, Math.PI * 2); ctx.stroke()
        } else if (kind === "back" || kind === "forward") {   // open arc (gap at the upper left), arrowhead on top, "10s" inside
            ctx.save()
            if (kind === "forward") { ctx.translate(22, 0); ctx.scale(-1, 1) }
            ctx.beginPath(); ctx.arc(11, 12, 8.5, -Math.PI / 2, Math.PI * 13 / 12, false); ctx.stroke()
            ctx.beginPath(); ctx.moveTo(7.6, 3.5); ctx.lineTo(11.6, 0.9); ctx.lineTo(11.6, 6.1); ctx.closePath(); ctx.fill()
            ctx.restore()
            ctx.font = "bold 6.6px sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle"
            ctx.fillText("10s", 11.2, 12.6)
        } else if (kind === "blackout") {               // a monitor, its screen gone dark: a crescent moon on it
            rrect(ctx, 2.5, 3, 17, 12, 2); ctx.stroke()
            ctx.beginPath(); ctx.moveTo(11, 15); ctx.lineTo(11, 18.2); ctx.moveTo(7.5, 18.8); ctx.lineTo(14.5, 18.8); ctx.stroke()
            ctx.save()
            ctx.beginPath(); ctx.arc(11, 9, 3.6, 0, Math.PI * 2); ctx.fill()
            ctx.globalCompositeOperation = "destination-out"
            ctx.beginPath(); ctx.arc(12.9, 7.6, 3.2, 0, Math.PI * 2); ctx.fill()
            ctx.restore()
        } else if (kind === "fullscreen" || kind === "windowed") {   // four corners, pointing out (or in)
            var o = kind === "fullscreen"
            var C = [[3, 3, 1, 1], [19, 3, -1, 1], [3, 19, 1, -1], [19, 19, -1, -1]]
            for (var i = 0; i < 4; i++) {
                var x = C[i][0], y = C[i][1], sx = C[i][2], sy = C[i][3]
                if (!o) { x += sx * 5; y += sy * 5; sx = -sx; sy = -sy }
                ctx.beginPath(); ctx.moveTo(x, y + sy * 5.5); ctx.lineTo(x, y); ctx.lineTo(x + sx * 5.5, y); ctx.stroke()
            }
        } else if (kind === "panel") {                  // three sliders
            for (const [y, k] of [[5, 14], [11, 7], [17, 12]]) {
                ctx.beginPath(); ctx.moveTo(3, y); ctx.lineTo(19, y); ctx.stroke()
                ctx.beginPath(); ctx.arc(k, y, 2.4, 0, Math.PI * 2); ctx.fill()
            }
        }
    }
}
