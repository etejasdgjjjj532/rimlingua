# Formal multi-version export, checked in the running game

- Date: 2026-11-16
- Game: RimWorld 1.6.4871 rev598 (Core, Royalty, Biotech installed), Linux
- Subject: Save Our Ship 2 (Workshop 1909914131, declares 1.0-1.6), copied; the original folder hash is unchanged
- Tool: `tools/verify_formal_versions_live.py` (`scan`, `export`, `game`); evidence was written under `artifacts/` (not committed, not distributed)
- Diagnostic MOD compiled with Roslyn 4.14.0 from api.nuget.org, package SHA-256
  `941a9cf3ea618d88d01a3dd6b1a45a06bcf07716a9f81ce4031caa3edd24a845`

## Static result (editor and exported files)

| version | entries | translated and approved | export |
|---|---:|---:|---|
| 1.0 | 799 | 0 | held: load rules for RimWorld 1.0 are unverified |
| 1.1 | 1,096 | 0 | held: nothing to export |
| 1.2 | 1,799 | 0 | held: nothing to export |
| 1.3 | 1,921 | 0 | held: nothing to export |
| 1.4 | 2,040 | 36 | written |
| 1.5 | 2,352 | 43 | written |
| 1.6 | 2,535 | 44 | written |

`About.xml` lists 1.4, 1.5 and 1.6; `LoadFolders.xml` maps `v1.4`-`v1.6` to their own folders; each has
`Languages/Japanese/DefInjected/ThingDef` and `Keyed`. Untranslated entries are not written.

## Seen in the running game (1.6 only)

Disposable game copy and profile, no network, active mods: Harmony, Core, the source copy, the exported
translation MOD, the diagnostic window. The values below are `DefDatabase<ThingDef>.label` read inside the game.

- 33 translated ThingDef labels: 20 hold the exported Japanese text; 13 Defs do not exist in this game (10 animal
  Defs and 3 holodeck Defs). Vehicle Framework, a dependency of the source MOD, is not installed here, so the
  source MOD's assembly does not load and those Defs fail to load.
- 40 untranslated ThingDef labels: 8 hold the English source text; 30 Defs do not exist for the same reason; 2
  (`Ship_Beam`, `Ship_Engine`) hold Japanese text. Both are Core Defs that the source MOD redefines, and the text
  is Core's own Japanese translation, not this export.
- A screenshot from the game's framebuffer showed four translated labels in Japanese and three untranslated labels
  in English (kept with the private evidence, not distributed).
- Log: "Translation data for language Japanese has 40 errors" with the export, 27 without it. The 13 extra errors
  equal the 13 translated labels whose Defs are missing.

## Not checked

- Versions 1.4 and 1.5 in a running game (only 1.6 is installed).
- Keyed translations and descriptions in the running game; the diagnostic window reads ThingDef labels only.
- Normal gameplay screens. The window is a diagnostic one.
- The source MOD with all its dependencies present.

## Finding

A Def that redefines a Core Def of the same name is listed as untranslated in the editor, while the game shows
Core's Japanese text for it (`Ship_Beam`: the editor's source text is a short English phrase for the ship hull, and
the game shows Core's Japanese hull term). The editor gives no hint that an official translation already applies.
Severity: low.
