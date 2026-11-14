// A disc: the art (disc art, else the poster) clipped to a circle, with a clear plastic hub and the centre hole.
// No art: plain silver with a coloured label band. Canvas, so it draws without a GPU.
// dataSide: the other face, the one a player reads: mirror silver with a rainbow sheen that turns with the disc.
import QtQuick

Item {
    id: root
    property url source
    property real spin: 0                 // degrees
    property bool dataSide: false
    Canvas {
        id: c
        anchors.fill: parent
        rotation: root.spin
        property url src: root.dataSide ? "" : root.source
        property bool readSide: root.dataSide
        onReadSideChanged: requestPaint()
        onSrcChanged: { if (src != "") loadImage(src); requestPaint() }
        onImageLoaded: requestPaint()
        onWidthChanged: requestPaint()
        onPaint: {
            var g = getContext("2d"), w = width, r = w / 2
            g.reset()
            g.save()
            g.beginPath(); g.arc(r, r, r, 0, Math.PI * 2); g.clip()
            if (readSide) {
                var m = g.createRadialGradient(r, r, w * 0.16, r, r, r)
                m.addColorStop(0, "#C9CDD3"); m.addColorStop(0.5, "#E9ECF0"); m.addColorStop(1, "#AEB4BC")
                g.fillStyle = m; g.fillRect(0, 0, w, w)
                var rb = g.createConicalGradient(r, r, 0)          // light split by the tracks: a soft rainbow
                var hues = ["#FF5A5A", "#FFC24A", "#7BE36A", "#4AD6FF", "#6A7BFF", "#E46AFF", "#FF5A5A"]
                for (var i = 0; i < hues.length; i++) rb.addColorStop(i / (hues.length - 1), hues[i])
                g.globalAlpha = 0.28; g.fillStyle = rb; g.fillRect(0, 0, w, w); g.globalAlpha = 1
                g.strokeStyle = "rgba(255,255,255,0.10)"; g.lineWidth = 1        // the tracks
                for (var t = w * 0.2; t < r; t += Math.max(3, w * 0.012)) { g.beginPath(); g.arc(r, r, t, 0, Math.PI * 2); g.stroke() }
            } else if (src != "" && isImageLoaded(src)) {
                g.drawImage(src, 0, 0, w, w)
            } else {
                var s = g.createLinearGradient(0, 0, w, w)
                s.addColorStop(0, "#EEF1F5"); s.addColorStop(0.35, "#A9AFB8"); s.addColorStop(0.65, "#D9DDE3"); s.addColorStop(1, "#9DA3AC")
                g.fillStyle = s; g.fillRect(0, 0, w, w)
                g.fillStyle = Theme.blue; g.globalAlpha = 0.85; g.fillRect(8, r - w * 0.09, w - 16, w * 0.18); g.globalAlpha = 1
            }
            // a sheen sweeping across the surface
            var sh = g.createLinearGradient(0, 0, w, 0)
            sh.addColorStop(0, "rgba(255,255,255,0)"); sh.addColorStop(0.45, "rgba(255,255,255,0.22)"); sh.addColorStop(0.55, "rgba(255,255,255,0)")
            g.fillStyle = sh; g.fillRect(0, 0, w, w)
            g.restore()
            // clear hub, silver ring, hole
            g.beginPath(); g.arc(r, r, w * 0.17, 0, Math.PI * 2); g.fillStyle = "rgba(220,224,230,0.55)"; g.fill()
            g.beginPath(); g.arc(r, r, w * 0.17, 0, Math.PI * 2); g.lineWidth = Math.max(1, w * 0.01); g.strokeStyle = "rgba(255,255,255,0.6)"; g.stroke()
            g.beginPath(); g.arc(r, r, w * 0.055, 0, Math.PI * 2); g.fillStyle = "#141416"; g.fill()
            g.beginPath(); g.arc(r, r, r - 1, 0, Math.PI * 2); g.lineWidth = 2; g.strokeStyle = "rgba(255,255,255,0.35)"; g.stroke()
        }
    }
}
