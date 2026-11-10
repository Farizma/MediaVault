// A disc: the art (disc art, else the poster) clipped to a circle, with a clear plastic hub and the centre hole.
// No art: plain silver with a coloured label band. Canvas, so it draws without a GPU.
import QtQuick

Item {
    id: root
    property url source
    property real spin: 0                 // degrees
    Canvas {
        id: c
        anchors.fill: parent
        rotation: root.spin
        property url src: root.source
        onSrcChanged: { if (src != "") loadImage(src); requestPaint() }
        onImageLoaded: requestPaint()
        onWidthChanged: requestPaint()
        onPaint: {
            var g = getContext("2d"), w = width, r = w / 2
            g.reset()
            g.save()
            g.beginPath(); g.arc(r, r, r, 0, Math.PI * 2); g.clip()
            if (src != "" && isImageLoaded(src)) {
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
