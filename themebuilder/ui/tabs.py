from pathlib import Path

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QDialog, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
                               QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..mediainfo import read_ogg_info, read_bik_info
from ..fontgen import family_for
from ..model import (Track, Clip, LAYOUTS, TRANSITIONS, BUTTON_IDS, slug, auto_prefix, parse_credits,
                     final_credit_groups, credit_screen_groups)
from .fonts_dialog import FontBrowser
from .preview import HighlightGallery, CaptionSample, natural_size
from .widgets import (ImagePicker, FilePicker, IMG_FILTER, make_thumb, note, labeled, CollapsibleSection, InkLabel)

OGG_FILTER = "Ogg audio (*.ogg)"


def scrolled(widget):
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QScrollArea.NoFrame)
    sa.setWidget(widget)
    return sa


class NumberBox(QSpinBox):
    """A compact number field. The mouse wheel only changes it once it has been clicked into, so scrolling a tab
    with the wheel can never alter a value by accident (the wheel then scrolls the page instead)."""

    def __init__(self):
        super().__init__()
        self.setFocusPolicy(Qt.StrongFocus)      # clicking or tabbing focuses it, hovering/scrolling does not
        self.setMinimumWidth(90)
        self.setMaximumWidth(130)

    def wheelEvent(self, e):
        if self.hasFocus():
            super().wheelEvent(e)
        else:
            e.ignore()


def spin(lo, hi, step=1, suffix=""):
    s = NumberBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    if suffix:
        s.setSuffix(suffix)
    return s


class BaseTab(QWidget):
    changed = Signal()
    reloadAll = Signal()      # ask the main window to refresh every tab (a tab changed values that other tabs show)

    def __init__(self):
        super().__init__()
        self.t = None
        self._loading = False

    def load(self, theme):
        self.t = theme
        self._loading = True
        try:
            self._fill()
        finally:
            self._loading = False

    def _fill(self):
        pass

    def touch(self):
        if not self._loading and self.t is not None:
            self.changed.emit()


# ------------------------------------------------------------------ Info ----------------

class InfoTab(BaseTab):
    def __init__(self):
        super().__init__()
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setSpacing(12)

        box = QGroupBox("About your theme")
        form = QFormLayout(box)
        form.setVerticalSpacing(8)
        self.name = QLineEdit()
        self.author = QLineEdit()
        self.desc = QPlainTextEdit()
        self.desc.setFixedHeight(80)
        self.version = QLineEdit()
        form.addRow("Theme name", labeled(self.name, "Shown in the game's Mods list and in the theme's settings window."))
        form.addRow("Author", labeled(self.author, "Your name. It is also added to the Credits automatically."))
        form.addRow("Description", self.desc)
        form.addRow("Version", labeled(self.version, "Raise it when you publish an update (1.0.0, 1.1.0 ...)."))
        lay.addWidget(box)

        self.poster = ImagePicker("Poster", "256x256. Left empty, it is made from your first background.", (256, 256), (50, 50))
        self.icon = ImagePicker("Icon", "Small mod icon. Left empty, it is made from your first background.", None, (50, 50))
        pics = CollapsibleSection("Poster and icon (optional - made for you if left empty)")
        pics.add(self.poster)
        pics.add(self.icon)
        lay.addWidget(pics)

        adv = CollapsibleSection("Advanced - you normally don't need to touch this")
        af = QFormLayout()
        af.setVerticalSpacing(8)
        self.theme_id = QLineEdit()
        self.prefix = QLineEdit()
        self.mod_id = QLabel()
        self.vmin = QLineEdit()
        af.addRow("File prefix", labeled(self.prefix,
                  "A short tag put in front of every file and sound this theme creates (for example MMT_Background_1.png), "
                  "so two themes never overwrite each other's files. 2-10 letters/digits. It is made from the theme name "
                  "for you; change it only if you want a specific one."))
        af.addRow("Theme ID", labeled(self.theme_id,
                  "The internal name and the folder name inside your Workshop folder. Letters and digits only. "
                  "Also made from the theme name."))
        af.addRow("Mod ID", labeled(self.mod_id, "Theme ID + \"B42\". This is the id the game uses for the mod."))
        af.addRow("Minimum game version", labeled(self.vmin, "Lowest Build 42 version the theme works on."))
        adv.add(af)
        lay.addWidget(adv)
        lay.addStretch(1)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scrolled(body))

        self.name.textEdited.connect(self._name)
        self.theme_id.textEdited.connect(self._id)
        self.prefix.textEdited.connect(self._prefix)
        self.author.textEdited.connect(lambda s: self._set("author", s))
        self.version.textEdited.connect(lambda s: self._set("mod_version", s))
        self.vmin.textEdited.connect(lambda s: self._set("version_min", s))
        self.desc.textChanged.connect(lambda: self._set("description", self.desc.toPlainText()))
        self.poster.changed.connect(lambda p: self._set("poster", p))
        self.icon.changed.connect(lambda p: self._set("icon", p))

    def _set(self, attr, v):
        if self.t is None or self._loading:
            return
        setattr(self.t, attr, v)
        self.touch()

    def _name(self, s):
        self.t.name = s
        if self.t.auto_ids:
            self.t.theme_id = slug(s)
            self.t.prefix = auto_prefix(s)
            self.theme_id.setText(self.t.theme_id)
            self.prefix.setText(self.t.prefix)
            self.mod_id.setText(self.t.mod_id)
        self.touch()

    def _id(self, s):
        self.t.auto_ids = False
        self.t.theme_id = s
        self.mod_id.setText(self.t.mod_id)
        self.touch()

    def _prefix(self, s):
        self.t.auto_ids = False
        self.t.prefix = s
        self.touch()

    def _fill(self):
        t = self.t
        self.name.setText(t.name)
        self.theme_id.setText(t.theme_id)
        self.prefix.setText(t.prefix)
        self.mod_id.setText(t.mod_id)
        self.author.setText(t.author)
        self.version.setText(t.mod_version)
        self.vmin.setText(t.version_min)
        self.desc.setPlainText(t.description)
        self.poster.set_path(t.poster)
        self.icon.set_path(t.icon)


# ------------------------------------------------------------------ Backgrounds ---------

class DropList(QListWidget):
    filesDropped = Signal(list)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            self.filesDropped.emit([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])
            e.acceptProposedAction()
        else:
            super().dropEvent(e)


class BackgroundsTab(BaseTab):
    def __init__(self):
        super().__init__()
        self._icons = {}
        lay = QVBoxLayout(self)
        lay.addWidget(note("Background images shown as a slideshow behind the main menu (PNG recommended; other formats are "
                           "converted to PNG when saving). 1920x1080 or larger. Drop files here, then use the buttons to reorder."))
        self.list = DropList()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(QSize(176, 99))
        self.list.setGridSize(QSize(196, 130))
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setDragDropMode(QAbstractItemView.DropOnly)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setAcceptDrops(True)
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        for text, fn in (("Add images…", self._add_dialog), ("Remove", self._remove),
                         ("◀ Move left", lambda: self._move(-1)), ("Move right ▶", lambda: self._move(1))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        box = QGroupBox("Slideshow")
        form = QFormLayout(box)
        form.setVerticalSpacing(8)
        self.hold = spin(500, 600000, 500, " ms")
        self.instant = QCheckBox("Change images instantly (no animation at all)")
        self.trans = spin(0, 5000, 50, " ms")
        self.style = QComboBox()
        for k, v in TRANSITIONS:
            self.style.addItem(v, k)
        self.seamless = QCheckBox("Seamless Background Slides (the slide styles push the old Image out as the new one arrives, with no black between)")
        self.drift = QCheckBox("Slowly drift sideways while an image is shown")
        self.drift_px = spin(0, 500, 5, " px")
        self.zoom = QCheckBox("Slowly zoom in and out while an Image is shown")
        self.zoom_pct = spin(1, 50, 1, " %")
        self.image_scale = spin(100, 150, 1, " %")
        form.addRow("Time each image stays", self.hold)
        form.addRow(self.instant)
        form.addRow("Animation time", labeled(self.trans, "How long the old image takes to leave, and the new one to arrive."))
        form.addRow("Animation style", labeled(self.style, "Players can still change the style in the theme's settings window."))
        form.addRow(self.seamless)
        form.addRow(self.drift)
        form.addRow("Drift distance", labeled(self.drift_px, "In pixels, at 1080p."))
        form.addRow(self.zoom)
        form.addRow("Zoom amount", labeled(self.zoom_pct, "How much bigger the Image gets at the middle of its time on screen."))
        form.addRow("Image scale", labeled(self.image_scale, "Draws every Image this much bigger than the screen and crops it, which gives Drift, Zoom and the slide room to move without showing an edge. 100% fits the screen exactly."))
        lay.addWidget(box)
        self.list.filesDropped.connect(self._add_files)
        self.hold.valueChanged.connect(lambda v: self._set("hold_ms", v))
        self.trans.valueChanged.connect(lambda v: self._set("transition_ms", v))
        self.style.currentIndexChanged.connect(lambda: self._set("transition_style", self.style.currentData()))
        self.seamless.toggled.connect(lambda v: self._set("seamless_slide", v))
        self.drift.toggled.connect(lambda v: (self._set("drift", v), self._sync()))
        self.drift_px.valueChanged.connect(lambda v: self._set("drift_px", v))
        self.zoom.toggled.connect(lambda v: (self._set("zoom", v), self._sync()))
        self.zoom_pct.valueChanged.connect(lambda v: self._set("zoom_pct", v))
        self.image_scale.valueChanged.connect(lambda v: self._set("image_scale", v))
        self.instant.toggled.connect(lambda v: (self._set("no_transition", v), self._sync()))

    def _sync(self):
        inst = self.instant.isChecked()
        self.trans.setEnabled(not inst)
        self.style.setEnabled(not inst)
        self.drift_px.setEnabled(self.drift.isChecked())
        self.zoom_pct.setEnabled(self.zoom.isChecked())

    def _set(self, a, v):
        if self.t is None or self._loading:
            return
        setattr(self.t, a, v)
        self.touch()

    def _icon(self, p):
        if p not in self._icons:
            self._icons[p] = QIcon(make_thumb(p, 176, 99))
        return self._icons[p]

    def _refresh(self, select=None):
        self.list.clear()
        for i, p in enumerate(self.t.backgrounds):
            it = QListWidgetItem(self._icon(p), f"{i + 1}. {Path(p).name}")
            it.setData(Qt.UserRole, p)
            it.setToolTip(p)
            self.list.addItem(it)
        for r in (select or []):
            if 0 <= r < self.list.count():
                self.list.item(r).setSelected(True)

    def _fill(self):
        t = self.t
        self.hold.setValue(t.hold_ms)
        self.trans.setValue(t.transition_ms)
        self.style.setCurrentIndex(max(0, self.style.findData(t.transition_style)))
        self.seamless.setChecked(t.seamless_slide)
        self.drift.setChecked(t.drift)
        self.drift_px.setValue(t.drift_px)
        self.zoom.setChecked(t.zoom)
        self.zoom_pct.setValue(t.zoom_pct)
        self.image_scale.setValue(t.image_scale)
        self.instant.setChecked(t.no_transition)
        self._sync()
        self._refresh()

    def _add_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Add background images", "", IMG_FILTER)
        self._add_files(files)

    def _add_files(self, files):
        exts = (".png", ".jpg", ".jpeg", ".bmp", ".tga", ".webp")
        good = [f for f in files if f.lower().endswith(exts)]
        if good:
            self.t.backgrounds.extend(good)
            self._refresh()
            self.touch()

    def _rows(self):
        return sorted(self.list.row(i) for i in self.list.selectedItems())

    def _remove(self):
        rows = self._rows()
        for r in reversed(rows):
            del self.t.backgrounds[r]
        self._refresh()
        self.touch()

    def _move(self, d):
        rows = self._rows()
        if not rows:
            return
        b = self.t.backgrounds
        if d < 0 and rows[0] == 0 or d > 0 and rows[-1] == len(b) - 1:
            return
        order = rows if d < 0 else reversed(rows)
        for r in order:
            b[r + d], b[r] = b[r], b[r + d]
        self._refresh([r + d for r in rows])
        self.touch()


# ------------------------------------------------------------------ Music ---------------

class MusicTab(BaseTab):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addWidget(note("Menu music. Only Ogg files (.ogg) are supported. The length is read from the file automatically; "
                           "MTF needs it to move on to the next track."))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Title (shown to the player)", "Length (ms)", "File"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        for text, fn in (("Add .ogg…", self._add), ("Remove", self._remove), ("▲ Up", lambda: self._move(-1)),
                         ("▼ Down", lambda: self._move(1))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.repeat = QCheckBox("Play ONE track per menu visit and repeat it (no playlist)")
        lay.addWidget(self.repeat)
        vf = QFormLayout()
        self.vol = spin(0, 100, 5, " %")
        vf.addRow("Starting volume", labeled(self.vol, "The volume players start with. They can change it in the theme's settings window."))
        lay.addLayout(vf)
        self.vol.valueChanged.connect(self._vol)
        self.repeat.toggled.connect(self._rep)
        self.table.itemChanged.connect(self._item)

    def _rep(self, v):
        if self.t is not None and not self._loading:
            self.t.repeat_one = v
            self.touch()

    def _vol(self, v):
        if self.t is not None and not self._loading:
            self.t.music_volume = v
            self.touch()

    def _fill(self):
        self.repeat.setChecked(self.t.repeat_one)
        self.vol.setValue(self.t.music_volume)
        self._refresh()

    def _refresh(self, select=None):
        self._loading = True
        self.table.setRowCount(0)
        for tr in self.t.tracks:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(tr.title))
            self.table.setItem(r, 1, QTableWidgetItem(str(tr.length_ms)))
            f = QTableWidgetItem(Path(tr.path).name)
            f.setFlags(f.flags() & ~Qt.ItemIsEditable)
            f.setToolTip(tr.path)
            self.table.setItem(r, 2, f)
        if select is not None and 0 <= select < self.table.rowCount():
            self.table.selectRow(select)
        self._loading = False

    def _item(self, it):
        if self._loading or self.t is None:
            return
        tr = self.t.tracks[it.row()]
        if it.column() == 0:
            tr.title = it.text()
        elif it.column() == 1:
            try:
                tr.length_ms = max(0, int(it.text()))
            except ValueError:
                self._loading = True
                it.setText(str(tr.length_ms))
                self._loading = False
        self.touch()

    def _add(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Add music (Ogg)", "", "Audio (*.ogg *.mp3 *.wav *.flac);;All files (*)")
        bad = []
        for f in files:
            if not f.lower().endswith(".ogg"):
                bad.append(f"{Path(f).name}: not an .ogg file (convert it to Ogg Vorbis first)")
                continue
            try:
                info = read_ogg_info(f)
            except (ValueError, OSError) as e:
                bad.append(f"{Path(f).name}: {e}")
                continue
            title = Path(f).stem.replace("_", " ").strip()
            self.t.tracks.append(Track(f, title, info["duration_ms"]))
        if bad:
            QMessageBox.warning(self, "Some files were skipped", "\n".join(bad))
        self._refresh()
        self.touch()

    def _remove(self):
        r = self.table.currentRow()
        if r >= 0:
            del self.t.tracks[r]
            self._refresh()
            self.touch()

    def _move(self, d):
        r = self.table.currentRow()
        n = r + d
        if r < 0 or not 0 <= n < len(self.t.tracks):
            return
        tr = self.t.tracks
        tr[r], tr[n] = tr[n], tr[r]
        self._refresh(n)
        self.touch()


# ------------------------------------------------------------------ Video ---------------

class VideoTab(BaseTab):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addWidget(note("Optional looping video background (needs game Build 42.22 or later; older builds show the still image). "
                           "Videos must be Bink 1 (.bik) without sound inside; put the sound in a separate .ogg. "
                           "Convert videos with RAD Video Tools (radgametools.com/bnkdown.htm)."))
        top = QFormLayout()
        self.mode = QComboBox()
        for k, v in (("random", "Random: one clip per menu visit, looped"), ("order", "Order: clips chained in list order"),
                     ("shuffle", "Shuffle: clips chained in random order")):
            self.mode.addItem(v, k)
        self.bgmode = QComboBox()
        self.bgmode.addItem("Images", "images")
        self.bgmode.addItem("Video", "video")
        top.addRow("Playback mode", self.mode)
        top.addRow("Default background (when both exist)", self.bgmode)
        self.vvol = spin(0, 100, 5, " %")
        top.addRow("Starting video sound volume", labeled(self.vvol, "Players can change it in the theme's settings window."))
        lay.addLayout(top)
        self.list = QListWidget()
        self.list.setMaximumHeight(110)
        lay.addWidget(self.list)
        row = QHBoxLayout()
        for text, fn in (("Add clip", self._add), ("Remove", self._remove), ("▲ Up", lambda: self._move(-1)),
                         ("▼ Down", lambda: self._move(1))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

        self.box = QGroupBox("Selected clip")
        f = QFormLayout(self.box)
        self.video = FilePicker("Choose Bink video", "Bink video (*.bik)")
        self.still = FilePicker("Choose still image", IMG_FILTER)
        self.sound = FilePicker("Choose sound (Ogg)", OGG_FILTER)
        self.w = spin(1, 16384)
        self.h = spin(1, 16384)
        self.length = spin(0, 36000000, 100, " ms")
        self.vol = spin(0, 100, 5, " %")
        self.rv = QCheckBox("Restart the video when the next clip is the same video")
        self.rs = QCheckBox("Restart the sound when the next clip uses the same sound")
        f.addRow("Video (.bik)", self.video)
        f.addRow("Still image", self.still)
        f.addRow("Sound (.ogg)", self.sound)
        size = QHBoxLayout()
        size.addWidget(self.w)
        size.addWidget(QLabel("x"))
        size.addWidget(self.h)
        size.addStretch(1)
        f.addRow("Video size", size)
        f.addRow("Clip length", self.length)
        f.addRow("Sound volume", self.vol)
        f.addRow(self.rv)
        f.addRow(self.rs)
        f.addRow(note("The still image is shown when the video can't play (Video Effects off, older builds). "
                      "Left empty, your first background is used. Size and length are read from the files when possible; "
                      "the length is only needed for Order / Shuffle."))
        lay.addWidget(self.box)
        lay.addStretch(1)

        self.mode.currentIndexChanged.connect(lambda: self._top("video_mode", self.mode.currentData()))
        self.bgmode.currentIndexChanged.connect(lambda: self._top("default_bg_mode", self.bgmode.currentData()))
        self.vvol.valueChanged.connect(lambda v: self._top("video_volume", v))
        self.list.currentRowChanged.connect(self._select)
        self.video.changed.connect(self._video)
        self.still.changed.connect(lambda p: self._clip("still", p))
        self.sound.changed.connect(self._sound)
        self.w.valueChanged.connect(lambda v: self._clip("width", v))
        self.h.valueChanged.connect(lambda v: self._clip("height", v))
        self.length.valueChanged.connect(lambda v: self._clip("length_ms", v))
        self.vol.valueChanged.connect(lambda v: self._clip("sound_volume", v))
        self.rv.toggled.connect(lambda v: self._clip("restart_video", v))
        self.rs.toggled.connect(lambda v: self._clip("restart_sound", v))

    def _top(self, a, v):
        if self.t is not None and not self._loading:
            setattr(self.t, a, v)
            self.touch()

    def _cur(self):
        r = self.list.currentRow()
        return self.t.clips[r] if self.t and 0 <= r < len(self.t.clips) else None

    def _clip(self, a, v):
        c = self._cur()
        if c is not None and not self._loading:
            setattr(c, a, v)
            self.touch()

    def _fill(self):
        self.mode.setCurrentIndex(max(0, self.mode.findData(self.t.video_mode)))
        self.bgmode.setCurrentIndex(max(0, self.bgmode.findData(self.t.default_bg_mode)))
        self.vvol.setValue(self.t.video_volume)
        self._refresh(0)

    def _refresh(self, select=0):
        was = self._loading
        self._loading = True
        self.list.clear()
        for i, c in enumerate(self.t.clips, 1):
            self.list.addItem(f"{i}. {Path(c.video).name if c.video else '(no video yet)'}")
        self._loading = was
        if self.t.clips:
            self.list.setCurrentRow(min(select, len(self.t.clips) - 1))
        else:
            self._select(-1)

    def _select(self, row):
        c = self._cur()
        self.box.setEnabled(c is not None)
        was = self._loading
        self._loading = True
        c = c or Clip()
        self.video.set_path(c.video)
        self.still.set_path(c.still)
        self.sound.set_path(c.sound)
        self.w.setValue(c.width)
        self.h.setValue(c.height)
        self.length.setValue(c.length_ms)
        self.vol.setValue(c.sound_volume)
        self.rv.setChecked(c.restart_video)
        self.rs.setChecked(c.restart_sound)
        self._loading = was

    def _add(self):
        self.t.clips.append(Clip())
        self._refresh(len(self.t.clips) - 1)
        self.touch()

    def _remove(self):
        r = self.list.currentRow()
        if r >= 0:
            del self.t.clips[r]
            self._refresh(r)
            self.touch()

    def _move(self, d):
        r, n = self.list.currentRow(), self.list.currentRow() + d
        if r < 0 or not 0 <= n < len(self.t.clips):
            return
        c = self.t.clips
        c[r], c[n] = c[n], c[r]
        self._refresh(n)
        self.touch()

    def _video(self, p):
        c = self._cur()
        if c is None:
            return
        c.video = p
        if p:
            try:
                info = read_bik_info(p)
                c.width, c.height = info["width"], info["height"]
                if not c.sound:
                    c.length_ms = info["duration_ms"]
            except (ValueError, OSError) as e:
                QMessageBox.warning(self, "Video", f"{e}\nOnly Bink (.bik) videos work in Project Zomboid.")
                c.video = ""
            auto_still = Path(p + ".png")
            if c.video and not c.still and auto_still.is_file():
                c.still = str(auto_still)
        self._refresh(self.list.currentRow())
        self.touch()

    def _sound(self, p):
        c = self._cur()
        if c is None:
            return
        if p:
            try:
                if not p.lower().endswith(".ogg"):
                    raise ValueError("Sound must be an .ogg file")
                c.length_ms = read_ogg_info(p)["duration_ms"]
            except (ValueError, OSError) as e:
                QMessageBox.warning(self, "Sound", str(e))
                p = ""
        c.sound = p
        self._select(self.list.currentRow())
        self.touch()


# ------------------------------------------------------------------ Menu & logo --------

class LayoutTab(BaseTab):
    def __init__(self):
        super().__init__()
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setSpacing(12)

        # --- button layouts
        box = QGroupBox("Button layouts offered to the player")
        v = QVBoxLayout(box)
        self.checks = {}
        for lid, (label, _, _) in LAYOUTS.items():
            cb = QCheckBox(label)
            cb.toggled.connect(self._layouts)
            self.checks[lid] = cb
            v.addWidget(cb)
        row = QHBoxLayout()
        row.addWidget(QLabel("Layout shown first"))
        self.default = QComboBox()
        self.default.currentIndexChanged.connect(self._default)
        row.addWidget(self.default, 1)
        v.addLayout(row)
        v.addWidget(note("Two or more layouts give the player a 'Button Layout' choice. With none, the vanilla list is kept."))
        lay.addWidget(box)

        # --- logo
        lbox = QGroupBox("Logo")
        lv = QVBoxLayout(lbox)
        self.logo = ImagePicker("Main menu logo", "Transparent PNG, 697x450.", (697, 450), (88, 57))
        lv.addWidget(self.logo)
        lf = QFormLayout()
        lf.setVerticalSpacing(8)
        self.scale = spin(10, 400, 5, " %")
        self.place = QComboBox()
        self.place.addItem("Vanilla position (top left)", "default")
        self.place.addItem("Choose the position", "custom")
        self.lx = spin(-2000, 4000, 5, " px")
        self.ly = spin(-2000, 4000, 5, " px")
        xy = QHBoxLayout()
        xy.addWidget(QLabel("X"))
        xy.addWidget(self.lx)
        xy.addWidget(QLabel("Y"))
        xy.addWidget(self.ly)
        xy.addStretch(1)
        self.xy_row = QWidget()
        self.xy_row.setLayout(xy)
        xy.setContentsMargins(0, 0, 0, 0)
        lf.addRow("Size", labeled(self.scale, "100% = the picture's own size. Needs a logo picture. The preview on the right shows it."))
        lf.addRow("Position", self.place)
        lf.addRow("", self.xy_row)
        cen = QHBoxLayout()
        self.center_x = QPushButton("Centre horizontally")
        self.center_all = QPushButton("Centre on screen")
        cen.addWidget(self.center_x)
        cen.addWidget(self.center_all)
        cen.addStretch(1)
        self.center_row = QWidget()
        cen.setContentsMargins(0, 0, 0, 0)
        self.center_row.setLayout(cen)
        lf.addRow("", labeled(self.center_row, "Turn on 'Grid' in the preview to see the screen centre and your logo's centre."))
        lv.addLayout(lf)
        alt = CollapsibleSection("Alternative logo (optional)")
        self.logo_alt = ImagePicker("Alternative logo", "Adds a 'Logo' choice to the theme settings.", (697, 450), (88, 57))
        alt.add(self.logo_alt)
        lv.addWidget(alt)
        lay.addWidget(lbox)

        # --- animations
        abox = QGroupBox("Menu animations")
        av = QVBoxLayout(abox)
        self.logo_fade = spin(0, 10000, 100, " ms")
        af = QFormLayout()
        af.addRow("Logo fade-in time", labeled(self.logo_fade, "How long the logo takes to appear. 0 = it appears instantly."))
        av.addLayout(af)
        self.logo_slide = QCheckBox("Logo also slides down a little while it fades in")
        self.btn_instant = QCheckBox("Menu buttons appear instantly (no fade-in)")
        av.addWidget(self.logo_slide)
        av.addWidget(self.btn_instant)
        av.addWidget(note("The change between background images has its own switch in the Backgrounds tab."))
        self.all_off = QPushButton("Turn off ALL animations")
        self.all_off.setToolTip("Instant background changes, no drift, logo and buttons appear at once.")
        av.addWidget(self.all_off, 0, Qt.AlignLeft)
        lay.addWidget(abox)

        # --- vanilla list highlight
        hbox = QGroupBox("Hover highlight of the Zomboid list")
        hv = QVBoxLayout(hbox)
        hv.addWidget(note("Only used by the 'Zomboid (vanilla list)' layout: how a button looks when the mouse is over it. "
                          "Click the look you want."))
        self.hl = HighlightGallery()
        hv.addWidget(self.hl)
        hrow = QHBoxLayout()
        self.hl_tint_on = QCheckBox("Colour the highlight")
        self.hl_tint_btn = QPushButton()
        hrow.addWidget(self.hl_tint_on)
        hrow.addWidget(self.hl_tint_btn)
        hrow.addStretch(1)
        hv.addLayout(hrow)
        hv.addWidget(note("\"Caption bar\" uses the caption art from the Cards tab. To change its colour, turn on "
                          "\"Colour the highlight\". With no caption art, the tool makes a plain bar for you."))
        lay.addWidget(hbox)

        # --- optional art
        extra = CollapsibleSection("More art (optional)")
        self.opt = ImagePicker("Settings button icon", "240x240. MTF has its own if empty.", (240, 240), (50, 50))
        self.strip = ImagePicker("Strip bar art", "1920x128. Used by Strip and Carousel layouts.", (1920, 128), (120, 8))
        self.ah = ImagePicker("Horizontal arrow", "128x128, facing left.", (128, 128), (50, 50))
        self.av = ImagePicker("Vertical arrow", "256x64, facing up.", (256, 64), (64, 16))
        for p in (self.opt, self.strip, self.ah, self.av):
            extra.add(p)
        lay.addWidget(extra)
        lay.addStretch(1)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scrolled(body))

        for w, a in ((self.logo, "logo"), (self.logo_alt, "logo_alt"), (self.opt, "options_icon"),
                     (self.strip, "strip"), (self.ah, "arrow_h"), (self.av, "arrow_v")):
            w.changed.connect(lambda p, a=a: self._set(a, p))
        self.logo.changed.connect(lambda _: self._sync())
        self.scale.valueChanged.connect(lambda v: self._set("logo_scale", v))
        self.place.currentIndexChanged.connect(self._place)
        self.lx.valueChanged.connect(lambda v: self._set("logo_x", v))
        self.ly.valueChanged.connect(lambda v: self._set("logo_y", v))
        self.logo_fade.valueChanged.connect(lambda v: (self._set("logo_fade_ms", v), self._sync()))
        self.logo_slide.toggled.connect(lambda v: self._set("logo_slide", v))
        self.btn_instant.toggled.connect(lambda v: self._set("buttons_instant", v))
        self.all_off.clicked.connect(self._all_off)
        self.center_x.clicked.connect(lambda: self._centre(False))
        self.center_all.clicked.connect(lambda: self._centre(True))
        self.hl.chosen.connect(self._highlight)
        self.hl_tint_on.toggled.connect(lambda v: (self._set("highlight_tint_on", v), self._hl_states()))
        self.hl_tint_btn.clicked.connect(self._pick_hl_color)

    def _set(self, a, v):
        if self.t is None or self._loading:
            return
        setattr(self.t, a, v)
        self.touch()

    def _hl_states(self):
        t = self.t
        if t is None:
            return
        caption = t.list_highlight == "caption"
        self.hl_tint_on.setEnabled(caption)
        self.hl_tint_btn.setEnabled(caption and t.highlight_tint_on)
        self.hl_tint_btn.setText(t.highlight_tint)
        c = QColor(t.highlight_tint)
        fg = "#000" if c.lightness() > 140 else "#fff"
        self.hl_tint_btn.setStyleSheet(f"background:{t.highlight_tint}; color:{fg}; border:1px solid #888;")
        self.hl.update()

    def _pick_hl_color(self):
        c = QColorDialog.getColor(QColor(self.t.highlight_tint), self, "Highlight colour")
        if c.isValid():
            self.t.highlight_tint = c.name()
            self._hl_states()
            self.touch()

    def _sync(self):
        t = self.t
        self.scale.setEnabled(bool(t and t.logo))
        self.xy_row.setEnabled(self.place.currentData() == "custom")
        self.center_row.setEnabled(bool(t and t.logo))
        self.logo_slide.setEnabled(self.logo_fade.value() > 0)

    def _place(self):
        self._set("logo_place", self.place.currentData())
        self._sync()

    def _highlight(self, mode):
        if self.t is None:
            return
        self.t.list_highlight = mode
        self._hl_states()
        self.touch()

    def _centre(self, both):
        t = self.t
        nw, nh = natural_size(t.logo) if t else (0, 0)
        if not nw or not nh:
            QMessageBox.information(self, "Centre logo", "Choose a logo picture first.")
            return
        ww, hh = nw * t.logo_scale / 100.0, nh * t.logo_scale / 100.0
        t.logo_place = "custom"
        t.logo_x = int(round((1920 - ww) / 2))
        if both:
            t.logo_y = int(round((1080 - hh) / 2))
        self.load(t)
        self.changed.emit()

    def _all_off(self):
        t = self.t
        if t is None:
            return
        t.no_transition = True
        t.drift = False
        t.logo_fade_ms = 0
        t.logo_slide = False
        t.buttons_instant = True
        self.reloadAll.emit()      # refresh the other tabs (Backgrounds) too
        self.changed.emit()

    def _fill(self):
        t = self.t
        for lid, cb in self.checks.items():
            cb.setChecked(lid in t.layouts)
        self._fill_default()
        self.logo.set_path(t.logo)
        self.logo_alt.set_path(t.logo_alt)
        self.scale.setValue(t.logo_scale)
        self.place.setCurrentIndex(max(0, self.place.findData(t.logo_place)))
        self.lx.setValue(t.logo_x)
        self.ly.setValue(t.logo_y)
        self.logo_fade.setValue(t.logo_fade_ms)
        self.logo_slide.setChecked(t.logo_slide)
        self.btn_instant.setChecked(t.buttons_instant)
        self.opt.set_path(t.options_icon)
        self.strip.set_path(t.strip)
        self.ah.set_path(t.arrow_h)
        self.av.set_path(t.arrow_v)
        self.hl.set_theme(t)
        self.hl_tint_on.setChecked(t.highlight_tint_on)
        self._hl_states()
        self._sync()

    def _fill_default(self):
        was = self._loading
        self._loading = True
        self.default.clear()
        for lid in LAYOUTS:
            if lid in self.t.layouts:
                self.default.addItem(LAYOUTS[lid][0], lid)
        self.default.setEnabled(self.default.count() > 0)
        i = self.default.findData(self.t.default_layout)
        self.default.setCurrentIndex(i if i >= 0 else 0)
        self._loading = was

    def _layouts(self):
        if self.t is None or self._loading:
            return
        self.t.layouts = [lid for lid, cb in self.checks.items() if cb.isChecked()]
        self._fill_default()
        if self.default.count():
            self.t.default_layout = self.default.currentData()
        self.touch()

    def _default(self):
        if self.t is None or self._loading or not self.default.count():
            return
        self.t.default_layout = self.default.currentData()
        self.touch()

    def showEvent(self, e):
        super().showEvent(e)
        self.hl.update()      # the caption art may have changed in the Cards tab


# ------------------------------------------------------------------ Cards ---------------

class CardsTab(BaseTab):
    def __init__(self):
        super().__init__()
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setSpacing(12)
        lay.addWidget(note("Cards are used by the two card layouts: every main-menu button becomes a card with a picture "
                           "and a name bar."))
        self.default = ImagePicker("Card picture", "1820x1024. Used by every card that has no picture of its own.", (1820, 1024), (96, 54))
        lay.addWidget(self.default)

        cbox = QGroupBox("Name bar of the cards")
        cv = QVBoxLayout(cbox)
        self.caption = ImagePicker("Name bar art (optional)", "1024x128, white art. Without it the bar is plain black, or your colour when 'Colour the bar' is on.", (1024, 128), (128, 16))
        cv.addWidget(self.caption)
        row = QHBoxLayout()
        self.tint_on = QCheckBox("Colour the bar")
        self.tint_btn = QPushButton()
        self.tint_btn.setFixedWidth(90)
        self.tint_btn.setToolTip("Click to choose the colour")
        row.addWidget(self.tint_on)
        row.addWidget(self.tint_btn)
        row.addStretch(1)
        cv.addLayout(row)
        cv.addWidget(note("This is how a card's name bar will look:"))
        self.sample = CaptionSample()
        cv.addWidget(self.sample, 0, Qt.AlignLeft)
        lay.addWidget(cbox)

        per = CollapsibleSection("A different picture for each button (optional)")
        self.pickers = {}
        for bid in BUTTON_IDS:
            p = ImagePicker(bid, "", (1820, 1024), (96, 54))
            p.changed.connect(lambda path, b=bid: self._card(b, path))
            self.pickers[bid] = p
            per.add(p)
        lay.addWidget(per)
        lay.addStretch(1)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scrolled(body))
        self.default.changed.connect(lambda p: self._set("card_default", p))
        self.caption.changed.connect(lambda p: self._set("caption", p))
        self.tint_on.toggled.connect(lambda v: self._set("caption_tint_on", v))
        self.tint_btn.clicked.connect(self._pick_color)

    def _set(self, a, v):
        if self.t is None or self._loading:
            return
        setattr(self.t, a, v)
        self.sample.update()
        self._paint_btn()
        self.touch()

    def _card(self, bid, path):
        if self.t is None or self._loading:
            return
        if path:
            self.t.cards[bid] = path
        else:
            self.t.cards.pop(bid, None)
        self.touch()

    def _paint_btn(self):
        if self.t is None:
            return
        self.tint_btn.setText(self.t.caption_tint)
        self.tint_btn.setEnabled(self.t.caption_tint_on)
        c = QColor(self.t.caption_tint)
        fg = "#000" if c.lightness() > 140 else "#fff"
        self.tint_btn.setStyleSheet(f"background:{self.t.caption_tint}; color:{fg}; border:1px solid #888;")

    def _pick_color(self):
        c = QColorDialog.getColor(QColor(self.t.caption_tint), self, "Name bar colour")
        if c.isValid():
            self.t.caption_tint = c.name()
            self._paint_btn()
            self.sample.update()
            self.touch()

    def _fill(self):
        t = self.t
        self.default.set_path(t.card_default)
        self.caption.set_path(t.caption)
        self.tint_on.setChecked(t.caption_tint_on)
        self._paint_btn()
        for bid, p in self.pickers.items():
            p.set_path(t.cards.get(bid, ""))
        self.sample.set_theme(t)


# ------------------------------------------------------------------ Font ---------------

class FontTab(BaseTab):
    def __init__(self):
        super().__init__()
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setSpacing(12)
        lay.addWidget(note("Give the main-menu buttons your own font. Pick a free font from Google Fonts (previewed here) "
                           "or use a .ttf / .otf from your computer. The tool converts it into the format the game "
                           "needs (5 sizes) when you press Save && Build. A project made with the web builder can carry several fonts; "
                           "this tool edits the first one and keeps the others."))
        box = QGroupBox("Menu button font")
        v = QVBoxLayout(box)
        self.name_lbl = QLabel()
        v.addWidget(self.name_lbl)
        self.sample = InkLabel("CONTINUE   NEW GAME   MULTIPLAYER", 90)
        v.addWidget(self.sample)
        row = QHBoxLayout()
        self.browse = QPushButton("Browse free fonts...")
        self.file = QPushButton("Choose a font file...")
        self.remove = QPushButton("Remove font")
        for b in (self.browse, self.file, self.remove):
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        form = QFormLayout()
        self.scale = spin(50, 200, 5, " %")
        form.addRow("Size adjustment", labeled(self.scale, "Every font looks bigger or smaller at the same size. "
                                                           "Change this until it fits your menu (see the preview)."))
        v.addLayout(form)
        lay.addWidget(box)
        lay.addWidget(note("Good to know: the font is added to the Button Font choice in Menu Theme Settings, so players can "
                           "also use it in other menu themes. It covers Latin letters; languages such as Russian, Chinese, "
                           "Japanese or Korean keep the game's font. Check that the font's licence lets you publish it - "
                           "fonts from Google Fonts do."))
        lay.addStretch(1)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scrolled(body))
        self.browse.clicked.connect(self._browse)
        self.file.clicked.connect(self._file)
        self.remove.clicked.connect(lambda: self._apply("", "", ""))
        self.scale.valueChanged.connect(self._scale)

    def _scale(self, v):
        if self.t is not None and not self._loading:
            self.t.font_scale = v
            self._refresh()
            self.touch()

    def _browse(self):
        t = self.t
        before = (t.font_file, t.font_name, t.font_license)
        # open where you were: the font you have now, or the last one you looked at
        dlg = FontBrowser(self, current=t.font_name if t.font_file else "")
        dlg.previewed.connect(lambda path, fam, lic: self._apply(path, fam, lic))     # live in the main preview
        if dlg.exec() == QDialog.Accepted and dlg.result_font:
            r = dlg.result_font
            self._apply(r["path"], r["family"], r["license"])
        else:
            self._apply(*before)          # cancelled: put back what you had

    def _file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Choose a font", "", "Fonts (*.ttf *.otf)")
        if not f:
            return
        fam = family_for(f)
        if not fam:
            QMessageBox.warning(self, "Font", "This file could not be read as a font.")
            return
        self._apply(f, fam, "")

    def _apply(self, path, name, lic):
        if self.t is None:
            return
        self.t.font_file, self.t.font_name, self.t.font_license = path, name, lic
        self._refresh()
        self.touch()

    def _refresh(self):
        t = self.t
        fam = family_for(t.font_file) if t and t.font_file else ""
        self.remove.setEnabled(bool(fam))
        if fam:
            self.sample.set_sample(family=fam, px=max(8, int(30 * t.font_scale / 100)))
            self.name_lbl.setText(f"Font: <b>{t.font_name or fam}</b>")
        else:
            self.sample.set_sample(family="", px=30)
            self.name_lbl.setText("No custom font - the game's own button font is used.")

    def _fill(self):
        self.scale.setValue(self.t.font_scale)
        self._refresh()


# ------------------------------------------------------------------ Credits ------------

CREDIT_ROLES = ["Theme", "Music", "Fonts", "Art", "Video", "Sounds", "Special thanks"]


class CreditsTab(BaseTab):
    def __init__(self):
        super().__init__()
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setSpacing(10)
        lay.addWidget(note("Credits are shown in the theme's Settings window. Each line has a role (Music, Fonts...) "
                           "and a name; lines with the same role are grouped for you - no # needed."))
        self.auto = QCheckBox("Add my author name automatically")
        lay.addWidget(self.auto)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Role", "Name / text"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 150)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setMinimumHeight(170)
        lay.addWidget(self.table, 1)

        row = QHBoxLayout()
        self.add_btn = QPushButton("Add credit ▾")
        menu = QMenu(self.add_btn)
        for role in CREDIT_ROLES:
            menu.addAction(role).triggered.connect(lambda checked=False, r=role: self._add(r))
        menu.addSeparator()
        menu.addAction("Other role...").triggered.connect(lambda checked=False: self._add(""))
        self.add_btn.setMenu(menu)
        rm = QPushButton("Remove")
        up = QPushButton("▲")
        dn = QPushButton("▼")
        up.setFixedWidth(34)
        dn.setFixedWidth(34)
        rm.clicked.connect(self._remove)
        up.clicked.connect(lambda: self._move(-1))
        dn.clicked.connect(lambda: self._move(1))
        for w in (self.add_btn, rm, up, dn):
            row.addWidget(w)
        row.addStretch(1)
        lay.addLayout(row)

        self.auto_music = QCheckBox("Auto generate for Music (the titles of my tracks)")
        self.auto_fonts = QCheckBox("Auto generate for Fonts (the names of my fonts)")
        lay.addWidget(self.auto_music)
        lay.addWidget(self.auto_fonts)

        lay.addWidget(QLabel("<b>How it will look in the game</b>"))
        self.result = QPlainTextEdit()
        self.result.setReadOnly(True)
        self.result.setMaximumHeight(130)
        lay.addWidget(self.result)

        lay.addWidget(QLabel("<b>About this mod</b> (optional)"))
        lay.addWidget(note("A short text shown at the very bottom of the Credits tab."))
        self.about = QPlainTextEdit()
        self.about.setMaximumHeight(80)
        lay.addWidget(self.about)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scrolled(body))

        self.auto.toggled.connect(self._auto)
        self.auto_music.toggled.connect(lambda v: self._auto_flag("auto_music", v))
        self.auto_fonts.toggled.connect(lambda v: self._auto_flag("auto_fonts", v))
        self.table.itemChanged.connect(lambda _: self._commit())
        self.about.textChanged.connect(lambda: self._plain("about", self.about.toPlainText()))

    def _plain(self, a, v):
        if self.t is None or self._loading:
            return
        setattr(self.t, a, v)
        self.touch()

    def _auto(self, v):
        if self.t is None or self._loading:
            return
        self.t.auto_credits = v
        self._update_result()
        self.touch()

    def _auto_flag(self, name, v):
        if self.t is None or self._loading:
            return
        setattr(self.t, name, v)
        self._update_result()
        self._show_autos()
        self.touch()

    def _has_role(self, name):
        for role, _ in self._table_rows():
            if role.strip().rstrip(":").strip().lower() == name:
                return True
        return False

    def _show_autos(self):
        if self.t is None:
            return
        self.auto_music.setVisible(self._has_role("music") or bool(self.t.auto_music))
        self.auto_fonts.setVisible(self._has_role("fonts") or bool(self.t.auto_fonts))

    # table <-> text
    def _rows_from_text(self):
        rows = []
        for g in parse_credits(self.t.credits_text):
            role = g["header"].strip().rstrip(":").strip()
            if g["rows"]:
                rows.extend((role, r) for r in g["rows"])
        return rows

    def _fill_table(self, rows, select=None):
        was = self._loading
        self._loading = True
        self.table.setRowCount(0)
        for role, text in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(role))
            self.table.setItem(r, 1, QTableWidgetItem(text))
        if select is not None and 0 <= select < self.table.rowCount():
            self.table.selectRow(select)
        self._loading = was

    def _table_rows(self):
        out = []
        for r in range(self.table.rowCount()):
            a, b = self.table.item(r, 0), self.table.item(r, 1)
            out.append((a.text() if a else "", b.text() if b else ""))
        return out

    def _commit(self):
        if self.t is None or self._loading:
            return
        order, groups = [], {}
        for role, text in self._table_rows():
            text = text.strip().lstrip("#").strip()
            if not text:
                continue
            role = role.strip().rstrip(":").strip() or "Other"
            key = role.lower()
            if key not in groups:
                groups[key] = (role, [])
                order.append(key)
            groups[key][1].append(text)
        lines = []
        for k in order:
            role, items = groups[k]
            lines.append("# " + role)
            lines.extend(items)
        self.t.credits_text = "\n".join(lines)
        self._update_result()
        self._show_autos()
        self.touch()

    def _add(self, role):
        r = self.table.rowCount()
        self._loading = True
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(role))
        self.table.setItem(r, 1, QTableWidgetItem(""))
        self._loading = False
        self.table.setCurrentCell(r, 1 if role else 0)
        self.table.editItem(self.table.item(r, 1 if role else 0))
        self._show_autos()

    def _remove(self):
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)
            self._commit()

    def _move(self, d):
        r = self.table.currentRow()
        n = r + d
        if r < 0 or not 0 <= n < self.table.rowCount():
            return
        rows = self._table_rows()
        rows[r], rows[n] = rows[n], rows[r]
        self._fill_table(rows, n)
        self._commit()

    def _update_result(self):
        if self.t is None:
            return
        lines = []
        for g in credit_screen_groups(self.t):
            if g["header"]:
                lines.append(g["header"])
            lines.extend("    " + r for r in g["rows"])
            lines.append("")
        self.result.setPlainText("\n".join(lines).strip() or "(no credits yet)")

    def _fill(self):
        t = self.t
        was = self._loading
        self._loading = True
        self.auto.setChecked(t.auto_credits)
        self.auto_music.setChecked(t.auto_music)
        self.auto_fonts.setChecked(t.auto_fonts)
        self._loading = was
        self._fill_table(self._rows_from_text())
        self._show_autos()
        self.about.setPlainText(t.about)
        self._update_result()

    def showEvent(self, e):
        super().showEvent(e)
        self._update_result()      # author / music may have changed in other tabs
