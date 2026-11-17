from pathlib import Path

from PySide6.QtCore import Qt, Signal, QPointF
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPixmap, QImageReader
from PySide6.QtWidgets import (QFileDialog, QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
                               QFrame)

IMG_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.tga *.webp);;All files (*)"


def make_thumb(path, w, h):
    pm = QPixmap(str(path))
    if pm.isNull():
        return QPixmap()
    return pm.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)


class ImagePicker(QFrame):
    """A thumbnail + file chooser for one image. expected=(w, h) shows a hint if the size differs."""
    changed = Signal(str)

    def __init__(self, title, hint="", expected=None, thumb=(88, 50), parent=None):
        super().__init__(parent)
        self._path = ""
        self._expected = expected
        self._thumb = thumb
        self.setFrameShape(QFrame.StyledPanel)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        self.thumb = QLabel()
        self.thumb.setFixedSize(*thumb)
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setStyleSheet("background:#15171a; border:1px solid #3a3f46;")
        lay.addWidget(self.thumb)
        col = QVBoxLayout()
        col.setSpacing(1)
        self.title = QLabel(f"<b>{title}</b>")
        self.hint = QLabel(hint)
        self.hint.setStyleSheet("color:#9aa0a8;")
        self.hint.setWordWrap(True)
        self.info = QLabel("")
        self.info.setStyleSheet("color:#9aa0a8;")
        col.addWidget(self.title)
        if hint:
            col.addWidget(self.hint)
        col.addWidget(self.info)
        lay.addLayout(col, 1)
        self.btn = QPushButton("Choose…")
        self.clear = QPushButton("Clear")
        self.btn.clicked.connect(self._choose)
        self.clear.clicked.connect(lambda: self.set_path("", emit=True))
        lay.addWidget(self.btn)
        lay.addWidget(self.clear)
        self.set_path("")

    def _choose(self):
        start = str(Path(self._path).parent) if self._path else ""
        f, _ = QFileDialog.getOpenFileName(self, "Choose image", start, IMG_FILTER)
        if f:
            self.set_path(f, emit=True)

    def path(self):
        return self._path

    def set_path(self, p, emit=False):
        self._path = p or ""
        self.clear.setEnabled(bool(self._path))
        if self._path:
            pm = make_thumb(self._path, *self._thumb)
            self.thumb.setPixmap(pm)
            if pm.isNull():
                self.thumb.setText("?")
            size = QImageReader(self._path).size()
            txt = f"{Path(self._path).name}  ({size.width()}x{size.height()})"
            if self._expected and size.isValid() and (size.width(), size.height()) != tuple(self._expected):
                txt += f"  —  recommended {self._expected[0]}x{self._expected[1]}"
                self.info.setStyleSheet("color:#e0a040;")
            else:
                self.info.setStyleSheet("color:#9aa0a8;")
            self.info.setText(txt)
        else:
            self.thumb.setPixmap(QPixmap())
            self.thumb.setText("none")
            self.info.setText("")
        if emit:
            self.changed.emit(self._path)


def draw_centered_ink(p, rect, text):
    """Draw text centred by the letters' real shape, not by the font's line metrics (some fonts reserve a huge
    empty space above/below the letters, which would push the text away from the centre)."""
    br = QFontMetricsF(p.font()).tightBoundingRect(text)
    x = rect.x() + (rect.width() - br.width()) / 2 - br.x()
    y = rect.y() + (rect.height() - br.height()) / 2 - br.y()
    p.drawText(QPointF(x, y), text)


def draw_fit_ink(p, rect, text, family, px, min_px=9):
    """Like draw_centered_ink, shrinking the font until the text fits the width."""
    f = QFont(family) if family else QFont()
    while True:
        f.setPixelSize(px)
        p.setFont(f)
        if px <= min_px or QFontMetricsF(f).tightBoundingRect(text).width() <= rect.width():
            break
        px -= 1
    draw_centered_ink(p, rect, text)


class InkLabel(QWidget):
    """A box that shows one line of text centred by its letters (used for font samples)."""

    def __init__(self, text="", height=90, parent=None):
        super().__init__(parent)
        self._text = text
        self._family = ""
        self._px = 30
        self.setFixedHeight(height)

    def set_sample(self, text=None, family=None, px=None):
        if text is not None:
            self._text = text
        if family is not None:
            self._family = family
        if px is not None:
            self._px = px
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        p.fillRect(self.rect(), QColor("#0d0e10"))
        p.setPen(QColor("white"))
        draw_fit_ink(p, self.rect().adjusted(10, 4, -10, -4), self._text, self._family, self._px)
        p.setPen(QColor("#3a3f46"))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))


def note(text):
    l = QLabel(text)
    l.setWordWrap(True)
    l.setStyleSheet("color:#9aa0a8;")
    return l


def labeled(widget, text):
    """A form field with a small explanation line under it."""
    box = QWidget()
    v = QVBoxLayout(box)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(2)
    v.addWidget(widget)
    h = QLabel(text)
    h.setWordWrap(True)
    h.setStyleSheet("color:#8c929a; font-size:11px;")
    v.addWidget(h)
    return box


class CollapsibleSection(QGroupBox):
    """A titled box that is always open (kept under this name so the tabs don't change)."""

    def __init__(self, title, expanded=True, parent=None):
        super().__init__(title, parent)
        self.body_layout = QVBoxLayout(self)
        self.body_layout.setSpacing(8)

    def add(self, item):
        if isinstance(item, QWidget):
            self.body_layout.addWidget(item)
        else:
            self.body_layout.addLayout(item)


class FilePicker(QWidget):
    """Plain file chooser (line + Browse + Clear)."""
    changed = Signal(str)

    def __init__(self, title, file_filter, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QLineEdit
        self._filter, self._title, self._path = file_filter, title, ""
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit()
        self.edit.setReadOnly(True)
        self.edit.setPlaceholderText("none")
        b = QPushButton("Choose…")
        c = QPushButton("Clear")
        b.clicked.connect(self._choose)
        c.clicked.connect(lambda: self.set_path("", True))
        lay.addWidget(self.edit, 1)
        lay.addWidget(b)
        lay.addWidget(c)

    def _choose(self):
        f, _ = QFileDialog.getOpenFileName(self, self._title, str(Path(self._path).parent) if self._path else "", self._filter)
        if f:
            self.set_path(f, True)

    def path(self):
        return self._path

    def set_path(self, p, emit=False):
        self._path = p or ""
        self.edit.setText(Path(self._path).name if self._path else "")
        self.edit.setToolTip(self._path)
        if emit:
            self.changed.emit(self._path)
