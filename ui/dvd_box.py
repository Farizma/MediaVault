"""Pictures for the 3D DVD box and for the in-RAM frame pool.

FrameProvider serves `image://frames/<name>` straight from memory: the 4 thumbnail candidates and
the live snapshot never touch the disk until the user picks one.
"""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtQuick import QQuickImageProvider

import database as db
from utils import scraper
from . import file_url

FRONT_W, FRONT_H = 576, 810  # texture size for the box faces: 135 x 190 mm, a real DVD keep case
FRONT_W_H = (FRONT_W, FRONT_H)
SPINE_W_H = (60, FRONT_H)  # 22 : 300, a real keep case spine (14 : 190 mm)


def pil_to_qimage(img) -> QImage:
    img = img.convert("RGBA")
    w, h = img.size
    return QImage(img.tobytes("raw", "RGBA"), w, h, w * 4, QImage.Format_RGBA8888).copy()


class FrameProvider(QQuickImageProvider):
    def __init__(self):
        super().__init__(QQuickImageProvider.Image)
        self._images: dict[str, QImage] = {}

    def set_pil(self, name: str, img) -> None:
        self._images[name] = pil_to_qimage(img)

    def clear(self, name: str | None = None) -> None:
        if name is None:
            self._images.clear()
        else:
            self._images.pop(name, None)

    def requestImage(self, id, size, requestedSize):
        img = self._images.get(id.split("?")[0])
        return img if img is not None else QImage(1, 1, QImage.Format_ARGB32)


def _text_card(title: str, body: str) -> QImage:
    img = QImage(FRONT_W, FRONT_H, QImage.Format_RGB32)
    img.fill(QColor("#1C1C1E"))
    p = QPainter(img)
    flags = Qt.AlignLeft.value | Qt.AlignTop.value | Qt.TextWordWrap.value
    font = QFont()
    font.setPixelSize(42)
    font.setBold(True)
    p.setFont(font)
    p.setPen(QColor("#F5F5F7"))
    p.drawText(QRectF(44, 60, FRONT_W - 88, 220), flags, title)
    font.setPixelSize(26)
    font.setBold(False)
    p.setFont(font)
    p.setPen(QColor("#8E8E93"))
    p.drawText(QRectF(44, 300, FRONT_W - 88, FRONT_H - 360), flags, body)
    p.end()
    return img


def _card(folder, uid: str, face: str, title: str, body: str):
    """A titled card face, drawn once per text (View More used to redraw and re-save it on every open and every
    carousel turn, on the interface's own thread; and a face rewritten while it was loading failed to decode)."""
    import hashlib
    tag = hashlib.sha1(f"{title}\0{body}".encode("utf-8")).hexdigest()[:10]
    path = folder / f"{uid}-{face}-{tag}.png"
    if not path.exists():
        for old in folder.glob(f"{uid}-{face}*.png"):      # the card for the old text
            old.unlink(missing_ok=True)
        tmp = path.with_suffix(".tmp.png")
        _text_card(title, body).save(str(tmp))
        tmp.replace(path)                                  # whole or not at all
    return path


def box_textures(item: dict) -> dict:
    """File URLs for the front and back faces. The front is the poster, or a titled card if there is none."""
    folder = db.data_dir() / "cache" / "box"
    folder.mkdir(parents=True, exist_ok=True)
    front = scraper.cover_path(item)
    if not front.exists():
        front = _card(folder, item["uuid"], "front", item["title"], "")
    back = scraper.custom_back_path(item)
    if not back.exists():
        back = _card(folder, item["uuid"], "back", item["title"], item.get("synopsis") or "No description yet.")
    spine = scraper.spine_path(item)
    return {"front": file_url(front), "back": file_url(back), "spine": file_url(spine) if spine else "",
            "customFront": scraper.custom_front_path(item).exists(), "customBack": scraper.custom_back_path(item).exists(),
            "customSpine": scraper.custom_spine_path(item).exists()}
