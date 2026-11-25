"""Turns a .ttf/.otf into the bitmap font files Project Zomboid reads (AngelCode .fnt + .png atlas).

Menu Theme Framework draws a theme's button fonts itself, so the files are named after the theme
(media/fonts/<Prefix>/<Prefix>_<Font>.fnt, listed in `menu.fonts`) and cannot collide with another theme's font.
They come in five size tiers (the folder itself and 1x..4x, one per 'Font Size' option of the game).
The sizes below are the ones the Menu Theme Template uses.
"""
import math
from pathlib import Path

from PySide6.QtCore import Qt, QPointF, QPoint
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetricsF, QImage, QPainter

TIERS = [("", 18), ("1x", 24), ("2x", 27), ("3x", 34), ("4x", 37)]
ATLAS_SIZES = (256, 512, 1024, 2048)


class FontError(Exception):
    pass


def charset():
    ids = list(range(32, 127)) + list(range(161, 384))
    ids += [8211, 8212, 8216, 8217, 8218, 8220, 8221, 8222, 8224, 8225, 8226, 8230, 8240, 8249, 8250, 8364, 8482]
    return ids


_FAM = {}


def family_for(path):
    """Register a font file with Qt and return its family name ('' if it can't be read)."""
    if not path:
        return ""
    if path not in _FAM:
        fid = QFontDatabase.addApplicationFont(str(path))
        fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
        _FAM[path] = fams[0] if fams else ""
    return _FAM[path]


# ---- pure helpers (no Qt) ---------------------------------------------------------------

def pack(glyphs, spacing=1, sizes=ATLAS_SIZES):
    """Shelf-pack glyph rectangles. Sets g['x'], g['y'] and returns the (square) atlas size."""
    items = [g for g in glyphs if g["w"] and g["h"]]
    order = sorted(items, key=lambda g: (-g["h"], -g["w"], g["id"]))
    for size in sizes:
        x = y = spacing
        shelf = 0
        ok = True
        for g in order:
            if x + g["w"] + spacing > size:
                x, y, shelf = spacing, y + shelf + spacing, 0
            if y + g["h"] + spacing > size or g["w"] + 2 * spacing > size:
                ok = False
                break
            g["x"], g["y"] = x, y
            x += g["w"] + spacing
            shelf = max(shelf, g["h"])
        if ok:
            for g in glyphs:
                g.setdefault("x", 0)
                g.setdefault("y", 0)
            return size
    raise FontError("The font is too large to fit in a texture. Lower 'Size adjustment' and try again.")


def normalize_lines(glyphs, ascent):
    """Some fonts declare a huge ascent/descent. Take the line height from the letters actually drawn instead.
    Glyph 'yo' values are measured from a line top where the baseline sits at 'ascent'. Returns (line_h, base)."""
    ink = [g for g in glyphs if g["h"]]
    if not ink:
        raise FontError("The font has no visible letters.")
    top = min(g["yo"] for g in ink)
    bottom = max(g["yo"] + g["h"] for g in ink)
    line_h = bottom - top + 1
    for g in glyphs:
        if g["h"]:
            g["yo"] -= top
    base = max(1, min(line_h, int(round(ascent - top))))
    return line_h, base


def fnt_text(face, px, line_h, base, atlas, page_file, glyphs):
    L = [f'info face="{face}" size={px} bold=0 italic=0 charset="" unicode=1 stretchH=100 smooth=1 aa=1 '
         f'padding=0,0,0,0 spacing=1,1 outline=0',
         f'common lineHeight={line_h} base={base} scaleW={atlas} scaleH={atlas} pages=1 packed=0 alphaChnl=0 '
         f'redChnl=4 greenChnl=4 blueChnl=4',
         f'page id=0 file="{page_file}"',
         f'chars count={len(glyphs)}']
    for g in sorted(glyphs, key=lambda g: g["id"]):
        L.append(f'char id={g["id"]:<4} x={g["x"]:<4} y={g["y"]:<4} width={g["w"]:<4} height={g["h"]:<4} '
                 f'xoffset={g["xo"]:<4} yoffset={g["yo"]:<4} xadvance={g["adv"]:<4} page=0  chnl=15')
    return "\r\n".join(L) + "\r\n"


# ---- Qt part ----------------------------------------------------------------------------

def _alpha_bbox(img):
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    buf = bytes(img.constBits())
    top = bottom = None
    left, right = w, -1
    for y in range(h):
        row = buf[y * bpl: y * bpl + w * 4][3::4]       # the alpha byte of every ARGB32 pixel
        if row.strip(b"\x00"):
            if top is None:
                top = y
            bottom = y
            left = min(left, len(row) - len(row.lstrip(b"\x00")))
            right = max(right, len(row.rstrip(b"\x00")) - 1)
    return None if top is None else (left, top, right, bottom)


def _render_tier(family, px):
    font = QFont(family)
    font.setPixelSize(px)
    font.setStyleStrategy(QFont.PreferAntialias)
    fm = QFontMetricsF(font)
    ascent = fm.ascent()
    line_h = int(math.ceil(fm.height()))
    pad = max(2, px // 4)
    pad_y = pad + max(0, int(math.ceil(fm.height() - px * 2)))      # room for fonts that overflow their line
    glyphs = []
    for cid in charset():
        ch = chr(cid)
        try:
            if cid != 32 and not fm.inFontUcs4(cid):
                continue
        except (AttributeError, TypeError):
            pass
        adv = max(1, int(round(fm.horizontalAdvance(ch))))
        if cid == 32:
            glyphs.append(dict(id=32, w=0, h=0, xo=0, yo=0, adv=adv, img=None))
            continue
        img = QImage(adv + 2 * pad + 2, line_h + 2 * pad_y, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setFont(font)
        p.setPen(QColor(255, 255, 255))
        p.drawText(QPointF(pad, pad_y + ascent), ch)
        p.end()
        box = _alpha_bbox(img)
        if box is None:
            glyphs.append(dict(id=cid, w=0, h=0, xo=0, yo=0, adv=adv, img=None))
            continue
        x0, y0, x1, y1 = box
        glyphs.append(dict(id=cid, w=x1 - x0 + 1, h=y1 - y0 + 1, xo=x0 - pad, yo=y0 - pad_y, adv=adv,
                           img=img.copy(x0, y0, x1 - x0 + 1, y1 - y0 + 1)))
    line_h, base = normalize_lines(glyphs, ascent)
    return glyphs, line_h, base


def generate_menu_font(font_path, out_root, scale_percent=100, file_stem="MenuFont"):
    """Write <file_stem>.fnt + <file_stem>_0.png for the five size tiers into out_root (…/media/fonts/<Prefix>)."""
    family = family_for(font_path)
    if not family:
        raise FontError(f"Could not read the font file: {font_path}")
    out_root = Path(out_root)
    for tier, size in TIERS:
        px = max(6, int(round(size * scale_percent / 100.0)))
        glyphs, line_h, base = _render_tier(family, px)
        if sum(1 for g in glyphs if 33 <= g["id"] <= 126) < 60:
            raise FontError(f"'{family}' has too few Latin letters to be used as a menu font.")
        atlas_size = pack(glyphs)
        atlas = QImage(atlas_size, atlas_size, QImage.Format_ARGB32)
        atlas.fill(Qt.transparent)
        p = QPainter(atlas)
        for g in glyphs:
            if g["img"] is not None:
                p.drawImage(QPoint(g["x"], g["y"]), g["img"])
        p.end()
        folder = out_root / tier if tier else out_root
        folder.mkdir(parents=True, exist_ok=True)
        if not atlas.save(str(folder / f"{file_stem}_0.png"), "PNG"):
            raise FontError(f"Could not write the font texture in {folder}")
        (folder / f"{file_stem}.fnt").write_text(
            fnt_text(family, px, line_h, base, atlas_size, f"{file_stem}_0.png", glyphs),
            encoding="utf-8", newline="")
    return family
