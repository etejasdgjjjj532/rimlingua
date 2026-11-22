# List items keyed by handle, measured against the official Japanese keys (2026-11-17)

The first sections are static analysis. The last section, "Live check in the game", was observed in a running game.

- Game: RimWorld 1.6.4871 rev598, Linux. Core's own Defs are scanned in place; the game is only read.
- Truth: the DefInjected keys of the official Japanese translation shipped with the game (the Japanese language
  archive under `Data/Core/Languages/`, read in memory), compared as exact strings.
- Tool: `tools/compare_handle_keys.py` (`python tools/compare_handle_keys.py --out artifacts/handle-keys/result.json`).
  It scans the same Defs with the same metadata twice: with the rule that copies `untranslatedX` from `X` (list
  items keyed by handle) and with the rule switched off (list items keyed by index, the scan before this change).
- The change measured is the handle-keyed list item rule of the extractor (design notes were kept privately).

## Result

| Def type | official keys | matched, index keys | matched, handle keys |
|---|---:|---:|---:|
| HediffDef | 607 | 382 | 531 |
| ThoughtDef | 850 | 0 | 845 |
| TraitDef | 131 | 0 | 131 |
| PawnKindDef | 201 | 152 | 200 |
| RoomStatDef | 50 | 11 | 50 |
| TerrainDef | 87 | 71 | 87 |
| ThingDef | 1,940 | 1,452 | 1,816 |
| StatDef | 387 | 364 | 368 |
| all Def types | 11,690 | 8,569 | 10,165 |

The other Def types are unchanged by the rule. "Matched" counts official keys that the scan also writes; it does
not say the text is right, only that the key can reach the game.

## What is still not matched

Causes were checked in Core's XML only where stated.

- Defs and list items that load only with another mod (`MayRequire` / `MayRequireAnyOf`): checked for one apparel
  Def (`MayRequireAnyOf` Royalty/Biotech) and for one stage of two thought Defs (`MayRequire` Biotech). The scan
  covered Core alone with no expansion active, so these are left out by design, as in the earlier audits.
- A field the official translation fills in although the English Def has no such text: checked for the
  `description` of one HediffDef stage (the stage has a label only).
- Component fields named by the component class, for example `AcidBurn.comps.HediffComp_GetsPermanent.permanentLabel`,
  `Bite.comps.HediffComp_TendDuration.labelTendedWell` and `ArchotechArm.comps.HediffComp_VerbGiver.tools.fist.label`.
  Not investigated; the component handle probably comes from `compClass`, whose default the metadata does not
  provide (the existing guard in `extraction.py` leaves it alone). Separate piece of work.
- Other unmatched keys, for example `StatDef` `description` / `formatString` of some stats, `PawnKindDef Cow.labelFemale`,
  `ThingDef` `verbs.Verb_Shoot.label`: not investigated.

Up to 20 unmatched keys per Def type are in the tool's JSON output.

## Not checked

- Versions other than 1.6. The rule is applied only when the type information comes from a game of the scanned
  version; which older versions already use handle keys is not established.
- Royalty and Biotech Defs (the tool scans Core only).
- Keyed and Strings keys.
- Handle keys on MOD Defs other than our own test MOD, and Defs of the other list classes (tools, verbs, life
  stages, trait degrees): the live check below covers HediffDef and ThoughtDef stage labels only.

## Live check in the game (2026-11-17, added after the first version of this audit)

`tools/verify_handle_keys_live.py` writes a small MOD of our own (HediffDef and ThoughtDef with stages), scans it
with the game's field table, exports a Japanese translation MOD with the editor's own export, and starts a
disposable copy of RimWorld 1.6.4871 rev598 (offline, own profile) with the diagnostic window of `tools/runtime_probe`,
which reads the stage labels the game loaded. Static evidence for the key shape is above; this is the running game.
It is a diagnostic window, not a gameplay screen. The original game, Workshop and real profile were only read
(`original_profile_unchanged`).

| Stage | Key written | Loaded in the game |
|---|---|---|
| Hediff "Initial" | `stages.Initial.label` | translated |
| Hediff "Severe pain" (space) | `stages.Severe_pain.label` | translated |
| Hediff "Worse" twice | `stages.Worse-0.label`, `stages.Worse-1.label` | both translated, each to its own text |
| Thought "Cheerful", "Gloomy" | `stages.Cheerful.label`, `stages.Gloomy.label` | translated |
| Control hediff, index key written by hand | `stages.0.label` | **also translated** |

Result: all six handle-keyed translations are applied, including the duplicate-label suffix and the space becoming
`_`. **The premise of the design was wrong for this field:** the game also applies the index-form key
(`stages.0.label`), so the old export was not silently ignored here. What the change gives is the same key names as
the official translation (and, by reasoning not observed here, keys that stay with their item when a MOD update
inserts or reorders list items). It is not a fix for text that failed to show. Whether index keys apply to the
other list classes was not checked.

### Real Workshop MODs

The same script with `--source <MOD folder> --dependency <Harmony folder>` copies a real MOD, translates the stage
label of up to six distinct HediffDef/ThoughtDef Defs under their handle keys (the stage index the probe reads
comes from the entry's recorded index-form key) and reads the loaded labels in the disposable game. Source folders
were only read.

| MOD | Checked | Applied in the game |
|---|---|---|
| Save Our Ship 2 (Workshop 1909914131) + Harmony | 6 Defs (including some with spaces in the handle) | 6 / 6 |
| One addon MOD (Workshop 3550544871) + Harmony | 1 Def (the other stage Defs sit under Biotech or MayRequire folders that were not active) | 1 / 1 |

Also, the read-only pool check (`tools/verify_installed.py`: 19 installed Workshop MODs and Core, scan, independent
export check, source files unchanged) passed 20 / 20 on 2026-11-17, and the full regression suite passed (863
tests, 1 skipped). These do not cover every MOD, and the diagnostic window is not a gameplay screen.

### Shared set for all versions

`export_shared` writes one root `Languages/` set (no version folders, no `LoadFolders.xml`). With the test MOD
declaring 1.4 and 1.6 (`--shared`: 1.4 scanned with another version's table, so it keeps index keys; 1.6 has handle
keys) the output carries **both** key forms of each item (12 keys for 6 items). Started in the 1.6 game: all 6
translations applied, none lost to the duplicate keys. Separately, an index key and a handle key for the same field
loaded together (the index key in a mod loaded later) gave the handle key's text. Not checked: a game older than
1.6 reading this set (no such game is installed), and the unexplained "translation data errors" count, which varied
between runs (36, 27, 37) and was not read.

The game log of the first (own test MOD) run above says "Translation data for language Japanese has 27 errors". The
same disposable game started with only the base game active (no test MOD, no translation MOD) said 36 errors, so
these errors are not caused by the test MOD. Why the count differs by nine between the two runs is not explained.
What the errors are was not read: calling `LanguageReportGenerator.SaveTranslationReport()` from the probe wrote no
report file (not investigated further and the probe change was dropped), and the in-game "Generate translation
report" button was not pressed.
