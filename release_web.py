import argparse
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"


def read(path):
    return path.read_text(encoding="utf-8")


def versions():
    desktop = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', read(ROOT / "themebuilder" / "__init__.py")).group(1)
    web = re.search(r'BUILDER_VERSION\s*=\s*"([^"]+)"', read(WEB / "js" / "version.js")).group(1)
    return desktop, web


def changelog():
    text = read(WEB / "js" / "changelog.js")
    entries = []
    for block in re.finditer(r'version:\s*"([^"]+)",\s*date:\s*"([^"]+)",\s*changes:\s*\[(.*?)\n\s*\],', text, re.S):
        notes = re.findall(r'^\s*"(.*)",\s*$', block.group(3), re.M)
        entries.append((block.group(1), block.group(2), notes))
    return entries


def check():
    desktop, web = versions()
    problems = []
    if desktop != web:
        problems.append(f"The desktop tool is {desktop} but the web Builder is {web}. Bump both together.")
    entries = changelog()
    if not entries:
        problems.append("web/js/changelog.js has no entries.")
    elif entries[0][0] != web:
        problems.append(f"The newest changelog entry is {entries[0][0]} but the Builder is {web}. Add notes for {web}.")
    return web, entries, problems


def main():
    ap = argparse.ArgumentParser(description="Cut a Menu Theme Builder web release into the website repo working tree.")
    ap.add_argument("--site", help="Path to the website repo (ObnoxiouslyNoxious.github.io). Omit to only check.")
    ap.add_argument("--folder", default="MenuThemeBuilder", help="Folder name inside the website repo (default MenuThemeBuilder).")
    args = ap.parse_args()

    version, entries, problems = check()
    if problems:
        print("Not ready to release:")
        for p in problems:
            print(" -", p)
        return 1

    notes = ROOT / "RELEASE_NOTES.md"
    _, date, items = entries[0]
    notes.write_text(f"# Menu Theme Builder {version}\n\n{date}\n\n" + "\n".join(f"- {i}" for i in items) + "\n", encoding="utf-8")
    print(f"Version {version} is consistent. GitHub Release notes written to {notes.name} (tag v{version}).")

    if not args.site:
        print("Checks only. Pass --site <path to the website repo> to copy the page.")
        return 0

    target = Path(args.site) / args.folder
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(WEB, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    print(f"Copied web/ to {target}. Review and commit it in the website repo (the Author does that).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
