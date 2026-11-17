"""Finds and downloads free fonts from Google Fonts (all of them are open licences). Pure Python, no Qt."""
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

CACHE = Path.home() / ".menu_theme_builder" / "fonts"
META_URL = "https://fonts.google.com/metadata/fonts"
CSS_URL = "https://fonts.googleapis.com/css2?family={}"
CSS1_URL = "https://fonts.googleapis.com/css?family={}"
LICENSE_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/{}/OFL.txt"
# Google sends plain .ttf files to clients that do not look like a browser (browsers get .woff2, which Qt cannot load)
UA = "curl/8.0"
TTF_MAGIC = (b"\x00\x01\x00\x00", b"OTTO", b"true", b"ttcf")

# shown if Google Fonts cannot be reached, so the tool still works with a small built-in list
CURATED = [
    ("Pixelify Sans", "Display"), ("Press Start 2P", "Display"), ("VT323", "Monospace"), ("Silkscreen", "Display"),
    ("Germania One", "Display"), ("Cinzel", "Serif"), ("Special Elite", "Display"), ("Creepster", "Display"),
    ("Metal Mania", "Display"), ("Eater", "Display"), ("Butcherman", "Display"), ("Nosifer", "Display"),
    ("Staatliches", "Display"), ("Bebas Neue", "Sans Serif"), ("Oswald", "Sans Serif"), ("Anton", "Sans Serif"),
    ("Teko", "Sans Serif"), ("Black Ops One", "Display"), ("Orbitron", "Sans Serif"), ("Rajdhani", "Sans Serif"),
    ("Saira Condensed", "Sans Serif"), ("Permanent Marker", "Handwriting"), ("Rock Salt", "Handwriting"),
    ("UnifrakturMaguntia", "Display"), ("MedievalSharp", "Display"), ("Jolly Lodger", "Display"),
    ("Fredericka the Great", "Display"), ("Cabin Sketch", "Display"), ("Roboto Condensed", "Sans Serif"),
    ("Share Tech Mono", "Monospace"), ("Cutive Mono", "Monospace"), ("Rubik Glitch", "Display"),
    ("Kelly Slab", "Display"), ("New Rocker", "Display"), ("Uncial Antiqua", "Display"), ("Almendra", "Serif"),
]


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_metadata(raw):
    """[(family, category)] most popular first, from fonts.google.com/metadata/fonts."""
    text = raw.decode("utf-8", "replace")
    data = json.loads(text[text.index("{"):])
    out = []
    for it in data.get("familyMetadataList") or []:
        fam = it.get("family")
        if fam:
            out.append((it.get("popularity") or 10 ** 6, fam, it.get("category") or ""))
    out.sort()
    return [(f, c) for _, f, c in out]


def list_google_fonts():
    """Returns ([(family, category)], online). Falls back to a short built-in list when offline."""
    try:
        items = parse_metadata(_get(META_URL))
        if items:
            return items, True
    except Exception:
        pass
    return list(CURATED), False


def parse_css_url(css):
    m = re.search(r"url\(\s*['\"]?(https?://[^)'\"\s]+)", css)
    return m.group(1) if m else ""


def _dir_name(family):
    return re.sub(r"[^a-z0-9]", "", family.lower())


def _file_stem(family):
    return re.sub(r"[^A-Za-z0-9]+", "_", family).strip("_") or "Font"


def fetch_license(family, folder=CACHE):
    """The font's OFL licence text from Google's font repository ('' if it is not found)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    lic = folder / f"OFL-{_file_stem(family)}.txt"
    if not lic.is_file():
        try:
            lic.write_bytes(_get(LICENSE_URL.format(_dir_name(family))))
        except Exception:
            return ""
    return str(lic)


def download_google_font(family, folder=CACHE, with_license=True):
    """Download the regular weight as .ttf (cached). Returns (ttf_path, license_path or '')."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    ttf = folder / f"{_file_stem(family)}.ttf"
    if not ttf.is_file():
        name = urllib.parse.quote_plus(family)
        data, errors = b"", []
        for css_url in (CSS_URL.format(name), CSS1_URL.format(name)):
            try:
                url = parse_css_url(_get(css_url).decode("utf-8", "replace"))
                if url:
                    data = _get(url)
                    if data[:4] in TTF_MAGIC:
                        break
                    errors.append("Google sent a web font instead of a .ttf")
                    data = b""
            except Exception as e:
                errors.append(str(e))
        if not data:       # last try: the file in Google's public font repository
            try:
                stem = family.replace(" ", "")
                data = _get(f"https://raw.githubusercontent.com/google/fonts/main/ofl/{_dir_name(family)}/{stem}-Regular.ttf")
                if data[:4] not in TTF_MAGIC:
                    data = b""
            except Exception as e:
                errors.append(str(e))
        if not data:
            raise RuntimeError("Could not download this font" + (f" ({errors[-1]})" if errors else "") +
                               ". Download the .ttf yourself and use 'Choose a font file...'.")
        ttf.write_bytes(data)
    return str(ttf), (fetch_license(family, folder) if with_license else "")
