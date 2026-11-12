"""A click anywhere outside the text box you are typing in ends the edit, as on the web and in macOS: the box loses
focus, so whatever saves on focus loss (titles, synopses, notes, settings) saves there and then. Qt on its own keeps
focus in the box when you click empty space, so the edit stayed open until you clicked another field.

Not when the click lands in a popup (a tag suggestion, a menu): those act on what you typed. Focus goes to the
nearest item that declares `focusHome` (View More, so Esc still closes it), else to the window."""
from PySide6.QtCore import QEvent, QObject


def _within(item, scene_pos) -> bool:
    return item.contains(item.mapFromScene(scene_pos))


def _in_text_box(item, scene_pos) -> bool:
    """On the box itself, or on the scroll view around it (its scroll bar, its padding)."""
    node = item
    for _ in range(4):
        if node is None:
            break
        if node is item or node.inherits("QQuickScrollView"):
            if _within(node, scene_pos):
                return True
        node = node.parentItem()
    return False


def _in_popup(window, scene_pos) -> bool:
    for child in window.contentItem().childItems():
        if child.inherits("QQuickOverlay"):
            return any(p.isVisible() and _within(p, scene_pos) for p in child.childItems())
    return False


class ClickAway(QObject):
    def eventFilter(self, window, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            try:
                self._press(window, event.scenePosition())
            except Exception:       # never let a focus nicety break a click
                pass
        return False

    @staticmethod
    def _press(window, pos):
        item = window.activeFocusItem()
        if item is None or not (item.inherits("QQuickTextInput") or item.inherits("QQuickTextEdit")):
            return
        if _in_text_box(item, pos) or _in_popup(window, pos):
            return
        home = item.parentItem()
        while home is not None and home.property("focusHome") is not True:
            home = home.parentItem()
        (home or window.contentItem()).forceActiveFocus()
