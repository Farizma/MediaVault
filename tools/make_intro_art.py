"""Cut ui/brand/icon.svg into the four layers the opening animation moves (ui/VaultIntro.qml):
intro-tile.png (the rounded square, with the opening cut out), intro-dial.png (ring and ticks: it spins), intro-door.png (the dark disc with the
shelf: it swings open) and intro-rim.png (the blue-to-green edge of the opening). Stacked in that order they are the icon.
Run again after changing the icon:  python tools/make_intro_art.py"""
import re
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QPointF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

BRAND = Path(__file__).resolve().parent.parent / "ui" / "brand"
SIZE = 1024


def main():
    QGuiApplication.instance() or QGuiApplication(sys.argv[:1] + ["-platform", "offscreen"])
    svg = (BRAND / "icon.svg").read_text(encoding="utf-8")
    head, body = svg.split("</defs>", 1)
    head += "</defs>"
    tile = re.search(r'<rect x="8"[^>]*/>', body).group(0)
    dial = re.search(r'<circle cx="128" cy="128" r="84".*?</g>', body, re.S).group(0)
    door = re.search(r'<circle cx="128" cy="128" r="62" fill="#0E0E10"/>\s*<g clip-path="url\(#inside\)">.*?</g>', body, re.S).group(0)
    rim = re.search(r'<circle cx="128" cy="128" r="62" fill="none" stroke="url\(#ring\)"[^>]*/>', body).group(0)
    for name, part in (("tile", tile), ("dial", dial), ("door", door), ("rim", rim)):
        renderer = QSvgRenderer(QByteArray((head + part + "</svg>").encode()))
        img = QImage(SIZE, SIZE, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        renderer.render(p)
        k = SIZE / 256
        p.setPen(Qt.NoPen)
        p.setBrush(Qt.black)
        if name == "door":                # Qt's SVG renderer skips clip-path: keep the shelf inside the disc by hand
            p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            p.drawEllipse(QPointF(128 * k, 128 * k), 62 * k, 62 * k)
        if name == "tile":                # the opening (inside the rim): the dashboard shows through it once the door swings
            p.setCompositionMode(QPainter.CompositionMode_DestinationOut)
            p.drawEllipse(QPointF(128 * k, 128 * k), 59 * k, 59 * k)
        p.end()
        img.save(str(BRAND / f"intro-{name}.png"))
        print("wrote", f"intro-{name}.png")


if __name__ == "__main__":
    main()
