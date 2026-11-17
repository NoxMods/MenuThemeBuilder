"""Best-effort import of a Menu Theme mod that was NOT made with this tool."""
import re
from pathlib import Path

from .model import Theme, Track, Clip, BUTTON_IDS, LAYOUTS, auto_prefix, slug
from .mediainfo import read_ogg_info


def find_mod_root(folder: Path):
    folder = Path(folder)
    if (folder / "mod.info").is_file():
        return folder
    for pattern in ("Contents/mods/*/mod.info", "mods/*/mod.info", "*/mod.info", "*/*/mod.info", "*/*/*/mod.info"):
        hits = sorted(folder.glob(pattern))
        if hits:
            return hits[0].parent
    return None


def _read(p, strip_comments=False):
    try:
        text = Path(p).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if strip_comments:
        text = re.sub(r"--!.*?!--", "", text, flags=re.S)
        text = re.sub(r"--[^\n]*", "", text)
    return text


def _block(text, key):
    m = re.search(rf"\b{key}\s*=\s*\{{", text)
    if not m:
        return None
    i, depth = m.end(), 1
    while i < len(text) and depth:
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
    return text[m.end(): i - 1]


def _num(text, key, default):
    m = re.search(rf"{key}\s*=\s*(\d+)", text)
    return int(m.group(1)) if m else default


def import_theme(folder):
    """Returns (Theme, notes[list[str]]). Raises ValueError when no theme is found."""
    root = find_mod_root(Path(folder))
    if root is None:
        raise ValueError("No mod.info found in that folder.")
    base = root / "42" if (root / "42").is_dir() else root
    notes = []
    t = Theme()

    info = {}
    for line in _read(root / "mod.info").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            info[k.strip()] = v.strip()
    t.name = info.get("name", root.name)
    t.author = info.get("author", "")
    t.description = info.get("description", "").replace("<LINE>", "\n").replace("  ", " ").strip()
    t.mod_version = info.get("modversion", "1.0.0")
    t.version_min = info.get("versionMin", "42.19.0")

    lua_dir = base / "media" / "lua"
    theme_lua = config_lua = ""
    for f in sorted((lua_dir / "client").glob("*.lua")) if (lua_dir / "client").is_dir() else []:
        txt = _read(f, True)
        if "registerTheme" in txt:
            theme_lua += txt
    for f in sorted((lua_dir / "shared").glob("*Config*.lua")) if (lua_dir / "shared").is_dir() else []:
        config_lua += _read(f, True)
    both = config_lua + "\n" + theme_lua
    if not theme_lua:
        notes.append("No registerTheme call was found; only files found by name were imported.")

    m = re.search(r'assetPrefix\s*=\s*"(\w+)"', theme_lua)
    prefix = m.group(1) if m else ""
    if not prefix:
        for f in (base / "media" / "ui").rglob("*_Menu_Logo*.png"):
            prefix = f.name.split("_")[0]
            break
    t.prefix = prefix or auto_prefix(t.name)
    m = re.search(r'registerTheme\(\{.*?\bid\s*=\s*"(\w+)"', theme_lua, re.S)
    orig_id = m.group(1) if m else slug(t.name)
    # keep the original untouched: the imported copy gets its own id / folder
    t.theme_id = orig_id + "Edited"
    t.name = t.name + " (Edited)"
    t.auto_ids = False

    # backgrounds + timings
    bgs = re.findall(r'"([^"]+\.(?:png|jpg|jpeg))"', _block(config_lua, "BG_IMAGES") or "")
    if not bgs:
        bgs = re.findall(r'"([^"]+\.(?:png|jpg|jpeg))"', _block(theme_lua, "backgrounds") or "")
    t.backgrounds = [str(base / b) for b in bgs if (base / b).is_file()]
    if len(t.backgrounds) < len(bgs):
        notes.append("Some background images were listed but not found on disk.")
    t.hold_ms = _num(config_lua, "IMAGE_HOLD_MS", t.hold_ms)
    t.transition_ms = _num(config_lua, "TRANSITION_MS", t.transition_ms)
    t.drift = bool(re.search(r"IMAGE_DRIFT\s*=\s*true", config_lua))
    t.drift_px = _num(config_lua, "DRIFT_PX", t.drift_px)
    m = re.search(r'key\s*=\s*"Transition".*?default\s*=\s*"(\w+)"', theme_lua, re.S)
    if m and m.group(1) in ("slide", "slidedown", "fade"):
        t.transition_style = m.group(1)

    # sound scripts: sound name -> file
    sounds = {}
    for f in (base / "media" / "scripts").glob("*.txt") if (base / "media" / "scripts").is_dir() else []:
        for sm in re.finditer(r"sound\s+(\w+)\s*\{.*?file\s*=\s*([^,\s}]+)", _read(f), re.S):
            sounds[sm.group(1)] = sm.group(2)

    # music
    block = _block(theme_lua, "music")
    for e in re.finditer(r'\{\s*"([^"]+)"\s*,\s*"([^"]*)"\s*,\s*(\d+)', block or ""):
        sname, title, length = e.group(1), e.group(2), int(e.group(3))
        if sname in sounds and (base / sounds[sname]).is_file():
            t.tracks.append(Track(str(base / sounds[sname]), title, length))
    t.repeat_one = bool(re.search(r"musicRepeatOne\s*=\s*true", theme_lua))
    if block and not t.tracks:
        notes.append("Music was declared but its .ogg files could not be matched.")

    # video clips
    vm = re.search(r'mode\s*=\s*"(random|order|shuffle)"', config_lua)
    if vm:
        t.video_mode = vm.group(1)
    parts = re.split(r'video\s*=\s*"', config_lua)[1:]
    for part in parts:
        vname = part.split('"', 1)[0]
        vf = base / "media" / "videos" / vname
        if not vf.is_file():
            continue
        seg = part
        c = Clip(video=str(vf))
        sm = re.search(r'still\s*=\s*"([^"]+)"', seg)
        if sm and (base / sm.group(1)).is_file():
            c.still = str(base / sm.group(1))
        sm = re.search(r'sound\s*=\s*"(\w+)"', seg)
        if sm and sm.group(1) in sounds and (base / sounds[sm.group(1)]).is_file():
            c.sound = str(base / sounds[sm.group(1)])
        c.width, c.height = _num(seg, "width", 1920), _num(seg, "height", 1080)
        c.length_ms = _num(seg, "lengthMs", 0)
        c.sound_volume = _num(seg, "soundVolume", 100)
        c.restart_video = bool(re.search(r"restartVideo\s*=\s*true", seg))
        c.restart_sound = bool(re.search(r"restartSound\s*=\s*true", seg))
        if c.sound and not c.length_ms:
            try:
                c.length_ms = read_ogg_info(c.sound)["duration_ms"]
            except (ValueError, OSError):
                pass
        t.clips.append(c)

    # layouts
    ids = [i for i in re.findall(r'\{\s*id\s*=\s*"(\w+)"', theme_lua) if i in LAYOUTS]
    if ids:
        t.layouts = ids
        m = re.search(r'defaultLayout\s*=\s*"(\w+)"', theme_lua)
        t.default_layout = m.group(1) if m and m.group(1) in ids else ids[0]
    elif theme_lua:
        t.layouts = []

    # files found by name
    ui = base / "media" / "ui"
    P = t.prefix

    def first(*names):
        for n in names:
            for f in ui.rglob(n):
                return str(f)
        return ""
    t.logo = first(f"{P}_Menu_Logo.png")
    t.logo_alt = first(f"{P}_Menu_Logo_Alt.png")
    t.options_icon = first(f"{P}_Options_Icon.png")
    t.strip = first(f"{P}_Strip.png")
    t.arrow_h = first(f"{P}_Arrow_H.png")
    t.arrow_v = first(f"{P}_Arrow_V.png")
    t.caption = first(f"{P}_Caption.png")
    t.card_default = first(f"{P}_Card_Default.png")
    for bid in BUTTON_IDS:
        p = first(f"{P}_Card_{bid}.png")
        if p:
            t.cards[bid] = p
    for cand in (root / "poster.png", base / "poster.png"):
        if cand.is_file():
            t.poster = str(cand); break
    for cand in (root / "icon.png", base / "icon.png"):
        if cand.is_file():
            t.icon = str(cand); break

    t.credits_text = f"# Theme:\n{t.author}\n" if t.author else "# Theme:\n"
    notes.append("Imported best-effort: custom Lua code (painters, intro sequences, fonts, hooks) is NOT carried over. "
                 "Saving writes a new mod with its own id; the original is left untouched.")
    return t, notes
