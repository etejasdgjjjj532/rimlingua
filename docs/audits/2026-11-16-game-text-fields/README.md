# RimWorld string fields by owning class

- RimWorld version: `1.6.4871 rev598`
- Assembly: `Assembly-CSharp.dll` (15767552 bytes)
- SHA-256: `082db1dd4f7f1d0b72960d7e1beead8fbfe6957200e8627f65bda0dbbe1dd8f8`
- Method: static ECMA-335 metadata read; no code executed (`tools/dump_game_text_fields.py`)

Static metadata only. An attribute states what the game declares, not what a player sees in a given build.

## Data files are not distributed

The original audit shipped `fields.json` (every string field of every class, with owner, base class and attributes)
and a full per-class table of the `[MustTranslate]` / `[MayTranslate]` fields. Both are derived from the game
assembly and are therefore not distributed here. Regenerate them from your own installation with
`tools/dump_game_text_fields.py`. Only the aggregate counts and a few examples are kept below.

## Counts

| group | all classes | Def classes |
|---|---:|---:|
| [MustTranslate] | 398 | 174 |
| [MayTranslate] | 13 | 6 |
| string, no attribute | 1353 | 52 |
| [NoTranslate] / [Unsaved] | 340 | 149 |

Classes with at least one string field: 1043 (122 are Defs).

## Examples of fields carrying [MustTranslate] or [MayTranslate]

The original table had roughly 140 owner classes. A few examples (owner, base class, attribute: fields):

| owner | base | attribute | fields |
|---|---|---|---|
| `Verse.Def` | `Verse.Editable` | MustTranslate | description, label |
| `RimWorld.IncidentDef` | `Verse.Def` | MustTranslate | diseaseLethalLetterText, letterLabel, letterText |
| `RimWorld.ConceptDef` | `Verse.Def` | MustTranslate | helpText, helpTextController |
| `RimWorld.BackstoryDef` | `Verse.Def` | MustTranslate / MayTranslate | title, titleFemale, titleShort, titleShortFemale / baseDesc |
| `Verse.Grammar.RulePack` | `System.Object` | MustTranslate / MayTranslate | rulesStrings[] / rulesFiles[] |

The fields named in the 2026-11-16 extraction-recall audit (for example `FactionDef.leaderTitle`,
`HediffDef.labelNoun`, `ResearchProjectDef.discoveredLetterText`) are all present in this metadata; see
`docs/audits/2026-11-16-extraction-recall/README.md`.
