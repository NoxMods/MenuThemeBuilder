from PySide6.QtCore import Qt, QPoint, QRectF, QSettings, QSize, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget,
                               QListWidgetItem, QPushButton, QStyle, QStyledItemDelegate, QVBoxLayout)

from .. import fontnet
from ..fontgen import family_for
from .widgets import draw_fit_ink

TILE_W, TILE_H = 216, 100
DEFAULT_SAMPLE = "CONTINUE   NEW GAME   MULTIPLAYER   OPTIONS"


class Worker(QThread):
    """Runs one slow call (a download) without freezing the window."""
    done = Signal(object, str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn(), "")
        except Exception as e:          # network errors, bad answers ...
            self.done.emit(None, str(e))


class TileDelegate(QStyledItemDelegate):
    """Every font is a tile that already shows your text written in that font."""

    def __init__(self, dlg):
        super().__init__(dlg)
        self.dlg = dlg

    def sizeHint(self, option, index):
        return QSize(TILE_W, TILE_H)

    def paint(self, p, option, index):
        d = self.dlg
        fam = index.data(Qt.UserRole)
        sel = bool(option.state & QStyle.State_Selected)
        r = option.rect.adjusted(4, 4, -4, -4)
        p.save()
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setPen(QPen(QColor("#3d7ad6") if sel else QColor("#3a3f46"), 2 if sel else 1))
        p.setBrush(QColor("#0d0e10"))
        p.drawRoundedRect(r, 6, 6)
        body = QRectF(r.adjusted(8, 6, -8, -22))
        q = d._qfam.get(fam)
        if q:
            p.setPen(QColor("white"))
            lines = d.sample_lines()
            h = body.height() / len(lines)
            for i, line in enumerate(lines):
                draw_fit_ink(p, QRectF(body.x(), body.y() + i * h, body.width(), h), line, q, 18)
        else:
            p.setFont(QFont())
            p.setPen(QColor("#666"))
            p.drawText(body, Qt.AlignCenter, "no preview" if fam in d._failed else "...")
        cap = QFont()
        cap.setPixelSize(11)
        p.setFont(cap)
        p.setPen(QColor("white") if sel else QColor("#9aa0a8"))
        p.drawText(QRectF(r.x() + 8, r.bottom() - 20, r.width() - 16, 16), Qt.AlignLeft | Qt.AlignVCenter, fam)
        p.restore()


class FontBrowser(QDialog):
    """Free Google Fonts as live tiles. Click one: it is shown at once in the main preview."""
    previewed = Signal(str, str, str)      # ttf path, family, licence path

    def __init__(self, parent=None, current=""):
        super().__init__(parent)
        self.setWindowTitle("Free fonts (Google Fonts)")
        self.resize(700, 640)
        self.result_font = None
        self._workers = []
        self._all = []
        self._qfam = {}        # google family -> family name Qt knows it by (font downloaded and loaded)
        self._paths = {}
        self._licenses = {}
        self._failed = set()
        self._active = set()
        self._queue = []
        self._want = ""
        self._ready = None
        self._placed = False
        self._current = current or QSettings().value("lastFontFamily", "") or ""

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search a font name...")
        self.cat = QComboBox()
        self.cat.addItem("All styles", "")
        top.addWidget(self.search, 1)
        top.addWidget(self.cat)
        lay.addLayout(top)
        self.sample = QLineEdit(DEFAULT_SAMPLE)
        self.sample.setToolTip("Type your own text: every tile shows it (in capitals, like the game's menu)")
        lay.addWidget(self.sample)
        self.list = QListWidget()
        self.list.setViewMode(QListView.IconMode)
        self.list.setResizeMode(QListView.Adjust)
        self.list.setMovement(QListView.Static)
        self.list.setUniformItemSizes(True)
        self.list.setSpacing(2)
        self.list.setItemDelegate(TileDelegate(self))
        lay.addWidget(self.list, 1)
        self.status = QLabel("Loading the font list...")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#9aa0a8;")
        lay.addWidget(self.status)
        row = QHBoxLayout()
        row.addStretch(1)
        self.use = QPushButton("Use this font")
        self.use.setEnabled(False)
        cancel = QPushButton("Cancel")
        row.addWidget(self.use)
        row.addWidget(cancel)
        lay.addLayout(row)

        self._vis_timer = QTimer(self)
        self._vis_timer.setSingleShot(True)
        self._vis_timer.setInterval(150)
        self._vis_timer.timeout.connect(self._queue_visible)
        self.search.textChanged.connect(self._refilter)
        self.cat.currentIndexChanged.connect(self._refilter)
        self.sample.textChanged.connect(lambda _t: self.list.viewport().update())
        self.list.currentItemChanged.connect(lambda cur, _prev: self._select(cur))
        self.list.verticalScrollBar().valueChanged.connect(lambda _v: self._vis_timer.start())
        self.use.clicked.connect(self._use)
        cancel.clicked.connect(self.reject)
        self._run(fontnet.list_google_fonts, self._listed)

    def sample_text(self):
        return (self.sample.text() or DEFAULT_SAMPLE).upper()

    def sample_lines(self):
        """The first two words/phrases of the sample (separated by 3+ spaces), one per line, so a tile stays readable."""
        parts = [x.strip() for x in self.sample_text().split("   ") if x.strip()]
        return parts[:2] or [self.sample_text()]

    # ---- background work
    def _run(self, fn, handler):
        w = Worker(fn, self)
        self._workers.append(w)
        w.done.connect(lambda res, err, w=w: self._finished(w, handler, res, err))
        w.start()

    def _finished(self, w, handler, res, err):
        if w in self._workers:
            self._workers.remove(w)
        handler(res, err)

    def done(self, r):
        for w in list(self._workers):      # never close while a download is still running
            w.wait(25000)
        super().done(r)

    def showEvent(self, e):
        super().showEvent(e)
        if not self._placed and self.parent() is not None:      # sit on the left so the main preview stays visible
            self._placed = True
            win = self.parent().window()
            self.move(win.frameGeometry().topLeft() + QPoint(14, 60))
        self._vis_timer.start()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._vis_timer.start()

    # ---- the list
    def _listed(self, res, err):
        if err or not res:
            res = (list(fontnet.CURATED), False)
        self._all, online = res
        for c in sorted({c for _, c in self._all if c}):
            self.cat.addItem(c, c)
        self._refilter()
        if online:
            self.status.setText(f"{len(self._all)} free fonts. Click one to see it in the preview.")
        else:
            self.status.setText("Could not reach Google Fonts, so a short built-in list is shown. "
                                "You can still use 'Choose a font file...' with any .ttf from your computer.")
        if not (self._goto(self._current) or self._goto(QSettings().value("lastFontFamily", "") or "")):
            self._vis_timer.start()

    def _refilter(self):
        q = self.search.text().strip().lower()
        cat = self.cat.currentData() or ""
        self.list.blockSignals(True)
        self.list.clear()
        for fam, c in self._all:
            if (q and q not in fam.lower()) or (cat and c != cat):
                continue
            if not q and fam.startswith("Noto "):      # huge files for other alphabets: only when searched for
                continue
            it = QListWidgetItem(fam)
            it.setData(Qt.UserRole, fam)
            it.setSizeHint(QSize(TILE_W, TILE_H))
            self.list.addItem(it)
        self.list.blockSignals(False)
        self._vis_timer.start()

    def _goto(self, family):
        """Select a font and scroll to it, so the window opens where you left it."""
        if not family:
            return False
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(Qt.UserRole) == family:
                self.list.setCurrentItem(it)
                self.list.scrollToItem(it, QListWidget.PositionAtCenter)
                return True
        return False

    # ---- lazy previews: only the tiles you can see are downloaded
    def _queue_visible(self):
        vp = self.list.viewport().rect()
        self._queue = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if self.list.visualItemRect(it).intersects(vp):
                fam = it.data(Qt.UserRole)
                if fam not in self._qfam and fam not in self._active and fam not in self._failed:
                    self._queue.append(fam)
        self._pump()

    def _pump(self):
        while len(self._active) < 3 and self._queue:
            fam = self._queue.pop(0)
            if fam in self._active or fam in self._qfam:
                continue
            self._active.add(fam)
            self._run(lambda f=fam: fontnet.download_google_font(f, with_license=False),
                      lambda res, err, f=fam: self._tile_loaded(f, res, err))

    def _tile_loaded(self, fam, res, err):
        self._active.discard(fam)
        q = family_for(res[0]) if res and not err else ""
        if q:
            self._qfam[fam] = q
            self._paths[fam] = res[0]
        else:
            self._failed.add(fam)
        self.list.viewport().update()
        if fam == self._want:
            self._chosen(fam, err)
        self._pump()

    # ---- choosing
    def _select(self, item):
        if item is None:
            return
        fam = item.data(Qt.UserRole)
        self._want = fam
        self._ready = None
        self.use.setEnabled(False)
        QSettings().setValue("lastFontFamily", fam)
        if fam in self._qfam:
            self._chosen(fam, "")
        elif fam in self._failed:
            self._chosen(fam, "")
        else:
            self.status.setText(f"Downloading {fam}...")
            if fam not in self._active:
                self._queue.insert(0, fam)
                self._pump()

    def _chosen(self, fam, err):
        if fam != self._want:
            return
        if fam not in self._qfam:
            self.status.setText(err or "This font could not be downloaded or read. Try another one.")
            return
        ttf, q = self._paths[fam], self._qfam[fam]
        lic = self._licenses.get(fam, "")
        self._ready = (ttf, q, lic)
        self.previewed.emit(ttf, q, lic)          # shown at once in the main preview
        if fam in self._licenses:
            self._finish_ready(fam)
        else:
            self.status.setText(f"{fam}: checking its licence...")
            self._run(lambda f=fam: fontnet.fetch_license(f),
                      lambda res, err2, f=fam: self._license_done(f, res or ""))

    def _license_done(self, fam, lic):
        self._licenses[fam] = lic
        if fam == self._want:
            self._ready = (self._paths[fam], self._qfam[fam], lic)
            self.previewed.emit(*self._ready)
            self._finish_ready(fam)

    def _finish_ready(self, fam):
        self.use.setEnabled(True)
        lic = self._licenses.get(fam, "")
        self.status.setText(f"{fam} - free to use (open licence). It is already shown in the main preview." +
                            ("" if lic else " Licence file not found: check its licence before publishing."))

    def _use(self):
        if self._ready:
            ttf, q, lic = self._ready
            self.result_font = dict(path=ttf, family=q, license=lic)
            self.accept()
