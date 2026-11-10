"""Media Vault entry point.

1. setup.run_setup()             checks every requirement, installs what is missing, and refuses to
                                 start until it is all there (no skip)
2. single-instance lock          QLocalServer = a Windows named pipe. A second launch hands its file
                                 path to the first one and exits
4. QML app: wizard on first run (no media_vault.db yet), otherwise the dashboard; the player HUD is a
   second QML window that only appears during playback
"""
import atexit
import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path

import setup

PIPE_NAME = "MediaVaultSingleton"
SHOW = "\0show"  # message that means "just bring the window forward"


class App:
    """Owns the long-lived services and connects them: watcher -> dashboard, player -> database."""

    def __init__(self, qapp, initial: str = ""):
        import database as db
        from player.player_engine import PlayerEngine
        from ui.dashboard import Dashboard, LibraryModel, TabsModel
        from ui.dvd_box import FrameProvider
        from ui.wizard import WizardController
        from watcher import Watcher

        self.db, self.initial, self.ready = db, initial, False
        self.main_window = None
        self.qml_context = None
        self.frames, self.library, self.tabs = FrameProvider(), LibraryModel(), TabsModel()
        self.engine = PlayerEngine(self.resolve, self.frames)       # `engine` = the player (Dashboard reads engine.hw)
        self.engine.on_progress, self.engine.on_mark_intro = self.on_progress, self.on_mark_intro
        self.engine.on_mark_credits = lambda s, left: db.set_credits(s.credits_key, left) if s.credits_key else None
        self.engine.on_setting = db.set_setting
        self.engine.pipChanged.connect(self._pip_changed)
        self.dashboard = Dashboard(self, self.library, self.tabs, self.frames)
        self.wizard = WizardController()
        self.watcher = Watcher(lambda _ids: self.dashboard.libraryChanged.emit())
        self.updates = None
        self.presence = None        # Discord status, created once the database is open
        self._presence_item = (None, None)
        self.engine.closed.connect(self._after_playback)
        self.engine.stateChanged.connect(self._presence_tick)
        self.engine.closed.connect(lambda: self.presence and self.presence.update(None))
        self.engine.error.connect(self.dashboard.toast)
        self.engine.artChanged.connect(lambda _p: self.dashboard.libraryChanged.emit())
        self.wizard.finished.connect(self.finish_setup)
        self.dashboard.needsSetup = not db.db_exists()
        atexit.register(self.shutdown)

    # -- startup
    def attach(self, main_window, hud_window=None):
        self.main_window = main_window
        self.engine.hud = hud_window
        self._restore_window(main_window)
        main_window.closing.connect(self._main_closing)
        if not self.dashboard.needsSetup:
            self.start_library()

    def finish_setup(self, folders, options):
        db = self.db
        db.init_db()
        if options["tmdb_key"]:
            db.set_setting("tmdb_key", options["tmdb_key"])
        for f in folders:
            db.add_directory(f["path"], f["tab"], bool(f["scrape"]), f.get("parts"), "anilist" if f.get("anime") else "tmdb")
        if options["associate"]:
            self.set_file_types(True)
        self.start_library()

    def start_library(self):
        db = self.db
        db.init_db()
        from utils import hw_accelerator
        self.engine.level = int(hw_accelerator.resolve(db.get_setting("upscale_level"), self.engine.hw.level))
        self.engine.core_pref = db.get_setting("core") or "auto"
        self.engine.auto_credits = db.get_setting("auto_credits") != "0"
        try:
            scale, pos, box = (db.get_setting("sub_style") or "1.0,100,0").split(",")
            self.engine.sub = {"scale": float(scale), "pos": int(pos), "box": box == "1"}
        except ValueError:
            pass
        try:
            self.engine.audio_delay = max(-5.0, min(5.0, float(db.get_setting("audio_delay") or 0)))
            mode, peak, scene = (db.get_setting("hdr") or "tonemap,0,1").split(",")
            self.engine.hdr = {"mode": mode if mode in ("tonemap", "display") else "tonemap", "peak": int(peak), "scene": scene == "1"}
        except ValueError:
            pass
        self.engine.night = db.get_setting("night_mode") == "1"
        self.engine.blackout = db.get_setting("blackout") != "0"
        try:
            from PySide6.QtCore import QRect
            x, y, w, h = (int(v) for v in (db.get_setting("player_geometry") or "").split(","))
            self.engine.player_geo = QRect(x, y, w, h)
        except ValueError:
            pass
        from utils.discord_presence import Presence
        self.presence = Presence(db.get_setting)
        self.ready = True
        self.dashboard.start()
        self.watcher.start()
        for d in db.list_directories():
            self.watcher.watch(d)
        threading.Thread(target=self._initial_scan, daemon=True, name="initial-scan").start()
        from utils import backup_manager
        backup_manager.start()
        self.updates = setup.UpdateDaemon(self._updates_found)
        self.updates.start()
        if self.initial:
            self.handle_arg(self.initial)

    def _presence_tick(self):
        """Feed the player state to the Discord status (it sends only real changes, rate limited)."""
        p, s, st = self.presence, self.engine.session, self.engine.state
        if not (p and p.enabled and s and st.get("active")):
            return
        if self._presence_item[0] != s.path:
            self._presence_item = (s.path, self.db.get_media(s.uuid) if s.uuid else None)
        item = self._presence_item[1] or {}
        kind = item.get("media_type", "clip")
        title = self.db.series_title(item["title"]) if kind == "show" else (item.get("title") or s.title)
        p.update({"title": title, "kind": kind, "episode": self.db.episode_suffix(item.get("title", "")).strip(),
                  "year": (item.get("release_date") or "")[:4], "position": st.get("position", 0),
                  "duration": st.get("duration", 0), "paused": st.get("paused", False), "speed": st.get("speed", 1.0)})

    def _initial_scan(self):
        from watcher import scan_directory
        changed = False
        for d in self.db.list_directories():
            try:
                changed |= bool(scan_directory(d))
            except Exception:
                logging.exception("scan failed for %s", d["folder_path"])
        if changed:
            self.dashboard.libraryChanged.emit()

    # -- library
    def add_directory(self, path, tab=None, scrape=True, parts=None, source="tmdb"):
        from watcher import scan_directory
        db = self.db
        did = db.add_directory(path, tab or Path(path).name or path, scrape, parts, source)
        directory = db.get_directory(did)
        self.watcher.watch(directory)

        def scan():
            scan_directory(directory)
            self.dashboard.libraryChanged.emit()
        threading.Thread(target=scan, daemon=True, name="scan").start()
        self.dashboard.libraryChanged.emit()

    def remove_directory(self, dir_id):
        self.watcher.unwatch(dir_id)
        self.db.remove_directory(dir_id)
        self.dashboard.libraryChanged.emit()

    # -- playback
    def play(self, path, from_start=False):
        self._start_over = self.db.norm(path) if from_start else None   # resolve() skips the resume point once
        self.engine.screen = self.main_window.screen() if self.main_window else None
        self.engine.play(path)

    def resolve(self, path):
        from player.player_engine import Session
        from utils import scraper
        db = self.db
        item = db.get_media_by_path(path) if self.ready else None
        if not item:  # opened from Explorer and not in the library: plays, but nothing is saved
            return Session(path=path, title=Path(path).stem)
        resume = item["last_position"] > 10 and not item["is_completed"] and getattr(self, "_start_over", None) != item["file_path"]
        self._start_over = None
        nxt = db.next_episode(item["uuid"])
        credits_key = os.path.dirname(item["file_path"]) if item["media_type"] == "show" else item["file_path"]
        return Session(path=item["file_path"], title=item["title"], uuid=item["uuid"],
                       credits=db.get_credits(credits_key), credits_key=credits_key,
                       start=max(0, item["last_position"] - 3) if resume else 0,
                       next_path=nxt["file_path"] if nxt else None, next_title=nxt["title"] if nxt else "",
                       intro=db.get_intro(os.path.dirname(item["file_path"])),
                       poster=scraper.poster_path(item), fanart=scraper.fanart_path(item))

    def on_progress(self, session, pos, dur, completed, watched):
        if session.uuid:
            self.db.save_progress(session.uuid, pos, completed)
            self.db.log_watch(session.uuid, watched)

    def on_mark_intro(self, session, start, end):
        self.db.set_intro(os.path.dirname(session.path), start, end)

    def _pip_changed(self, on: bool):
        """Picture in picture: only the small video window stays on screen; Media Vault minimises."""
        if on and self.main_window:
            self.dashboard.minimizeWindow.emit()

    # -- the library window: same size and place as last time; closing it ends Media Vault, player included
    def _restore_window(self, w):
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QGuiApplication
        try:
            x, y, width, height, maxed = (int(v) for v in (self.db.get_setting("window_geometry") or "").split(","))
        except (ValueError, Exception):
            return
        g = QRect(x, y, max(width, w.minimumWidth()), max(height, w.minimumHeight()))
        if any(sc.availableGeometry().intersects(g) for sc in QGuiApplication.screens()):   # a monitor may be gone
            w.setGeometry(g)
        if maxed:
            w.showMaximized()

    def _main_closing(self, *_):
        from PySide6.QtGui import QWindow
        w = self.main_window
        maxed = w.visibility() == QWindow.Visibility.Maximized
        g = w.property("normalGeo") if maxed else w.geometry()     # maximised: keep the size it returns to
        if not g or g.width() < 100:
            g = w.geometry()
        try:
            self.db.set_setting("window_geometry", f"{g.x()},{g.y()},{g.width()},{g.height()},{int(maxed)}")
        except Exception:
            logging.exception("save window size")
        self.quit()

    def _after_playback(self):
        self.dashboard.libraryChanged.emit()
        self.dashboard.raiseWindow.emit()

    def set_theme(self, theme_id: str) -> None:
        import ui
        db = self.db
        self.db.set_setting("theme", ui.apply_theme(theme_id, custom=ui.custom_from(db.get_setting)))
        if self.qml_context:
            self.qml_context.setContextProperty("Theme", ui.THEME)  # every binding on Theme.* updates live

    # -- upkeep
    def set_file_types(self, on: bool):
        try:
            (setup.register_file_types if on else setup.unregister_file_types)()
            self.dashboard.toast.emit("Media Vault added to \"Open with\"" if on else "File associations removed")
        except Exception as e:
            logging.exception("file types")
            self.dashboard.toast.emit(f"Could not change file associations: {e}")

    def _updates_found(self, found):
        if found.get("app"):
            self.dashboard.toast.emit(f"Media Vault {found['app']} is available. Settings > Components.")
            return
        names = ", ".join(found["packages"] + (["libmpv"] if found["mpv"] else []))
        self.dashboard.toast.emit(f"Updates available: {names}. Settings > Components.")

    def quit(self):
        """Media Vault ends: the player and its windows go too (a picture-in-picture window never stays behind)."""
        from PySide6.QtGui import QGuiApplication
        self.shutdown()
        QGuiApplication.quit()

    def check_updates(self, manual=False):
        def work():
            try:
                found = setup.check_updates()
                if not (found["packages"] or found["mpv"] or found.get("app")):
                    self.dashboard.toast.emit("Everything is up to date")
                elif manual:  # the person asked, so apply
                    setup.apply_updates(found)
                    self.dashboard.toast.emit("Updated. Restart Media Vault to use the new versions.")
            except Exception as e:
                logging.exception("update check")
                self.dashboard.toast.emit(f"Update check failed: {e}")
        threading.Thread(target=work, daemon=True, name="update-check").start()

    # -- a second launch hands us a file
    def handle_arg(self, arg: str):
        """A file from "Open with" (or a second launch). Runs on the next event-loop pass, never inside the
        socket's signal, and never lets an error take the app down."""
        from watcher import is_video
        try:
            arg = (arg or "").strip().strip('"')
            if arg and arg != SHOW and os.path.isfile(arg) and is_video(arg):  # only ever play real video files
                if self.ready:
                    self.dashboard.raiseWindow.emit()
                    self.play(arg)
                else:
                    self.initial = arg
            else:
                self.dashboard.raiseWindow.emit()
        except Exception:
            logging.exception("open with")
            self.dashboard.toast.emit("Could not open that file. Details are in media_vault.log.")

    def shutdown(self):
        try:
            self.dashboard.stream.stop()
            self.engine.stop()
            if self.updates:
                self.updates.stop()
            self.watcher.stop()
        except RuntimeError:
            pass  # observer was never started (first-run wizard abandoned)


def setup_logging():
    import database as db
    handler = logging.handlers.RotatingFileHandler(db.data_dir() / "media_vault.log", maxBytes=1_000_000,
                                                   backupCount=2, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler],
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sys.excepthook = lambda *a: logging.critical("uncaught", exc_info=a)

    from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    levels = {QtMsgType.QtDebugMsg: logging.DEBUG, QtMsgType.QtInfoMsg: logging.INFO,
              QtMsgType.QtWarningMsg: logging.WARNING, QtMsgType.QtCriticalMsg: logging.ERROR,
              QtMsgType.QtFatalMsg: logging.CRITICAL}
    qInstallMessageHandler(lambda kind, ctx, msg: logging.getLogger("qt").log(levels.get(kind, logging.INFO), msg))


def main() -> int:
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if not setup.run_setup():
        return 1

    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtWidgets import QApplication, QMessageBox

    qapp = QApplication(sys.argv[:1])
    from PySide6.QtGui import QIcon
    qapp.setWindowIcon(QIcon(str(Path(__file__).resolve().parent / "ui" / "brand" / "icon-256.png")))  # taskbar, title bars
    qapp.setApplicationName("Media Vault")

    def send_to_primary() -> bool:
        sock = QLocalSocket()
        sock.connectToServer(PIPE_NAME)
        if not sock.waitForConnected(400):
            return False
        sock.write((os.path.abspath(arg) if arg else SHOW).encode("utf-8"))
        sock.waitForBytesWritten(2000)
        sock.disconnectFromServer()
        return True

    if send_to_primary():  # an instance is running: it plays the file and this process just ends
        return 0
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.UserAccessOption)  # only this Windows user may talk to us
    QLocalServer.removeServer(PIPE_NAME)
    if not server.listen(PIPE_NAME) and send_to_primary():  # lost a start-up race with another launch
        return 0

    setup_logging()

    import database as db
    import ui

    from utils import backup_manager
    restored = backup_manager.apply_pending_restore()   # a portable backup staged last time: swap it in first

    app = App(qapp, arg)
    reduced = ui.detect_reduced_motion()  # the Windows "show animations" switch ...
    if db.db_exists():
        db.init_db()
        reduced = reduced or db.get_setting("reduce_motion") == "1"  # ... or our own setting
    ui.THEME["motion"] = 0 if reduced else 1
    if db.db_exists():
        ui.apply_theme(db.get_setting("theme") or "", custom=ui.custom_from(db.get_setting))
    else:
        ui.apply_theme("")

    def on_connection():
        conn = server.nextPendingConnection()
        if conn:
            buf = bytearray()
            conn.readyRead.connect(lambda c=conn, b=buf: b.extend(bytes(c.readAll())))
            # the whole message arrives before the sender disconnects; act on it from the event loop afterwards
            conn.disconnected.connect(lambda c=conn, b=buf: (b.extend(bytes(c.readAll())),
                                                           QTimer.singleShot(0, lambda: app.handle_arg(bytes(b).decode("utf-8", "ignore"))),
                                                           c.deleteLater()))
    server.newConnection.connect(on_connection)

    ui.load_fonts(qapp)
    QQuickStyle.setStyle("Basic")  # the only style that lets every control be re-skinned
    engine = QQmlApplicationEngine()
    engine.addImageProvider("frames", app.frames)
    ctx = engine.rootContext()
    app.qml_context = ctx
    for name, obj in (("Theme", ui.THEME), ("Backend", app.dashboard), ("Library", app.library),
                      ("Tabs", app.tabs), ("Onboarding", app.wizard), ("Player", app.engine)):
        ctx.setContextProperty(name, obj)
    engine.load(QUrl.fromLocalFile(str(ui.QML_DIR / "Main.qml")))
    engine.load(QUrl.fromLocalFile(str(ui.PLAYER_DIR / "Hud.qml")))
    if len(engine.rootObjects()) < 2:
        logging.critical("QML failed to load (see qt log lines above)")
        QMessageBox.critical(None, "Media Vault", "The interface failed to load. Details are in media_vault.log.")
        return 1
    qapp.setQuitOnLastWindowClosed(False)     # Media Vault ends when its library window closes (see App._main_closing)
    app.attach(engine.rootObjects()[0], engine.rootObjects()[1])
    if restored:
        app.dashboard.toast.emit("Portable backup restored")
    code = qapp.exec()
    app.shutdown()
    return code


if __name__ == "__main__":
    sys.exit(main())
