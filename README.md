# Menu Theme Builder

Desktop tool (PySide6) to create and edit main-menu themes for the **Menu Theme Framework** (Project Zomboid, Build 42).

## Run
    pip install PySide6-Essentials
    python main.py          (or double-click run.bat)

Only PySide6 is needed (no Pillow, no audio libraries).

## What it does
- **Create** a theme: backgrounds slideshow, music (.ogg only), optional Bink video, logos, layouts
  (Zomboid / Strip / Carousel / Horizontal Cards / Vertical Cards), card pictures, credits.
- **Edit** a theme made with the tool: *Open…* lists every theme found in your Workshop folder.
- **Import** any other menu-theme mod folder (best effort, see below) via *Open → Open / import another folder…*.
- **Save & Build mod** (Ctrl+S) writes the complete mod to
  `…/Zomboid/Workshop/<ThemeID>/Contents/mods/<ThemeID>/` (plus `preview.png`), ready to enable in-game.
  Nothing is uploaded to Steam.

The Workshop folder defaults to `~/Zomboid/Workshop`; change it with *Set Workshop folder…*.

## Notes
- All images are saved as PNG (JPG/BMP/WebP are converted automatically).
- Music and video sounds must be `.ogg`. Their length is read from the file.
- Videos must be Bink 1 `.bik` (convert with RAD Video Tools). Size and length are read from the .bik header.
- The tool keeps its project in `ThemeProject.json` next to `Contents/` (it is not uploaded to Steam).
  Saving regenerates `<PREFIX>_Theme.lua`, `<PREFIX>_Config.lua`, the sound script, `mod.info` and the EN translation file.
  **Do not hand-edit those Lua files** - changes would be overwritten the next time you save from the tool.
- Importing a theme that was not made with this tool does NOT carry over custom Lua code (painters, intro sequences,
  button fonts, hooks). The import is saved as a new mod (`<id>Edited`); the original is never touched.
- Not covered yet: button fonts, intro sequences, custom painters, translations (UI texts are English only for now,
  but they are written as translation keys in `Translate/EN/IG_UI.json`, so other languages can be added later).

## Credits
Menu Theme Builder was created by [JFlowersB](https://github.com/JFlowersB) (Agente_FLOWERS on Steam), who wrote the original tool and handed it over to the Menu Theme Framework project. It is now maintained by [ObnoxiouslyNoxious](https://github.com/ObnoxiouslyNoxious) in the NoxMods organisation. Contributions are welcome by fork and pull request.

## Licence
MIT, see [LICENSE](LICENSE). Copyright (c) 2026 JFlowersB and MenuThemeBuilder contributors.
