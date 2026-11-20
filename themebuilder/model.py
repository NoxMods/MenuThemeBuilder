import copy
import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

PROJECT_FILE = "ThemeProject.json"
BUTTON_IDS = ["LATESTSAVE", "SOLO", "COOP", "MULTIPLAYER", "OPTIONS", "MODS",
              "WORKSHOP", "TUTORIAL", "CREDITS", "EXIT", "LOAD"]
# id -> (display name, translation suffix)
LAYOUTS = {
    "rail": ("Zomboid (vanilla list)", "LayoutRail", "Zomboid"),
    "strip": ("Strip", "LayoutStrip", "Strip"),
    "carousel": ("Carousel", "LayoutCarousel", "Carousel"),
    "cards_wide": ("Horizontal Cards", "LayoutCardsWide", "Horizontal Cards"),
    "cards_vertical": ("Vertical Cards", "LayoutCardsVertical", "Vertical Cards"),
}
TRANSITIONS = [("slide", "Horizontal Slide"), ("slidedown", "Vertical Slide"), ("fade", "Fade")]


@dataclass
class Track:
    path: str = ""
    title: str = ""
    length_ms: int = 0


@dataclass
class Clip:
    video: str = ""
    still: str = ""
    sound: str = ""
    width: int = 1920
    height: int = 1080
    length_ms: int = 0
    sound_volume: int = 100
    restart_video: bool = False
    restart_sound: bool = False


@dataclass
class Theme:
    # identity
    name: str = "My Menu Theme"
    theme_id: str = "MyMenuTheme"
    prefix: str = "MMT"
    auto_ids: bool = True
    author: str = ""
    description: str = "A main menu theme for Menu Theme Framework."
    mod_version: str = "1.0.0"
    version_min: str = "42.19.0"
    poster: str = ""
    icon: str = ""
    # backgrounds
    backgrounds: list = field(default_factory=list)
    hold_ms: int = 8000
    transition_ms: int = 450
    transition_style: str = "slide"
    no_transition: bool = False       # True = images change instantly, no animation
    drift: bool = False
    drift_px: int = 30
    # logo / layout
    logo: str = ""
    logo_alt: str = ""
    logo_scale: int = 100             # % of the logo image's own size
    logo_slide: bool = True           # logo slides down a little while it fades in
    buttons_instant: bool = False     # True = menu buttons appear without fade-in
    logo_place: str = "default"       # default | custom
    logo_x: int = 60
    logo_y: int = 40
    options_icon: str = ""
    layouts: list = field(default_factory=lambda: ["rail", "strip", "carousel", "cards_wide", "cards_vertical"])
    default_layout: str = "cards_wide"
    strip: str = ""
    arrow_h: str = ""
    arrow_v: str = ""
    list_highlight: str = "default"   # default | white | caption
    # cards
    caption: str = ""
    caption_tint_on: bool = False
    caption_tint: str = "#000000"
    card_default: str = ""
    cards: dict = field(default_factory=dict)
    # menu button font
    font_file: str = ""               # .ttf/.otf converted to the game's bitmap font format when building
    font_name: str = ""
    font_scale: int = 100             # % - every font is drawn at a different visual size
    font_license: str = ""            # licence text file shipped next to the font (optional)
    # audio
    tracks: list = field(default_factory=list)
    repeat_one: bool = False
    music_volume: int = 50
    video_volume: int = 50
    logo_fade_ms: int = 1000
    # video
    video_mode: str = "random"
    default_bg_mode: str = "images"
    clips: list = field(default_factory=list)
    # texts
    credits_text: str = ""            # manual credits, "# Role" lines followed by their rows
    auto_credits: bool = True         # add author + music titles automatically
    about: str = ""

    @property
    def mod_id(self):
        return self.theme_id + "B42"


def slug(text, default="Theme"):
    s = re.sub(r"[^A-Za-z0-9]+", " ", text).title().replace(" ", "")
    if not s:
        s = default
    if s[0].isdigit():
        s = "T" + s
    return s


def auto_prefix(name):
    words = re.findall(r"[A-Za-z0-9]+", name)
    p = "".join(w[0] for w in words).upper()[:4]
    if len(p) < 3:
        p = (slug(name)[:3] or "THM").upper()
    if p[0].isdigit():
        p = "T" + p
    return p


def sanitize_stem(text):
    s = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return s or "File"


# ---- credits ------------------------------------------------------------------------

def parse_credits(text):
    """'# Role' lines start a group, every other non-empty line is a row of the current group."""
    groups, cur = [], None
    for line in (text or "").splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            cur = {"header": s.lstrip("#").strip(), "rows": []}
            groups.append(cur)
        else:
            if cur is None:
                cur = {"header": "", "rows": []}
                groups.append(cur)
            cur["rows"].append(s)
    return [g for g in groups if g["header"] or g["rows"]]


def credit_header(text):
    """'music', 'Music:' -> 'music:'  (the game shows the header exactly as written)."""
    h = (text or "").strip().rstrip(":").strip()
    return h + ":" if h else ""


def final_credit_groups(t):
    """Credits exactly as they will be written into the mod: automatic part + manual part, merged by role."""
    groups = []

    def add(header, rows):
        header = credit_header(header)
        rows = [r.strip() for r in rows if r and r.strip()]
        if not rows:
            return
        for g in groups:
            if g["header"].lower() == header.lower():
                g["rows"].extend(r for r in rows if r not in g["rows"])
                return
        groups.append({"header": header, "rows": list(dict.fromkeys(rows))})

    if t.auto_credits:
        add("Theme", [t.author])
        add("Music", [tr.title or Path(tr.path).stem for tr in t.tracks])
        add("Fonts", [t.font_name] if t.font_file else [])
    for g in parse_credits(t.credits_text):
        add(g["header"], g["rows"])
    return groups


# ---- (de)serialisation -------------------------------------------------------------

def map_paths(theme, fn):
    """Return a deep copy of theme with fn applied to every asset path."""
    t = copy.deepcopy(theme)
    for a in ("poster", "icon", "logo", "logo_alt", "options_icon", "strip",
              "arrow_h", "arrow_v", "caption", "card_default", "font_file", "font_license"):
        v = getattr(t, a)
        setattr(t, a, fn(v) if v else "")
    t.backgrounds = [fn(p) for p in t.backgrounds]
    t.cards = {k: fn(v) for k, v in t.cards.items() if v}
    for tr in t.tracks:
        tr.path = fn(tr.path) if tr.path else ""
    for c in t.clips:
        c.video = fn(c.video) if c.video else ""
        c.still = fn(c.still) if c.still else ""
        c.sound = fn(c.sound) if c.sound else ""
    return t


def save_project(theme, root: Path):
    root = Path(root)

    def rel(p):
        try:
            return Path(p).resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return str(p)
    data = asdict(map_paths(theme, rel))
    (root / PROJECT_FILE).write_text(json.dumps(data, indent=2), encoding="utf-8")


def _coerce(value, default):
    """A value from a project file, forced to the type of the field's default (or the default itself)."""
    if isinstance(default, bool):
        return value if isinstance(value, bool) else default
    if isinstance(default, int):
        if isinstance(value, bool):
            return default
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return default
    for kind in (str, list, dict):
        if isinstance(default, kind):
            return value if isinstance(value, kind) else default
    return value


def _build(cls, data):
    base = cls()
    return cls(**{k: _coerce(data[k], getattr(base, k)) for k in cls.__dataclass_fields__ if k in data})


def _dicts(value):
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def load_project(root: Path):
    root = Path(root)
    data = json.loads((root / PROJECT_FILE).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{PROJECT_FILE} is not a valid project file.")
    tracks = [_build(Track, x) for x in _dicts(data.pop("tracks", []))]
    clips = [_build(Clip, x) for x in _dicts(data.pop("clips", []))]
    t = _build(Theme, data)
    t.tracks, t.clips = tracks, clips
    t.backgrounds = [p for p in t.backgrounds if isinstance(p, str)]
    t.layouts = [i for i in t.layouts if i in LAYOUTS]
    t.cards = {k: v for k, v in t.cards.items() if k in BUTTON_IDS and isinstance(v, str)}

    def absol(p):
        pp = Path(p)
        return str(pp if pp.is_absolute() else (root / pp))
    return map_paths(t, absol)
