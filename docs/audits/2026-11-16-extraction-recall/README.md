# Extraction recall with and without game type information (2026-11-16)

Static analysis only. Nothing here was observed in a running game.

- Game: RimWorld 1.6.4871 rev598, `Assembly-CSharp.dll` SHA-256 `082db1dd4f7f1d0b72960d7e1beead8fbfe6957200e8627f65bda0dbbe1dd8f8`
- Corpus: the 558 pinned public repositories of `tools/corpus/manifest.json` (`python tools/fetch_corpus.py --split dev`); 553 contain a mod the scan can read.
- Truth: DefInjected keys of the community translations shipped inside each mod, compared by Def name, first path segment and field name.
- Tools: `tools/precision_bench.py --schema {game,builtin,mod,none}`, `tools/compare_recall.py`, `tools/recall_gaps.py`.

## What is counted

449 of the 553 mods ship community translations. 12 of those are repositories that hold only translations of other
mods and have no Defs of their own (88,991 keys, half of all truth keys). They say nothing about extraction and are
left out. The remaining 437 mods have 86,320 community-translated keys. (A machine-readable summary of this run was
produced alongside the original report; it also lists the excluded repositories by name and is not distributed
here. Its aggregate numbers are the ones in the table below.)

## Result

| condition | type information | pooled recall | per-mod median | mods under 50% | unattributed values equal to a known Def/Keyed name |
|---|---|---:|---:|---:|---:|
| game | game assembly + mod DLLs + Core XML | 75.7% | 89.5% | 61 | 193 |
| builtin, before the name list | shipped field table + mod DLLs | 75.1% | 88.5% | 63 | 1005 |
| builtin, with the name list | same, plus shipped Def/Keyed names | 75.1% | 88.5% | 63 | 190 |
| mod | mod DLLs only (previous route without a game) | 71.2% | 83.8% | 77 | not counted |
| none | no CLR metadata | 70.6% | 82.7% | 78 | not counted |

The built-in table closes the gap between "no game" and "game" from 4.5 points to 0.6 points of pooled recall.
The first version of the table extracted 812 more reference values than the game route, mostly
`allowedTerrains` lists of vanilla terrain Def names in mod classes. Shipping the game's Def and Keyed names
removed them at a cost of 5 hits out of 64,487.

The "proven reference" column of `precision_bench.py` overstates false extraction: most of its hits are
attributed `label` fields whose text happens to equal a Def name. The last column above counts only unattributed
or heuristic fields, where equality with a Def name means the value is a reference.

## Why keys are missed with the game's type information

19,088 of the 86,320 keys are not extracted under the `game` condition. Each was looked up in the mod's own XML:

| cause | keys | share | in scope |
|---|---:|---:|---|
| No Def of that name in the folders active for the scanned version, and none anywhere in the mod | 12,302 | 64.4% | no |
| No such Def in the active folders, but one in another version folder | 2,978 | 15.6% | no (other version) |
| The Def exists but neither it nor its in-mod parents write the field | 3,264 | 17.1% | no (no English source) |
| The Def carries MayRequire and loads only with another mod | 232 | 1.2% | no (by design) |
| Field written, class unreadable, reported as `unknown-field` | 208 | 1.1% | partly |
| Field written, no diagnostic (abstract Defs with a defName, conditional list items) | 62 | 0.3% | no |
| Field only on an in-mod XML parent | 26 | 0.1% | yes |
| Field written, rejected as an internal value | 16 | 0.1% | review |

Of the 12,302 keys with no Def anywhere, at least 4,876 have names the game generates in code (`Make_*` 3,188,
`Frame_*` 854, `Blueprint_*` 564, `Administer_*` 270); the rest belong to other mods or to Defs the mod no longer has.

Keys whose English source exists in the scanned version and were still missed: 312 (208 + 62 + 26 + 16), 0.4% of
the truth keys. Measured against keys that have a source in the scanned version, recall is
65,014 / (65,014 + 312) = 99.5%.

The 208 `unknown-field` keys are fields a mod's own Def class declares when the class cannot be read. Source
repositories do not ship compiled DLLs, so this is common in the corpus and rare for installed Workshop mods.
Examples: `CombatExtended.AmmoCategoryDef.labelShort` (44), `RimWorldAccess.ConceptHelpOverrideDef.helpText` (62),
`AlienRace.PawnBioDef.name.first/last/nick` (39). After this measurement the scan was changed to apply the short
list of known text field names to the top level of such a Def, which covers `labelShort`; `helpText` and the name
parts stay diagnostics because matching them would be a match by name alone. That change is covered by a unit test
but the corpus was not measured again after it (it was re-measured on 2026-11-18, see below).

## Fields named in the handover

All are present in the game metadata with their owner (see `docs/audits/2026-11-16-game-text-fields/README.md`):
`IncidentDef.letterText/letterLabel`, `HediffDef.labelNoun`,
`FactionDef.pawnsPlural/pawnSingular/leaderTitle/fixedName`, `ConceptDef.helpText`, `GameConditionDef.endMessage`,
`ResearchProjectDef.discoveredLetterTitle/discoveredLetterText`, `PawnKindDef.labelMale/labelFemale`,
`WorkTypeDef.gerundLabel`, `SitePartDef.approachOrderString/approachingReportString`,
`MentalStateDef.baseInspectLine`, `BackstoryDef.title/titleShort` carry MustTranslate; `BackstoryDef.baseDesc`
carries MayTranslate; `HediffCompProperties_TendDuration.labelTendedWell/labelTendedWellInner` are plain strings.

## Open findings

- List items are keyed by index (`stages.0.label`). The official Japanese translation shipped with the game keys
  them by handle (`AlcoholAddiction.stages.withdrawal.label`: 149 HediffDef stage keys, 850 ThoughtDef stage keys,
  355 ThingDef tool keys, none by index). The handle fields are `untranslatedLabel` and similar, marked Unsaved and
  TranslationHandle in the metadata; only `BodyPartRecord` was handled at the time. Changing this renames keys in
  existing projects, so it needed a migration decision first.
  Implemented on 2026-11-17 (key match measured statically; HediffDef/ThoughtDef stage labels checked in a running
  1.6 game, where index keys were also applied): see `docs/audits/2026-11-17-handle-keys/README.md` (match against
  the official keys).
- The built-in table is RimWorld 1.6. It is also applied to scans of 1.1-1.5 when no installation of that version
  exists. Field sets differ between versions; the scan marks such results `game-version-context-unverified`.
- The list of unextracted items is dominated by non-text: an unlimited scan of one large mod for 1.6 records 12,482
  `unknown-field` diagnostics (class names, single-character map symbols, Def names) and the default limit of 1,500
  is reached. Numbers and known Def/Keyed names in scalar fields are no longer listed; the rest is unchanged.

Re-measured on 2026-11-18 after the handle-key and `labelShort` changes, with the generated-Def keys (`Make_*`,
`Frame_*`, ...) checked against the official Japanese translation: `docs/audits/2026-11-18-extraction-recheck/README.md`.

## Update: the table is no longer shipped

The built-in field table measured above was first bundled with the package. It is now built on the user's machine
from the installed game (`rimworld_translator.schema.game_table_schema`) and cached outside the program, so nothing
derived from the game is distributed. Extraction for a version with no matching installation gives the same result
as the "builtin" rows when a game of another version is installed; with no game at all there is no table and the
MOD-DLL-only figures apply. Sharing one cache between projects also avoids reading the game assembly (about 11 s)
for every new project.
