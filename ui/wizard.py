"""First-run onboarding controller (Wizard.qml does the layout)."""
import json
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from . import pick_folder


class WizardController(QObject):
    """Exposed to QML as `Onboarding` (not `Wizard`: Wizard.qml is a type of that name and would shadow it). finished(folders, options) fires once, when Finish is pressed."""
    finished = Signal(object, object)

    @Slot(result=str)
    def pickFolder(self) -> str:
        try:
            return pick_folder()
        except Exception:
            return ""

    @Slot(str, result=str)
    def baseName(self, path: str) -> str:
        return Path(path).name or path

    @Slot(str, str, bool)
    def finish(self, folders_json: str, tmdb_key: str, associate: bool):
        folders = [f for f in json.loads(folders_json) if f.get("path")]
        self.finished.emit(folders, {"tmdb_key": tmdb_key.strip(), "associate": associate})
