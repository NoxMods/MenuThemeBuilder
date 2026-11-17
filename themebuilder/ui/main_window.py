import os
import shutil
import json
from pathlib import Path

from PySide6.QtCore import Qt, QSettings, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QMainWindow, QMessageBox, QPushButton, QSplitter, QTabWidget, QToolBar,
                               QVBoxLayout, QApplication)

from .. import APP_NAME, APP_VERSION
from ..generator import build, validate, BuildError
from ..importer import import_theme
from ..model import Theme, PROJECT_FILE, load_project
from .preview import PreviewPanel
from .tabs import (InfoTab, BackgroundsTab, MusicTab, VideoTab, LayoutTab, CardsTab, FontTab, CreditsTab)


def default_workshop():
    return Path.home() / "Zomboid" / "Workshop"


class OpenDialog(QDialog):
    """Pick a theme made with this tool, or choose any other mod folder to import."""

    def __init__(self, workshop: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Open theme")
        self.resize(520, 380)
        self.result_path = None
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"Themes made with this tool in:\n{workshop}"))
        self.list = QListWidget()
        for d in sorted(workshop.glob(f"*/{PROJECT_FILE}")) if workshop.is_dir() else []:
            try:
                name = json.loads(d.read_text(encoding="utf-8")).get("name", d.parent.name)
            except (OSError, ValueError):
                name = d.parent.name
            it = QListWidgetItem(f"{name}   ({d.parent.name})")
            it.setData(Qt.UserRole, str(d.parent))
            self.list.addItem(it)
        if not self.list.count():
            self.list.addItem("(no themes found yet)")
            self.list.setEnabled(False)
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        ob = QPushButton("Open selected")
        ib = QPushButton("Open / import another folder…")
        cb = QPushButton("Cancel")
        ob.clicked.connect(self._open_sel)
        ib.clicked.connect(self._browse)
        cb.clicked.connect(self.reject)
        self.list.itemDoubleClicked.connect(lambda _: self._open_sel())
        row.addWidget(ob)
        row.addWidget(ib)
        row.addStretch(1)
        row.addWidget(cb)
        lay.addLayout(row)

    def _open_sel(self):
        it = self.list.currentItem()
        if it and it.data(Qt.UserRole):
            self.result_path = it.data(Qt.UserRole)
            self.accept()

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Choose a theme / mod folder")
        if d:
            self.result_path = d
            self.accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings()
        self.workshop = Path(self.settings.value("workshop", str(default_workshop())))
        self.theme = Theme()
        self.origin_root = None
        self.dirty = False

        self.tabs = QTabWidget()
        self.tab_list = [(InfoTab(), "Theme"), (BackgroundsTab(), "Backgrounds"), (MusicTab(), "Music"),
                         (VideoTab(), "Video"), (LayoutTab(), "Menu && Logo"), (CardsTab(), "Cards"),
                         (FontTab(), "Font"), (CreditsTab(), "Credits")]
        for w, title in self.tab_list:
            self.tabs.addTab(w, title)
            w.changed.connect(self._changed)
            w.reloadAll.connect(self._reload_tabs)
        self.preview = PreviewPanel()
        split = QSplitter()
        split.addWidget(self.tabs)
        split.addWidget(self.preview)
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 4)
        split.setSizes([680, 520])
        self.setCentralWidget(split)
        self.resize(1260, 820)

        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)
        for text, shortcut, fn in (("New", QKeySequence.New, self.on_new), ("Open…", QKeySequence.Open, self.on_open),
                                   ("Save && Build mod", QKeySequence.Save, self.on_save)):
            a = QAction(text, self)
            a.setShortcut(shortcut)
            a.triggered.connect(fn)
            tb.addAction(a)
        tb.addSeparator()
        a = QAction("Open Workshop folder", self)
        a.triggered.connect(self.on_open_workshop)
        tb.addAction(a)
        a = QAction("Set Workshop folder…", self)
        a.triggered.connect(self.on_set_workshop)
        tb.addAction(a)
        self.path_label = QLabel()
        self.statusBar().addPermanentWidget(self.path_label)
        self.set_theme(Theme(), None)
        self._update_status()

    # ---- state
    def set_theme(self, theme, origin_root, dirty=False):
        self.theme = theme
        self.origin_root = Path(origin_root) if origin_root else None
        for w, _ in self.tab_list:
            w.load(theme)
        self.preview.set_theme(theme)
        self.dirty = dirty
        self._update_status()

    def _reload_tabs(self):
        """A tab changed values that other tabs show (e.g. 'Turn off all animations'): redraw them all."""
        for w, _ in self.tab_list:
            w.load(self.theme)
        self.preview.refresh()

    def _changed(self):
        self.dirty = True
        self.preview.refresh()
        self._update_status()

    def _update_status(self):
        self.setWindowTitle(f"{self.theme.name or 'Untitled'}{' *' if self.dirty else ''} — {APP_NAME} {APP_VERSION}")
        self.path_label.setText(f"Workshop folder: {self.workshop}")

    def _confirm_discard(self):
        if not self.dirty:
            return True
        r = QMessageBox.question(self, "Unsaved changes", "Discard the unsaved changes?",
                                 QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Cancel)
        return r == QMessageBox.Discard

    # ---- actions
    def on_new(self):
        if self._confirm_discard():
            self.set_theme(Theme(), None)

    def on_open(self):
        if not self._confirm_discard():
            return
        dlg = OpenDialog(self.workshop, self)
        if dlg.exec() != QDialog.Accepted or not dlg.result_path:
            return
        folder = Path(dlg.result_path)
        try:
            root = folder if (folder / PROJECT_FILE).is_file() else next(
                (p for p in [folder.parent, folder.parent.parent] if (p / PROJECT_FILE).is_file()), None)
            if root:
                self.set_theme(load_project(root), root)
                return
            theme, notes = import_theme(folder)
        except (ValueError, OSError, KeyError, TypeError) as e:
            QMessageBox.critical(self, "Could not open", str(e))
            return
        self.set_theme(theme, None, dirty=True)
        QMessageBox.information(self, "Imported", "\n\n".join(notes))

    def on_set_workshop(self):
        d = QFileDialog.getExistingDirectory(self, "Workshop folder (…/Zomboid/Workshop)", str(self.workshop))
        if d:
            self.workshop = Path(d)
            self.settings.setValue("workshop", d)
            self._update_status()

    def on_open_workshop(self):
        self.workshop.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.workshop)))

    def on_save(self):
        errs, warns = validate(self.theme)
        if errs:
            QMessageBox.warning(self, "Can't build yet", "Please fix:\n\n• " + "\n• ".join(errs))
            return
        if warns:
            r = QMessageBox.question(self, "Warnings", "• " + "\n• ".join(warns) + "\n\nBuild anyway?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if r != QMessageBox.Yes:
                return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            try:
                new, root = build(self.theme, self.workshop)
            except BuildError as e:
                if not str(e).startswith("FOREIGN:"):
                    raise
                QApplication.restoreOverrideCursor()
                r = QMessageBox.warning(
                    self, "Folder already exists",
                    f"{e.args[0][8:]}\n\nalready exists and was not made by this tool. Replace it completely?",
                    QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
                if r != QMessageBox.Yes:
                    return
                QApplication.setOverrideCursor(Qt.WaitCursor)
                new, root = build(self.theme, self.workshop, allow_foreign_overwrite=True)
        except BuildError as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Build failed", str(e))
            return
        finally:
            while QApplication.overrideCursor():
                QApplication.restoreOverrideCursor()

        old = self.origin_root
        self.set_theme(new, root)
        self.statusBar().showMessage(f"Saved to {root}", 8000)
        if old and old.exists() and old.resolve() != root.resolve() and (old / PROJECT_FILE).exists():
            r = QMessageBox.question(self, "Old folder", f"The theme was renamed. Delete the old folder?\n\n{old}",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r == QMessageBox.Yes:
                shutil.rmtree(old, ignore_errors=True)
        box = QMessageBox(self)
        box.setWindowTitle("Mod saved")
        box.setText(f"Your theme was written to:\n{root}\n\n"
                    "In the game: Mods → enable \"Menu Theme Framework\" and this theme, then accept. "
                    "Only one menu theme can be active at a time.")
        openb = box.addButton("Open folder", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Ok)
        box.exec()
        if box.clickedButton() is openb:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(root)))

    def closeEvent(self, e):
        if self._confirm_discard():
            e.accept()
        else:
            e.ignore()
