"""Turns a Theme into a Menu Theme Framework mod folder inside the Workshop directory."""
import json
import re
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QColor, QFont, QImage, QImageReader, QPainter

from . import APP_VERSION
from .model import (Theme, LAYOUTS, BUTTON_IDS, sanitize_stem, PROJECT_FILE, map_paths,
                    parse_credits, final_credit_groups, stamp_text)


class BuildError(Exception):
    pass


# ---------------------------------------------------------------- validation ---------

def validate(t: Theme):
    """Return (errors, warnings)."""
    errs, warns = [], []
    if not t.name.strip():
        errs.append("The Theme needs a name.")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", t.theme_id or ""):
        errs.append("Theme ID may only contain letters and digits (and must start with a letter).")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{1,9}", t.prefix or ""):
        errs.append("Prefix must be 2-10 letters/digits and start with a letter (e.g. MMT).")
    if not t.backgrounds and not t.clips:
        errs.append("Add at least one background Image or one Video clip.")

    def need(path, what):
        if path and not Path(path).is_file():
            errs.append(f"{what}: file not found ({path}).")

    for p in t.backgrounds:
        need(p, "Background")
    for tr in t.tracks:
        need(tr.path, "Music track")
        if tr.path and not tr.path.lower().endswith(".ogg"):
            errs.append(f"Music must be .ogg: {Path(tr.path).name}")
        if tr.length_ms <= 0:
            warns.append(f"Track '{tr.title}' has no length; MTF needs the real length to advance to the next track.")
    for i, c in enumerate(t.clips, 1):
        if not c.video:
            errs.append(f"Video clip {i} has no .bik file.")
        need(c.video, f"Video clip {i}")
        need(c.still, f"Video clip {i} still")
        need(c.sound, f"Video clip {i} sound")
        if c.sound and not c.sound.lower().endswith(".ogg"):
            errs.append(f"Video clip {i}: the sound must be .ogg.")
        if t.video_mode != "random" and c.length_ms <= 0:
            warns.append(f"Video clip {i}: '{t.video_mode}' mode needs the clip length (ms).")
    for i, f in enumerate(t.fonts, 1):
        if not f.file:
            errs.append(f"Font {i} has no file.")
        need(f.file, f"Font {i}")
    for a, what in (("poster", "Poster"), ("icon", "Icon"), ("logo", "Logo"), ("logo_alt", "Alternative logo"),
                    ("options_icon", "Settings icon"), ("strip", "Strip art"), ("arrow_h", "Horizontal arrow"),
                    ("arrow_v", "Vertical arrow"), ("caption", "Caption bar"), ("card_default", "Default card Image")):
        need(getattr(t, a), what)
    for k, p in t.cards.items():
        need(p, f"Card {k}")
    if t.default_layout not in t.layouts and t.layouts:
        warns.append("The default layout is not among the enabled layouts; the first enabled one will be used.")
    for p in t.backgrounds:
        r = QImageReader(p)
        s = r.size()
        if s.isValid() and (s.width() < 1920 or s.height() < 1080):
            warns.append(f"{Path(p).name} is {s.width()}x{s.height()}; 1920x1080 or larger is recommended.")
    need_pct = 100 + (int(t.drift_px) * 5 + 47) // 48
    if t.drift and int(t.drift_px) > 0 and t.backgrounds and image_scale(t) < need_pct:
        warns.append(f"Drift moves the Image {int(t.drift_px)} px, so a strip of the screen can show at its edge. Set Image scale to at least {need_pct}%.")
    return errs, warns


# ---------------------------------------------------------------- helpers ------------

def image_scale(t):
    return max(100, min(150, int(t.image_scale)))


def picture_helper():
    """drawCover cannot scale, so a scaled or zooming picture is cover-fitted here instead (through MTF's smooth drawing
    when it has it, the same call drawCover ends in)."""
    return ["local function drawPicture(ctx, img, offsetX, offsetY, zoom)",
              "\tlocal tw, th = img:getWidth(), img:getHeight()",
              "\tif tw <= 0 or th <= 0 then", "\t\treturn", "\tend",
              "\tlocal k = math.max(ctx.width / tw, ctx.height / th) * zoom",
              "\tlocal w, h = tw * k, th * k",
              "\tlocal x, y = (ctx.width - w) / 2 + offsetX, (ctx.height - h) / 2 + offsetY",
              "\tif ctx.draw and ctx.draw.smooth then", "\t\tctx.draw.smooth(img, x, y, w, h, 1, 1, 1, 1)", "\telse",
              "\t\tctx.screen:drawTextureScaled(img, x, y, w, h, 1, 1, 1, 1)", "\tend",
              "end", ""]


def seamless_lines(P, picture, zoom_on):
    """drawSeamless: the slide styles with the old picture leaving while the new one arrives, in one push, so no black shows
    between them. The push is centred on the moment the cycle changes picture, so a cycle is as long as before."""
    def draw(img, x, y, z):
        return f"drawPicture(ctx, {img}, {x}, {y}, {z})" if picture else f"ctx.drawCover({img}, 1, {x}, {y})"

    out = ["local function drawSeamless(ctx, style, count)",
           f"\tlocal T = {P}_Config.TRANSITION_MS",
           f"\tlocal cycleMs = T + {P}_Config.IMAGE_HOLD_MS + T",
           "\tlocal s = ctx.now - run.startMs + T / 2",
           "\tlocal k = math.floor(s / cycleMs)",
           "\tlocal r = s - k * cycleMs",
           "\tlocal w, h = ctx.width, ctx.height",
           f"\tlocal drift = {P}_Config.IMAGE_DRIFT and {P}_Config.DRIFT_PX * ctx.layout.uiScale or 0"]
    if picture:
        out.append(f"\tlocal scale = {P}_Config.IMAGE_SCALE / 100")
    out.append("\tlocal function pose(p)")
    if picture and zoom_on:
        out.append(f"\t\treturn -drift * p, scale * (1 + {P}_Config.IMAGE_ZOOM / 100 * (0.5 - 0.5 * math.cos(2 * math.pi * p)))")
    elif picture:
        out.append("\t\treturn -drift * p, scale")
    else:
        out.append("\t\treturn -drift * p")
    out += ["\tend",
            f"\tlocal cur = ctx.tex({P}_Config.BG_IMAGES[k % count + 1])",
            "\tif not cur then", "\t\treturn", "\tend",
            "\tif k > 0 and r < T then",
            f"\t\tlocal prev = ctx.tex({P}_Config.BG_IMAGES[(k - 1) % count + 1])",
            "\t\tif not prev then", "\t\t\treturn", "\t\tend",
            "\t\tlocal t = r / T",
            "\t\tlocal px, pz = pose(1)" if picture else "\t\tlocal px = pose(1)",
            '\t\tif style == "slide" then',
            "\t\t\t" + draw("prev", "px - w * t", "0", "pz"),
            "\t\t\t" + draw("cur", "math.max(0, w + px - w * t)", "0", "scale"),
            "\t\telse",
            "\t\t\t" + draw("prev", "px", "h * t", "pz"),
            "\t\t\t" + draw("cur", "px * (1 - t)", "-h * (1 - t)", "scale"),
            "\t\tend",
            "\telse",
            f"\t\tlocal x, z = pose(math.min(1, math.max(0, (r - T) / (cycleMs - T))))" if picture
            else "\t\tlocal x = pose(math.min(1, math.max(0, (r - T) / (cycleMs - T))))",
            "\t\t" + draw("cur", "x", "0", "z"),
            "\tend", "end", ""]
    return out


def picture_body(P, lines, zoom_on):
    out = []
    for line in lines:
        if "ctx.drawCover(img, 1, driftX" in line:
            line = line.replace("ctx.drawCover(img, 1, driftX", "drawPicture(ctx, img, driftX")[:-1] + ", zoom)"
        elif "ctx.drawCover(img, 1, " in line:
            line = line.replace("ctx.drawCover(img, 1, ", "drawPicture(ctx, img, ")[:-1] + ", scale)"
        out.append(line)
        if line.startswith("\tlocal driftX ="):
            out.append(f"\tlocal scale = {P}_Config.IMAGE_SCALE / 100")
            if zoom_on:
                out.append(f"\tlocal progress = math.min(1, math.max(0, (into - {P}_Config.TRANSITION_MS) / {P}_Config.IMAGE_HOLD_MS))")
                out.append(f"\tlocal zoom = scale * (1 + {P}_Config.IMAGE_ZOOM / 100 * (0.5 - 0.5 * math.cos(2 * math.pi * progress)))")
            else:
                out.append("\tlocal zoom = scale")
    return out


def lq(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\r", "").replace("\n", "\\n") + '"'


def one_line(s):
    """Text for a single-line slot (Lua comment, mod.info value): control characters and line breaks become spaces."""
    return re.sub(r"[\x00-\x1f\x7f]+", " ", str(s)).strip()


def _load_image(src):
    img = QImage(str(src))
    if img.isNull():
        raise BuildError(f"Could not read the Image: {src}")
    return img


def put_png(src, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = QImageReader(str(src))
    if str(src).lower().endswith(".png") and r.format().data() == b"png":
        shutil.copyfile(src, dest)
    else:
        if not _load_image(src).save(str(dest), "PNG"):
            raise BuildError(f"Could not convert to PNG: {src}")


# Needs Menu Theme Framework 1.0.3 (the field is unknown, and only logs a warning, on older versions). Set True at the MTF 1.0.3 release.
EMIT_CAPTION_UNDER_BORDER = False


def put_solid(dest: Path, w, h, color):
    """A plain one-colour PNG (the white caption bar MTF tints when the theme brings no caption art of its own)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor(color))
    if not img.save(str(dest), "PNG"):
        raise BuildError(f"Could not write {dest.name}")


def needs_caption_art(t):
    """MTF multiplies a colour into the caption art, so a coloured bar or highlight needs art to colour."""
    return not t.caption and (t.caption_tint_on or (t.list_highlight == "caption" and t.highlight_tint_on))


def put_file(src, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)


def square_from(src, size, text):
    """A square image (cover-cropped from src, or a plain placeholder)."""
    out = QImage(size, size, QImage.Format_ARGB32)
    out.fill(QColor("#23262b"))
    p = QPainter(out)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    if src and Path(src).is_file():
        img = _load_image(src)
        s = max(size / img.width(), size / img.height())
        w, h = int(img.width() * s + 0.5), int(img.height() * s + 0.5)
        p.drawImage(QRect((size - w) // 2, (size - h) // 2, w, h), img)
    else:
        f = QFont()
        f.setBold(True)
        f.setPixelSize(max(8, size // 3))
        p.setFont(f)
        p.setPen(QColor("#e8e8e8"))
        p.drawText(QRect(0, 0, size, size), Qt.AlignCenter, text[:3].upper())
    p.end()
    return out


def font_label(f):
    """The name shown in the Button Font choice: the font's own name, else the file name."""
    return one_line(f.name) or Path(f.file).stem


def font_plan(t):
    """One entry per font with the names it gets in the mod: the theme prefix keeps a file from colliding with another
    theme's font, and two fonts with the same name get a number."""
    plan, stems, ids = [], set(), set()
    for f in t.fonts:
        label = font_label(f)
        base = sanitize_stem(label)
        stem, fid, k = f"{t.prefix}_{base}", base.lower(), 2
        while stem.lower() in stems or fid in ids:
            stem, fid = f"{t.prefix}_{base}_{k}", f"{base.lower()}_{k}"
            k += 1
        stems.add(stem.lower())
        ids.add(fid)
        plan.append({"font": f, "label": label, "stem": stem, "id": fid, "key": f"IGUI_{t.prefix}_Font{len(plan) + 1}"})
    return plan


def logo_display_height(t):
    """Logo height in pixels (at 1080p) when the theme scales its logo, else 0 (= the image's own height)."""
    if not t.logo or int(t.logo_scale) == 100:
        return 0
    size = QImageReader(str(t.logo)).size()
    if not size.isValid() or size.height() <= 0:
        return 0
    return max(1, round(size.height() * int(t.logo_scale) / 100))


# ---------------------------------------------------------------- lua text -----------

def gen_config(t, a):
    P = t.prefix
    L = [f"{P}_Config = {{}}", ""]
    L.append(f"{P}_Config.BG_IMAGES = {{")
    for p in a["bgs"]:
        L.append(f"\t{lq(p)},")
    L.append("}")
    L.append(f"{P}_Config.IMAGE_HOLD_MS = {int(t.hold_ms)}")
    trans_ms = 0 if (t.no_transition or len(a["bgs"]) < 2) else int(t.transition_ms)
    L.append(f"{P}_Config.TRANSITION_MS = {trans_ms}")
    L.append(f"{P}_Config.IMAGE_DRIFT = {'true' if t.drift else 'false'}")
    L.append(f"{P}_Config.DRIFT_PX = {int(t.drift_px)}")
    if t.zoom:
        L.append(f"{P}_Config.IMAGE_ZOOM = {max(1, min(50, int(t.zoom_pct)))}")
    if t.zoom or image_scale(t) != 100:
        L.append(f"{P}_Config.IMAGE_SCALE = {image_scale(t)}")
    if a["card_default"]:
        L.append(f"{P}_Config.CARD_DEFAULT_PHOTO = {lq(a['card_default'])}")
    if a["logo_alt"]:
        L.append(f"{P}_Config.LOGO_ALT = {lq(a['logo_alt'])}")
    if a["clips"]:
        L += ["", f"{P}_Config.VIDEO = {{", f"\tmode = {lq(t.video_mode)},", "\tclips = {"]
        for c in a["clips"]:
            L.append("\t\t{")
            L.append(f"\t\t\tvideo = {lq(c['video'])},")
            L.append(f"\t\t\tstill = {lq(c['still'])},")
            if c["sound"]:
                L.append(f"\t\t\tsound = {lq(c['sound'])},")
            if t.video_mode != "random" and c["length_ms"] > 0:
                L.append(f"\t\t\tlengthMs = {int(c['length_ms'])},")
            L.append(f"\t\t\twidth = {int(c['width'])}, height = {int(c['height'])},")
            L.append(f"\t\t\tsoundVolume = {int(c['sound_volume'])},")
            L.append(f"\t\t\trestartVideo = {'true' if c['restart_video'] else 'false'},")
            L.append(f"\t\t\trestartSound = {'true' if c['restart_sound'] else 'false'},")
            L.append("\t\t},")
        L += ["\t},", "}"]
    return "\n".join(L) + "\n"


def _credit_lua(groups, indent="\t\t"):
    out = []
    for g in groups:
        if not g["rows"]:
            out.append(f"{indent}{{ header = {lq(g['header'])} }},")
            continue
        rows = ", ".join(lq(r) for r in g["rows"])
        out.append(f"{indent}{{ header = {lq(g['header'])}, rows = {{ {rows} }} }},")
    return out


def gen_theme(t, a):
    P = t.prefix
    has_img = bool(a["bgs"])
    has_vid = bool(a["clips"])
    static = t.no_transition or len(a["bgs"]) < 2      # one image (or "instant") = nothing to animate
    L = ['require "MTF_Core"', f'require "{P}_Config"', "",
         f"-- {one_line(t.name)}: generated by Menu Theme Builder.",
         "-- Re-open this mod in the tool to edit it; manual changes here are overwritten when you save from the tool.", ""]
    if has_img:
        L += [f"for _, path in ipairs({P}_Config.BG_IMAGES) do", "\tgetTexture(path)", "end"]
    if a["card_default"]:
        L.append(f"getTexture({P}_Config.CARD_DEFAULT_PHOTO)")
    if a["logo_alt"]:
        L.append(f"getTexture({P}_Config.LOGO_ALT)")
    L.append("")

    if a["logo_alt"]:
        L += [f"local function {P}_LogoPath(ctx)",
              f'\tif ctx.settings.get("LogoVariant") == "alt" and getTexture({P}_Config.LOGO_ALT) then',
              f"\t\treturn {P}_Config.LOGO_ALT", "\tend", "\treturn nil", "end", ""]
    stacked = "left" in t.layouts
    if stacked:
        L += [f"local function {P}_LeftCentreY(ctx)", "\treturn ctx.height / 2", "end", "",
              f"local function {P}_LeftX(ctx)",
              "\tlocal icon = MenuThemeFramework.optionsButtonRect and MenuThemeFramework.optionsButtonRect()",
              "\tif icon then", "\t\tlocal theme = MenuThemeFramework.theme",
              '\t\tlocal pad = theme and type(theme.menu) == "table" and theme.menu.listHighlightPad',
              '\t\treturn icon.x + (type(pad) == "number" and pad or 6)', "\tend", "\treturn nil", "end", ""]
    if t.logo_place == "custom" or stacked:
        L.append(f"local function {P}_LogoPlace(ctx, w, h, uiScale)")
        if stacked:
            L += ['\tif ctx.menu.layoutId() == "left" then',
                  "\t\treturn ctx.layout.originX + ctx.layout.refW - 50 * uiScale - w, ctx.layout.originY + 50 * uiScale",
                  "\tend"]
        if t.logo_place == "custom":
            L.append(f"\treturn ctx.layout.originX + {int(t.logo_x)} * uiScale, ctx.layout.originY + {int(t.logo_y)} * uiScale")
        else:
            L.append("\treturn nil")
        L += ["end", ""]

    L += ["local run = nil", "",
          "local function startRun(ctx)", "\trun = { screen = ctx.screen, startMs = ctx.now }", "end", ""]

    if has_img:
        picture = bool(t.zoom or image_scale(t) != 100)
        seamless = bool(t.seamless_slide) and not static
        draw_lines = [
            "local function drawImages(ctx)",
            f"\tlocal count = #{P}_Config.BG_IMAGES",
            "\tif count == 0 then", "\t\treturn", "\tend",
            *([
                '\tlocal transition = ctx.settings.get("Transition")',
                '\tif count > 1 and (transition == "slide" or transition == "slidedown") then',
                "\t\tdrawSeamless(ctx, transition, count)", "\t\treturn", "\tend",
            ] if seamless else []),
            f"\tlocal cycleMs = {P}_Config.TRANSITION_MS + {P}_Config.IMAGE_HOLD_MS + {P}_Config.TRANSITION_MS",
            "\tlocal elapsed = ctx.now - run.startMs",
            "\tlocal index = math.floor(elapsed / cycleMs) % count + 1",
            "\tlocal into = elapsed % cycleMs",
            f"\tif elapsed < cycleMs and into < {P}_Config.TRANSITION_MS then",
            f"\t\tinto = {P}_Config.TRANSITION_MS",
            "\tend", "",
            f"\tlocal img = ctx.tex({P}_Config.BG_IMAGES[index])",
            "\tif not img then", "\t\treturn", "\tend",
            ('\tlocal style = "fade"' if static else '\tlocal style = ctx.settings.get("Transition")'),
            "\tlocal w, h = ctx.width, ctx.height",
            f"\tlocal drift = {P}_Config.IMAGE_DRIFT and {P}_Config.DRIFT_PX * ctx.layout.uiScale or 0",
            f"\tlocal driftX = -drift * math.min(1, math.max(0, (into - {P}_Config.TRANSITION_MS) / {P}_Config.IMAGE_HOLD_MS))",
            "",
            f"\tif into < {P}_Config.TRANSITION_MS then",
            f"\t\tlocal t = into / {P}_Config.TRANSITION_MS",
            '\t\tif style == "slide" then', "\t\t\tctx.drawCover(img, 1, w * (1 - t), 0)",
            '\t\telseif style == "slidedown" then', "\t\t\tctx.drawCover(img, 1, 0, -h * (1 - t))",
            "\t\telse", "\t\t\tctx.drawCover(img, 1, 0, 0)",
            "\t\t\tctx.screen:drawRect(0, 0, w, h, 1 - t, 0, 0, 0)", "\t\tend",
            f"\telseif into < {P}_Config.TRANSITION_MS + {P}_Config.IMAGE_HOLD_MS then",
            "\t\tctx.drawCover(img, 1, driftX, 0)",
            "\telse",
            f"\t\tlocal t = (into - {P}_Config.TRANSITION_MS - {P}_Config.IMAGE_HOLD_MS) / {P}_Config.TRANSITION_MS",
            '\t\tif style == "slide" then', "\t\t\tctx.drawCover(img, 1, driftX - w * t, 0)",
            '\t\telseif style == "slidedown" then', "\t\t\tctx.drawCover(img, 1, driftX, h * t)",
            "\t\telse", "\t\t\tctx.drawCover(img, 1, driftX, 0)",
            "\t\t\tctx.screen:drawRect(0, 0, w, h, t, 0, 0, 0)", "\t\tend",
            "\tend", "end", ""]
        if picture:
            L += picture_helper()
        if seamless:
            L += seamless_lines(P, picture, t.zoom)
        L += picture_body(P, draw_lines, t.zoom) if picture else draw_lines

    L += [f"local function {P}_renderBackground(ctx)",
          "\tif not run or run.screen ~= ctx.screen then", "\t\tstartRun(ctx)", "\tend",
          "\tctx.screen:drawRect(0, 0, ctx.width, ctx.height, 1, 0, 0, 0)"]
    if has_img and has_vid:
        L += ['\tif ctx.settings.get("BackgroundMode") == "video" then', "\t\tctx.video.play()", "\telse",
              "\t\tctx.video.stop()", "\t\tdrawImages(ctx)", "\tend"]
    elif has_vid:
        L.append("\tctx.video.play()")
    else:
        L.append("\tdrawImages(ctx)")
    L += ["end", ""]

    # ---- registerTheme
    L += ["MenuThemeFramework.registerTheme({",
          f"\tid = {lq(t.theme_id)},",
          f'\tname = "IGUI_{P}_Name",',
          f"\tmodId = {lq(t.mod_id)},",
          f"\tassetPrefix = {lq(P)},",
          f"\tsettingsFolder = {lq(t.theme_id)},", ""]
    groups = final_credit_groups(t)
    if groups:
        L += ["\tcredits = {"] + _credit_lua(groups) + ["\t},"]
    footer = []
    if t.about.strip():
        footer.append({"header": "About this Mod:", "rows": [t.about.strip()]})
    footer.append({"header": stamp_text(), "rows": []})
    L += ["\tcreditsFooter = {"] + _credit_lua(footer) + ["\t},"]

    if t.layouts:
        default = t.default_layout if t.default_layout in t.layouts else t.layouts[0]
        L += ["", "\tlayouts = {"]
        for lid in t.layouts:
            suffix = LAYOUTS[lid][1]
            base = f'\t\t{{ id = "{lid}", name = "IGUI_{P}_{suffix}", '
            extra = {"rail": 'preset = "keep"',
                     "left": f'preset = "keep", alignY = {P}_LeftCentreY, alignX = {P}_LeftX',
                     "strip": 'preset = "strip"',
                     "carousel": 'preset = "carousel", carouselAlign = "centre"',
                     "cards_wide": 'preset = "cards", cardWidth = 1228',
                     "cards_vertical": 'preset = "cards", cardOrientation = "vertical"'}[lid]
            L.append(base + extra + " },")
        L += ["\t},", f'\tdefaultLayout = "{default}",']

    # settings
    sett = []
    if has_img and has_vid:
        sett.append(f'\t\t{{ key = "BackgroundMode", type = "choice", default = {lq(t.default_bg_mode)}, first = true, '
                    f'values = {{ "images", "video" }}, labels = {{ "IGUI_{P}_BackgroundImages", "IGUI_{P}_BackgroundVideo" }}, '
                    f'label = "IGUI_{P}_Background" }},')
    if has_img and not static:
        sett.append(f'\t\t{{ key = "Transition", type = "choice", default = {lq(t.transition_style)}, '
                    f'values = {{ "slide", "slidedown", "fade" }}, '
                    f'labels = {{ "IGUI_{P}_AnimSlide", "IGUI_{P}_AnimSlideDown", "IGUI_{P}_AnimFade" }}, label = "IGUI_{P}_Transition" }},')
    if a["logo_alt"]:
        sett.append(f'\t\t{{ key = "LogoVariant", type = "choice", default = "standard", values = {{ "standard", "alt" }}, '
                    f'labels = {{ "IGUI_{P}_LogoStandard", "IGUI_{P}_LogoAlt" }}, label = "IGUI_{P}_Logo" }},')
    if sett:
        L += ["", "\tsettings = {"] + sett + ["\t},"]

    L += ["", "\trender = {", f"\t\tbackground = {P}_renderBackground,", "\t},"]

    logo = ["\tlogo = {", "\t\tslide = 0.35," if t.logo_slide else "\t\tslide = 0,"]
    n = 0
    if t.logo_place == "custom" or stacked:
        logo.append(f"\t\tplace = {P}_LogoPlace,"); n += 1
    if a["logo_alt"]:
        logo.append(f"\t\tpath = {P}_LogoPath,"); n += 1
    if n or t.logo_slide:   # MTF's plain default is slide = 0, so the table is only needed to turn the slide on
        L += ["", *logo, "\t},"]

    if t.tracks:
        L += ["", "\tmusic = {"]
        for tr in a["tracks"]:
            L.append(f"\t\t{{ {lq(tr['sound'])}, {lq(tr['title'])}, {max(1, int(tr['length_ms']))} }},")
        L.append("\t},")
        if t.repeat_one:
            L.append("\tmusicRepeatOne = true,")
    if has_vid:
        L += ["", f"\tvideo = {P}_Config.VIDEO,"]

    menu = []
    if t.list_highlight in ("white", "caption"):
        menu.append(f'\t\tlistHighlight = "{t.list_highlight}",')
    if t.list_highlight == "caption" and t.highlight_tint_on:
        hc = QColor(t.highlight_tint)
        menu.append(f"\t\tlistHighlightTint = {{ r = {hc.redF():.3f}, g = {hc.greenF():.3f}, b = {hc.blueF():.3f} }},")
    if t.fonts:
        menu.append("\t\tfonts = {")
        for fp in font_plan(t):
            fnt = f"media/fonts/{P}/{fp['stem']}.fnt"
            menu.append(f'\t\t\t{{ id = {lq(fp["id"])}, name = "{fp["key"]}", fnt = {lq(fnt)} }},')
        menu.append("\t\t},")
    if menu:
        L += ["", "\tmenu = {"] + menu + ["\t},"]

    if has_img:
        L += ["", "\tloadCover = {", "\t\tready = function(ctx)",
              f"\t\t\treturn MenuThemeFramework.texturesReady({P}_Config.BG_IMAGES)", "\t\tend,",
              "\t\tfadeMs = 500,", "\t\tmaxHoldMs = 10000,", "\t},"]
    if static:
        L += ["", "\ttransitionSpeed = false,"]

    if a["card_default"]:
        L += ["", "\tcardPhoto = function(buttonId)", f"\t\treturn {P}_Config.CARD_DEFAULT_PHOTO", "\tend,"]
    if t.caption or t.caption_tint_on or needs_caption_art(t):
        look = []
        if t.caption_tint_on or needs_caption_art(t):
            c = QColor(t.caption_tint) if t.caption_tint_on else QColor("black")
            look.append(f"\t\t\tcaptionTint = {{ r = {c.redF():.3f}, g = {c.greenF():.3f}, b = {c.blueF():.3f} }},")
        if EMIT_CAPTION_UNDER_BORDER:
            look.append("\t\t\tcaptionUnderBorder = true,")
        if look:
            L += ["", "\tcards = {", "\t\tlook = {"] + look + ["\t\t},", "\t},"]

    if t.buttons_instant:
        L += ["", "\treveal = { fadeMs = 0, slide = \"none\" },"]

    cfg = [f"\t\tMUSIC_VOLUME = {t.music_volume / 100:.2f},"]
    if has_vid:
        cfg.append(f"\t\tVIDEO_VOLUME = {t.video_volume / 100:.2f},")
    cfg.append(f"\t\tLOGO_FADE_IN_MS = {int(t.logo_fade_ms)},")
    lh = logo_display_height(t)
    if lh:
        cfg.append(f"\t\tLOGO_DISPLAY_HEIGHT = {lh},")
    L += ["", "\tconfig = {"] + cfg + ["\t},", "})", ""]
    return "\n".join(L)


def gen_sounds(a):
    L = ["module Base", "{"]
    entries = [(x["sound"], x["file"], True) for x in a["tracks"]] + \
              [(c["sound"], c["sound_file"], c["loop"]) for c in a["clips"] if c["sound"]]
    for i, (name, f, loop) in enumerate(entries):
        L += [f"    sound {name}", "    {", "        category = Ambient,", "        master = Primary,",
              f"        loop = {'true' if loop else 'false'},", "        volume = 1.0,", "        is3D = false,", "        clip", "        {",
              f"            file = {f},", "        }", "    }"]
        if i != len(entries) - 1:
            L.append("")
    L.append("}")
    return "\r\n".join(L) + "\r\n"


def gen_translation(t):
    P = t.prefix
    d = {f"IGUI_{P}_Name": t.name,
         f"IGUI_{P}_Background": "Background", f"IGUI_{P}_BackgroundImages": "Images",
         f"IGUI_{P}_BackgroundVideo": "Video", f"IGUI_{P}_Transition": "Slideshow Animation",
         f"IGUI_{P}_AnimSlide": "Horizontal Slide", f"IGUI_{P}_AnimSlideDown": "Vertical Slide",
         f"IGUI_{P}_AnimFade": "Fade", f"IGUI_{P}_Logo": "Logo",
         f"IGUI_{P}_LogoStandard": "Standard", f"IGUI_{P}_LogoAlt": "Alternative"}
    for lid in t.layouts:
        d[f"IGUI_{P}_{LAYOUTS[lid][1]}"] = LAYOUTS[lid][2]
    for fp in font_plan(t):
        d[fp["key"]] = fp["label"]
    return json.dumps(d, indent="\t", ensure_ascii=False) + "\n"


def gen_modinfo(t):
    desc = re.sub(r"[\x00-\x09\x0b-\x1f\x7f]", "", t.description.strip().replace("\r", "")).replace("\n", " <LINE> ")
    lines = [f"name={one_line(t.name)}", f"id={t.mod_id}", f"description={desc}", "poster=poster.png",
             f"author={one_line(t.author)}", "icon=icon.png", "require=ObnoxMenuThemeFrameworkB42",
             "loadAfter=ObnoxMenuThemeFrameworkB42", f"versionMin={one_line(t.version_min)}",
             f"modversion={one_line(t.mod_version)}"]
    return "\r\n".join(lines) + "\r\n"


# ---------------------------------------------------------------- build --------------

def build(theme: Theme, workshop_dir, allow_foreign_overwrite=False):
    """Write the mod. Returns (new_theme, target_root). Raises BuildError."""
    errs, _ = validate(theme)
    if errs:
        raise BuildError("\n".join(errs))
    t = theme
    P = t.prefix
    workshop_dir = Path(workshop_dir)
    target_root = workshop_dir / t.theme_id
    final_mod = target_root / "Contents" / "mods" / t.theme_id
    if target_root.exists() and not (target_root / PROJECT_FILE).exists() and not allow_foreign_overwrite:
        raise BuildError(f"FOREIGN:{target_root}")

    staging = workshop_dir / f".staging_{t.theme_id}"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    mod = staging / "Contents" / "mods" / t.theme_id
    m42 = mod / "42"
    media = m42 / "media"
    new_paths = {}   # id(src str) -> final absolute path; used to rewrite the project
    a = {"bgs": [], "tracks": [], "clips": [], "card_default": "", "logo_alt": ""}
    out = map_paths(t, lambda p: p)   # copy we will rewrite

    def final(path_in_m42):
        return str(final_mod / "42" / path_in_m42)

    try:
        # backgrounds
        for i, src in enumerate(t.backgrounds, 1):
            rel = f"media/ui/backgrounds/{P}_Background_{i}.png"
            put_png(src, m42 / rel)
            a["bgs"].append(rel)
            out.backgrounds[i - 1] = final(rel)

        def conv(attr, rel, key=None):
            src = getattr(t, attr)
            if src:
                put_png(src, m42 / rel)
                setattr(out, attr, final(rel))
                return rel
            return ""
        conv("logo", f"media/ui/logos/{P}_Menu_Logo.png")
        a["logo_alt"] = conv("logo_alt", f"media/ui/logos/{P}_Menu_Logo_Alt.png")
        conv("options_icon", f"media/ui/icons/{P}_Options_Icon.png")
        conv("strip", f"media/ui/layout/{P}_Strip.png")
        conv("arrow_h", f"media/ui/layout/{P}_Arrow_H.png")
        conv("arrow_v", f"media/ui/layout/{P}_Arrow_V.png")
        conv("caption", f"media/ui/cards/captions/{P}_Caption.png")
        if needs_caption_art(t):
            put_solid(m42 / f"media/ui/cards/captions/{P}_Caption.png", 256, 64, "#ffffff")
        a["card_default"] = conv("card_default", f"media/ui/cards/backgrounds/{P}_Card_Default.png")
        for bid in BUTTON_IDS:
            src = t.cards.get(bid)
            if src:
                rel = f"media/ui/cards/backgrounds/{P}_Card_{bid}.png"
                put_png(src, m42 / rel)
                out.cards[bid] = final(rel)

        # menu button font: the .ttf is turned into the game's bitmap font (5 sizes); the .ttf itself stays in the
        # project folder (not in the mod) so the theme can be edited again
        if t.fonts:
            from . import fontgen
            src_dir = staging / "FontSource"
            kept = set()

            def keep(name):
                n, k = name, 2
                while n.lower() in kept:
                    n = f"{Path(name).stem}_{k}{Path(name).suffix}"
                    k += 1
                kept.add(n.lower())
                return n
            for i, fp in enumerate(font_plan(t)):
                f = fp["font"]
                try:
                    fontgen.generate_menu_font(f.file, media / "fonts" / P, f.scale, fp["stem"])
                except fontgen.FontError as e:
                    raise BuildError(str(e))
                fname = keep(Path(f.file).name)
                put_file(f.file, src_dir / fname)
                out.fonts[i].file = str(target_root / "FontSource" / fname)
                if f.license and Path(f.license).is_file():
                    put_file(f.license, media / "fonts" / P / f"OFL-{sanitize_stem(Path(fname).stem)}.txt")
                    lname = keep(Path(f.license).name)
                    put_file(f.license, src_dir / lname)
                    out.fonts[i].license = str(target_root / "FontSource" / lname)
                else:
                    out.fonts[i].license = ""

        # music
        used = set()

        def unique(stem):
            n, k = stem, 2
            while n.lower() in used:
                n = f"{stem}_{k}"; k += 1
            used.add(n.lower())
            return n
        for i, tr in enumerate(t.tracks):
            base_stem = sanitize_stem(Path(tr.path).stem)
            if base_stem.lower().startswith(P.lower() + "_"):
                base_stem = base_stem[len(P) + 1:] or "Track"
            stem = unique(f"{P}_{base_stem}")
            rel = f"media/sounds/{stem}.ogg"
            put_file(tr.path, m42 / rel)
            out.tracks[i].path = final(rel)
            a["tracks"].append({"sound": stem, "file": rel, "title": tr.title or Path(tr.path).stem,
                                "length_ms": tr.length_ms})

        # video
        for i, c in enumerate(t.clips):
            n = i + 1
            vrel = f"media/videos/{P}_Clip_{n}.bik"
            put_file(c.video, m42 / vrel)
            out.clips[i].video = final(vrel)
            srel = vrel + ".png"
            put_png(c.still or (t.backgrounds[0] if t.backgrounds else None) or _blank_still(staging, c), m42 / srel)
            out.clips[i].still = final(srel) if c.still else ""
            entry = {"video": f"{P}_Clip_{n}.bik", "still": srel, "sound": "", "sound_file": "",
                     "width": c.width, "height": c.height, "length_ms": c.length_ms,
                     "sound_volume": c.sound_volume, "restart_video": c.restart_video,
                     "restart_sound": c.restart_sound,
                     # MTF restarts the sound itself at lengthMs, so then the script must not loop; without a
                     # lengthMs (random mode) or with restartSound = false the game has to loop it
                     "loop": not (t.video_mode != "random" and c.length_ms > 0 and c.restart_sound)}
            if c.sound:
                stem = unique(f"{P}_Clip_{n}")
                arel = f"media/sounds/{stem}.ogg"
                put_file(c.sound, m42 / arel)
                out.clips[i].sound = final(arel)
                entry["sound"], entry["sound_file"] = stem, arel
            a["clips"].append(entry)

        # lua / scripts / info
        (media / "lua" / "shared").mkdir(parents=True, exist_ok=True)
        (media / "lua" / "client").mkdir(parents=True, exist_ok=True)
        (media / "lua" / "shared" / f"{P}_Config.lua").write_text(gen_config(t, a), encoding="utf-8", newline="\n")
        (media / "lua" / "client" / f"{P}_Theme.lua").write_text(gen_theme(t, a), encoding="utf-8", newline="\n")
        if a["tracks"] or any(c["sound"] for c in a["clips"]):
            (media / "scripts").mkdir(parents=True, exist_ok=True)
            (media / "scripts" / f"{P}_Sounds.txt").write_text(gen_sounds(a), encoding="utf-8", newline="")
        tdir = mod / "common" / "media" / "lua" / "shared" / "Translate" / "EN"
        tdir.mkdir(parents=True, exist_ok=True)
        (tdir / "IG_UI.json").write_text(gen_translation(t), encoding="utf-8", newline="\n")
        info = gen_modinfo(t)
        for d in (mod, m42):
            (d / "mod.info").write_text(info, encoding="utf-8", newline="")

        # poster + icon (root and 42/)
        first_bg = t.backgrounds[0] if t.backgrounds else None
        for d in (mod, m42):
            if t.poster:
                put_png(t.poster, d / "poster.png")
            else:
                square_from(first_bg, 256, t.prefix).save(str(d / "poster.png"), "PNG")
            if t.icon:
                put_png(t.icon, d / "icon.png")
            else:
                square_from(first_bg, 82, t.prefix).save(str(d / "icon.png"), "PNG")
        if t.poster:
            out.poster = str(final_mod / "poster.png")
        if t.icon:
            out.icon = str(final_mod / "icon.png")
        square_from(t.poster or first_bg, 512, t.prefix).save(str(staging / "preview.png"), "PNG")

        # project file is written relative to the FINAL location
        _save_project_for(out, staging, target_root)

        if target_root.exists():
            shutil.rmtree(target_root)
        staging.rename(target_root)
    except BuildError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except OSError as e:
        shutil.rmtree(staging, ignore_errors=True)
        raise BuildError(f"File error: {e}\n(Is the game or a file explorer window using the folder?)")
    return out, target_root


def _blank_still(staging, clip):
    p = staging / "_blank_still.png"
    img = QImage(max(16, clip.width // 8), max(9, clip.height // 8), QImage.Format_ARGB32)
    img.fill(QColor("black"))
    img.save(str(p), "PNG")
    return p


def _save_project_for(theme, staging: Path, final_root: Path):
    """Write the project JSON into staging with paths relative to final_root."""
    import json as _json
    from dataclasses import asdict

    def rel(p):
        try:
            return Path(p).resolve().relative_to(final_root.resolve()).as_posix()
        except ValueError:
            return str(p)
    data = asdict(map_paths(theme, rel))
    data["builder_version"] = APP_VERSION
    (staging / PROJECT_FILE).write_text(_json.dumps(data, indent=2), encoding="utf-8")
