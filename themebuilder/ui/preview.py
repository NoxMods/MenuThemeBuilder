import os

from PySide6.QtCore import Qt, QRectF, QTimer, QPointF, QVariantAnimation, Signal, QSize
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QImageReader, QLinearGradient, QPainter, QPixmap, QPen,
                           QBrush, QTransform)
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..fontgen import family_for
from ..model import LAYOUTS
from .widgets import note, draw_centered_ink

LABELS = ["CONTINUE", "SOLO", "MULTIPLAYER", "MODS", "OPTIONS"]
STYLE_NAMES = {"slide": "Horizontal slide", "slidedown": "Vertical slide", "fade": "Fade"}


# ------------------------------------------------------------------ small helpers ------

_PM = {}
_SIZES = {}
_TINT = {}


def load_pm(path, max_w=0):
    """Cached QPixmap (re-read when the file changes). None if missing/unreadable."""
    if not path:
        return None
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        return None
    key = (path, stamp, max_w)
    pm = _PM.get(key)
    if pm is None:
        if len(_PM) > 80:
            _PM.clear()
        pm = QPixmap(path)
        if not pm.isNull() and max_w and pm.width() > max_w:
            pm = pm.scaledToWidth(max_w, Qt.SmoothTransformation)
        _PM[key] = pm
    return None if pm.isNull() else pm


def natural_size(path):
    """(w, h) of the image file as it is on disk, without loading the pixels."""
    if not path:
        return 0, 0
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        return 0, 0
    key = (path, stamp)
    if key not in _SIZES:
        s = QImageReader(path).size()
        _SIZES[key] = (s.width(), s.height()) if s.isValid() else (0, 0)
    return _SIZES[key]


def tinted(pm, color, key):
    """White art multiplied by a colour, keeping the art's transparency (what MTF does with captionTint)."""
    k = (key, color.rgba(), pm.width())
    out = _TINT.get(k)
    if out is None:
        if len(_TINT) > 40:
            _TINT.clear()
        out = QPixmap(pm.size())
        out.fill(Qt.transparent)
        q = QPainter(out)
        q.drawPixmap(0, 0, pm)
        q.setCompositionMode(QPainter.CompositionMode_Multiply)
        q.fillRect(out.rect(), color)
        q.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        q.drawPixmap(0, 0, pm)
        q.end()
        _TINT[k] = out
    return out


def caption_pixmap(t):
    """The caption bar art with the theme's tint applied, or None when the theme has no caption art."""
    pm = load_pm(t.caption, 1024)
    if pm is None:
        return None
    color = QColor(t.caption_tint) if t.caption_tint_on else QColor("white")
    return tinted(pm, color, t.caption)


def draw_caption_bar(p, rect, t):
    art = caption_pixmap(t)
    if art is not None:
        p.drawPixmap(rect, art, QRectF(art.rect()))
    else:
        p.fillRect(rect, QColor(t.caption_tint) if t.caption_tint_on else QColor(0, 0, 0, 200))


def draw_list_highlight(p, box, t, mode):
    """How the vanilla list highlights a hovered button for each 'list_highlight' mode. Returns the text colour."""
    if mode == "white":
        p.fillRect(box, QColor("white"))
        return QColor("black")
    if mode == "caption":
        art = load_pm(t.caption, 1024)
        if art is not None:
            if t.highlight_tint_on:
                art = tinted(art, QColor(t.highlight_tint), t.caption + "|highlight")
            p.drawPixmap(box, art, QRectF(art.rect()))   # without a colour MTF draws the art as it is
            return QColor("white")
        if t.highlight_tint_on:
            p.fillRect(box, QColor(t.highlight_tint))    # the builder makes a plain white bar for MTF to tint
            return QColor("white")
    p.fillRect(box, QColor(77, 77, 77, 128))
    return QColor("white")


# ------------------------------------------------------------------ main canvas --------

class Canvas(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(360, 203)
        self.t = None
        self.index = 0
        self.prev_index = 0
        self.anim = 1.0        # 1 = idle, 0..1 = a slideshow change is running
        self.layout_id = ""
        self.grid = False
        self._logo = None      # (rect, x, y, w, h) of the logo in the last paint, 1080p units

    def _rect(self):
        w, h = self.width(), self.height()
        if w / h > 16 / 9:
            rw, rh = h * 16 / 9, h
        else:
            rw, rh = w, w * 9 / 16
        return QRectF((w - rw) / 2, (h - rh) / 2, rw, rh)

    def _cover(self, p, r, pm, ox=0.0, oy=0.0):
        k = max(r.width() / pm.width(), r.height() / pm.height())
        w, h = pm.width() * k, pm.height() * k
        p.drawPixmap(QRectF(r.x() + (r.width() - w) / 2 + ox, r.y() + (r.height() - h) / 2 + oy, w, h),
                     pm, QRectF(pm.rect()))

    def _bg(self, i):
        t = self.t
        if t.backgrounds:
            return load_pm(t.backgrounds[i % len(t.backgrounds)], 960)
        if t.clips:
            return load_pm(t.clips[0].still, 960)
        return None

    def _draw_background(self, p, r):
        t = self.t
        cur = self._bg(self.index)
        if cur is None:
            g = QLinearGradient(r.topLeft(), r.bottomRight())
            g.setColorAt(0, QColor("#1b1e24"))
            g.setColorAt(1, QColor("#0a0b0d"))
            p.fillRect(r, QBrush(g))
            p.setPen(QColor("#555"))
            p.drawText(r, Qt.AlignCenter, "No background yet")
            return
        if self.anim >= 1.0 or len(t.backgrounds) < 2:
            self._cover(p, r, cur)
            return
        style = t.transition_style
        if self.anim < 0.5:                      # the old image leaves
            u = self.anim * 2
            old = self._bg(self.prev_index)
            if old is None:
                return
            if style == "slide":
                self._cover(p, r, old, -r.width() * u, 0)
            elif style == "slidedown":
                self._cover(p, r, old, 0, r.height() * u)
            else:
                self._cover(p, r, old)
                p.fillRect(r, QColor(0, 0, 0, int(255 * u)))
        else:                                    # the new image arrives
            u = (self.anim - 0.5) * 2
            if style == "slide":
                self._cover(p, r, cur, r.width() * (1 - u), 0)
            elif style == "slidedown":
                self._cover(p, r, cur, 0, -r.height() * (1 - u))
            else:
                self._cover(p, r, cur)
                p.fillRect(r, QColor(0, 0, 0, int(255 * (1 - u))))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        p.fillRect(self.rect(), QColor("#0d0e10"))
        r = self._rect()
        p.setClipRect(r)
        p.fillRect(r, QColor("black"))
        t = self.t
        if t is None:
            return
        s = r.width() / 1920.0
        self._draw_background(p, r)

        # logo: its real proportions, the chosen size and the chosen position
        self._logo = None
        nw, nh = natural_size(t.logo)
        logo = load_pm(t.logo, 1000)
        if logo is not None and nw > 0 and nh > 0:
            hh = nh * max(1, t.logo_scale) / 100.0
            ww = hh * nw / nh
            x, y = (t.logo_x, t.logo_y) if t.logo_place == "custom" else (50, 50)
            if self.layout_id == "left":
                x, y = 1920 - 50 - ww, 50
            lrect = QRectF(r.x() + x * s, r.y() + y * s, ww * s, hh * s)
            p.drawPixmap(lrect, logo, QRectF(logo.rect()))
            self._logo = (lrect, x, y, ww, hh)

        font = QFont()
        fam = family_for(t.font_file) if t.font_file else ""
        if fam:
            font.setFamily(fam)
        font.setBold(not fam)
        font.setPixelSize(max(6, int(26 * s * (t.font_scale / 100.0 if fam else 1))))
        p.setFont(font)
        lid = self.layout_id
        if lid == "rail":
            fm = QFontMetricsF(font)
            pad = 20 * s
            for i, name in enumerate(LABELS):
                x = r.x() + 90 * s
                y = r.y() + r.height() * 0.52 + i * 52 * s
                col = QColor("white")
                if i == 1:     # pretend the mouse is over the 2nd button
                    row_h = fm.height() + 6 * s
                    box = QRectF(x - pad, y - fm.ascent() - 3 * s, fm.horizontalAdvance("MULTIPLAYER") + 2 * pad, row_h)
                    col = draw_list_highlight(p, box, t, t.list_highlight)
                p.setPen(col)
                p.drawText(QPointF(x, y), name)
        elif lid == "left":
            fm = QFontMetricsF(font)
            pad = 20 * s
            count = len(LABELS)
            for i, name in enumerate(LABELS):
                x = r.x() + 78 * s
                y = r.y() + r.height() * 0.5 + (i - (count - 1) / 2.0) * 52 * s + fm.ascent() / 2
                col = QColor("white")
                if i == 1:
                    row_h = fm.height() + 6 * s
                    box = QRectF(x - pad, y - fm.ascent() - 3 * s, fm.horizontalAdvance("MULTIPLAYER") + 2 * pad, row_h)
                    col = draw_list_highlight(p, box, t, t.list_highlight)
                p.setPen(col)
                p.drawText(QPointF(x, y), name)
        elif lid in ("cards_wide", "cards_vertical"):
            card = load_pm(t.card_default, 480)
            for i, name in enumerate(LABELS[1:]):
                if lid == "cards_wide":
                    cw, ch = (560 if i == 0 else 300) * s, 360 * s
                    x = r.x() + 60 * s + sum(((560 if j == 0 else 300) + 24) for j in range(i)) * s
                    y = r.bottom() - ch - 70 * s
                else:
                    cw, ch = (460 if i == 0 else 380) * s, (170 if i == 0 else 110) * s
                    x = r.x() + 60 * s
                    y = r.y() + r.height() * 0.50 + sum(((170 if j == 0 else 110) + 16) for j in range(i)) * s
                box = QRectF(x, y, cw, ch)
                img = load_pm(t.cards.get(name, ""), 480) or card
                if img:
                    p.drawPixmap(box, img, QRectF(img.rect()))
                else:
                    p.fillRect(box, QColor(40, 44, 50, 220))
                bar = QRectF(box.x(), box.bottom() - 34 * s, box.width(), 34 * s)
                draw_caption_bar(p, bar, t)
                p.setPen(QColor("white"))
                draw_centered_ink(p, bar, name)
                if i == 0:
                    p.setPen(QPen(QColor("white"), max(1, 2 * s)))
                    p.setBrush(Qt.NoBrush)
                    p.drawRect(box)
        elif lid in ("strip", "carousel"):
            bar = QRectF(r.x(), r.bottom() - 110 * s, r.width(), 90 * s)
            st = load_pm(t.strip, 960)
            if st:
                p.drawPixmap(bar, st, QRectF(st.rect()))
            else:
                p.fillRect(bar, QColor(0, 0, 0, 215))
            p.setPen(QColor("white"))
            if lid == "strip":
                for i, name in enumerate(LABELS):
                    draw_centered_ink(p, QRectF(r.x() + (60 + i * 300) * s, bar.y(), 280 * s, bar.height()), name)
            else:
                arrow = load_pm(t.arrow_h, 128)
                if arrow:
                    side = 64 * s
                    left = QRectF(bar.center().x() - 260 * s - side / 2, bar.center().y() - side / 2, side, side)
                    right = QRectF(bar.center().x() + 260 * s - side / 2, bar.center().y() - side / 2, side, side)
                    p.drawPixmap(left, arrow, QRectF(arrow.rect()))
                    flipped = arrow.transformed(QTransform().scale(-1, 1))
                    p.drawPixmap(right, flipped, QRectF(flipped.rect()))
                    draw_centered_ink(p, bar, "SOLO")
                else:
                    draw_centered_ink(p, bar, "◀    SOLO    ▶")
        if self.grid:
            self._draw_grid(p, r)
        p.setClipping(False)
        p.setPen(QPen(QColor("#3a3f46")))
        p.drawRect(r.adjusted(0, 0, -1, -1))

    def _draw_grid(self, p, r):
        """Four big quadrants with a strong centre cross, a faint quarter grid, and the logo's box and centre."""
        cx, cy = r.center().x(), r.center().y()
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 60), 1, Qt.DashLine))
        for f in (0.25, 0.75):
            xx, yy = r.x() + r.width() * f, r.y() + r.height() * f
            p.drawLine(QPointF(xx, r.y()), QPointF(xx, r.bottom()))
            p.drawLine(QPointF(r.x(), yy), QPointF(r.right(), yy))
        p.setPen(QPen(QColor(255, 70, 70, 235), 2))
        p.drawLine(QPointF(cx, r.y()), QPointF(cx, r.bottom()))
        p.drawLine(QPointF(r.x(), cy), QPointF(r.right(), cy))
        if self._logo:
            lrect, x, y, ww, hh = self._logo
            p.setPen(QPen(QColor(80, 200, 255, 235), 1))
            p.drawRect(lrect)
            c = lrect.center()
            p.drawLine(QPointF(c.x() - 6, c.y()), QPointF(c.x() + 6, c.y()))
            p.drawLine(QPointF(c.x(), c.y() - 6), QPointF(c.x(), c.y() + 6))
            f = QFont()
            f.setPixelSize(12)
            p.setFont(f)
            p.drawText(QPointF(lrect.x() + 4, lrect.bottom() + 14),
                       f"logo X {x:.0f}  Y {y:.0f}  |  centre {x + ww / 2:.0f}, {y + hh / 2:.0f}  (screen centre 960, 540)")


class PreviewPanel(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        head = QHBoxLayout()
        head.addWidget(QLabel("<b>Preview</b>"))
        head.addStretch(1)
        self.grid = QCheckBox("Grid")
        self.grid.setToolTip("Show a centring grid: big centre cross, quarter lines and the logo's own box and centre")
        self.grid.toggled.connect(self._grid)
        head.addWidget(self.grid)
        self.combo = QComboBox()
        self.combo.currentIndexChanged.connect(self._layout_changed)
        head.addWidget(QLabel("Layout"))
        head.addWidget(self.combo)
        prev, nxt = QPushButton("◀"), QPushButton("▶")
        prev.setFixedWidth(30)
        nxt.setFixedWidth(30)
        prev.setToolTip("Previous background")
        nxt.setToolTip("Next background")
        prev.clicked.connect(lambda: self._step(-1))
        nxt.clicked.connect(lambda: self._step(1))
        head.addWidget(prev)
        head.addWidget(nxt)
        lay.addLayout(head)
        self.canvas = Canvas()
        lay.addWidget(self.canvas, 1)
        self.info = QLabel()
        self.info.setStyleSheet("color:#c3c8cf;")
        lay.addWidget(self.info)
        lay.addWidget(note("Approximate preview. The real positions, sizes and animations are drawn by Menu Theme "
                           "Framework in-game."))
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self._step(1))
        self.timer.start(3500)
        self._anim = QVariantAnimation(self)
        self._anim.valueChanged.connect(self._on_anim)

    def _grid(self, on):
        self.canvas.grid = on
        self.canvas.update()

    def _on_anim(self, v):
        self.canvas.anim = float(v)
        self.canvas.update()

    def _step(self, d):
        c = self.canvas
        t = c.t
        if not t or len(t.backgrounds) < 2:
            return
        c.prev_index = c.index
        c.index = (c.index + d) % len(t.backgrounds)
        self._anim.stop()
        ms = 0 if t.no_transition else int(t.transition_ms) * 2     # the old image leaves, then the new one arrives
        if ms <= 0:
            c.anim = 1.0
            c.update()
            return
        c.anim = 0.0
        self._anim.setDuration(min(max(ms, 150), 4000))
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def _layout_changed(self):
        self.canvas.layout_id = self.combo.currentData() or ""
        self.canvas.update()

    def set_theme(self, t):
        self.canvas.t = t
        self.canvas.index = 0
        self.canvas.prev_index = 0
        self.canvas.anim = 1.0
        self.refresh()

    def refresh(self):
        t = self.canvas.t
        if t is None:
            return
        cur = self.combo.currentData()
        self.combo.blockSignals(True)
        self.combo.clear()
        for lid in t.layouts:
            self.combo.addItem(LAYOUTS[lid][0], lid)
        want = cur if cur in t.layouts else (t.default_layout if t.default_layout in t.layouts else None)
        i = self.combo.findData(want) if want else 0
        self.combo.setCurrentIndex(max(0, i))
        self.combo.blockSignals(False)
        self.canvas.layout_id = self.combo.currentData() or ""
        if len(t.backgrounds) == 0:
            self.info.setText("Slideshow: add a background image.")
        elif len(t.backgrounds) == 1:
            self.info.setText("Slideshow: a single image is shown still - no animation.")
        elif t.no_transition or t.transition_ms <= 0:
            self.info.setText("Slideshow: images change instantly (no animation).")
        else:
            self.info.setText(f"Slideshow: {STYLE_NAMES.get(t.transition_style, t.transition_style)}, "
                              f"{t.transition_ms} ms per half.")
        self.canvas.update()


# ------------------------------------------------------------------ small live previews -

class HighlightGallery(QWidget):
    """The three hover-highlight looks side by side. Click one to choose it."""
    chosen = Signal(str)
    MODES = (("default", "MTF default"), ("white", "Inverted Hover"), ("caption", "Caption bar"))

    def __init__(self):
        super().__init__()
        self.t = None
        self.setMinimumHeight(170)
        self.setCursor(Qt.PointingHandCursor)

    def sizeHint(self):
        return QSize(520, 170)

    def set_theme(self, t):
        self.t = t
        self.update()

    def _tiles(self):
        gap = 10
        w = (self.width() - gap * 2) / 3.0
        h = self.height() - 24
        return [QRectF(i * (w + gap), 0, w, h) for i in range(3)]

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        t = self.t
        if t is None:
            return
        font = QFont()
        font.setBold(True)
        font.setPixelSize(15)
        for (mode, label), tile in zip(self.MODES, self._tiles()):
            sel = (t.list_highlight == mode)
            p.setPen(QPen(QColor("#3d7ad6") if sel else QColor("#3a3f46"), 2 if sel else 1))
            p.setBrush(QColor("#101215"))
            p.drawRoundedRect(tile.adjusted(1, 1, -1, -1), 6, 6)
            p.setFont(font)
            fm = QFontMetricsF(font)
            row = tile.height() / 5.0
            for i, name in enumerate(("CONTINUE", "SOLO", "MULTIPLAYER", "MODS")):
                x = tile.x() + 26
                y = tile.y() + row * (i + 0.9)
                col = QColor("#dddddd")
                if i == 1:
                    box = QRectF(x - 12, y - fm.ascent() - 2, fm.horizontalAdvance("MULTIPLAYER") + 24, fm.height() + 4)
                    col = draw_list_highlight(p, box, t, mode)
                p.setPen(col)
                p.drawText(QPointF(x, y), name)
            p.setPen(QColor("white") if sel else QColor("#9aa0a8"))
            name = label + ("  ✓" if sel else "")
            if mode == "caption" and load_pm(t.caption, 1024) is None:
                name += "  (needs caption art)"
            p.setFont(QFont())
            p.drawText(QRectF(tile.x(), tile.bottom() + 4, tile.width(), 20), Qt.AlignCenter, name)

    def mousePressEvent(self, e):
        pos = e.position() if hasattr(e, "position") else e.pos()
        for (mode, _), tile in zip(self.MODES, self._tiles()):
            if tile.contains(QPointF(pos)):
                self.chosen.emit(mode)
                break


class CaptionSample(QWidget):
    """A card with its caption bar, drawn with the theme's caption art and tint."""

    def __init__(self):
        super().__init__()
        self.t = None
        self.setFixedHeight(120)
        self.setMinimumWidth(260)

    def set_theme(self, t):
        self.t = t
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        t = self.t
        if t is None:
            return
        box = QRectF(0, 0, min(self.width(), 213), 120)      # 16:9-ish card sample
        img = load_pm(t.card_default, 480)
        if img:
            k = max(box.width() / img.width(), box.height() / img.height())
            p.setClipRect(box)
            p.drawPixmap(QRectF(box.x() + (box.width() - img.width() * k) / 2,
                                box.y() + (box.height() - img.height() * k) / 2, img.width() * k, img.height() * k),
                         img, QRectF(img.rect()))
            p.setClipping(False)
        else:
            p.fillRect(box, QColor("#2b2f36"))
            p.setPen(QColor("#777"))
            p.drawText(box.adjusted(0, 0, 0, -40), Qt.AlignCenter, "card picture")
        bar = QRectF(box.x(), box.bottom() - 34, box.width(), 34)
        draw_caption_bar(p, bar, t)
        f = QFont()
        f.setBold(True)
        f.setPixelSize(15)
        p.setFont(f)
        p.setPen(QColor("white"))
        draw_centered_ink(p, bar, "SOLO")
        p.setPen(QPen(QColor("white"), 2))
        p.setBrush(Qt.NoBrush)
        p.drawRect(box.adjusted(1, 1, -1, -1))
