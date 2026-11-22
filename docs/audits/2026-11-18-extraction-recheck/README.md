# Extraction re-check after handle keys (2026-11-18)

Static analysis only, except where a running game is named. Same corpus, game and tools as
`docs/audits/2026-11-16-extraction-recall/README.md` (558 pinned repositories, RimWorld 1.6.4871,
`tools/precision_bench.py --split dev --schema game`). Raw results were kept in an untracked local directory and are
not distributed.

## Recall after the handle-key and `labelShort` changes

| run | code | DefInjected entries | truth hits | pooled recall | per-mod median | mods under 50% |
|---|---|---:|---:|---:|---:|---:|
| 2026-11-16 | before handle keys | 105,992 | 65,014 | 75.7% | 89.5% | 61 |
| 2026-11-18 | main, after handle keys | 105,944 | 65,056 | 75.8% | 89.6% | 61 |

19 mods changed. The +42 hits are mostly the `labelShort` change of 2026-11-16, which had not been measured: 34
`CombatExtended.AmmoCategoryDef.labelShort` keys in one Combat Extended add-on repository.

The one mod that lost hits (`AobaKuma__Dead-Man-Switch-MobileDragoon`, -2 hits, -29 entries) was checked key by key
with the code before and after the handle-key change. The old scan wrote every melee tool and verb twice: once by
index (`DMS_Dragoon_Sword.tools.0.label`) and once by handle (`DMS_Dragoon_Sword.tools.poke.label`). Only the handle
form remains, which is the form the mod's own community translations use. No player-visible text was lost. The
other mods with fewer entries show the same pattern (`OrionFive/Hospitality` -31 entries, no change in hits).

## Duplicate entries for comps whose handle only the English catalog names

RimWorld keys a `comps` item by its `compClass`, which the comp's constructor usually sets; the XML leaves it out,
so the scan cannot recover it from metadata and uses the index (`DMS_Apparel_MissilePod.comps.1.chargeNoun`). When
the mod ships an English DefInjected catalog with the real key
(`DMS_Apparel_MissilePod.comps.CompApparelReloadable.chargeNoun`), the catalog key became a second, unlinked entry
for the same text: a translator saw it twice.

Fix: when a catalog key has no exact match, the scan looks for exactly one entry whose key differs only in one index
segment and whose English text is equal. That list item (all its fields) is then keyed by the catalog's handle and
keeps the index key as `legacy_keys`, so existing projects carry their translations over on rescan. Different text,
or more than one candidate, leaves both entries as before. In the Dead-Man-Switch mod this removes 4 duplicates and
adds nothing. Tests: `tests/test_handle_keys_extraction.py` (`CatalogHandleForUnknownHandleTests`). Corpus-wide
effect: 1 of 553 mods changed, 4 entries fewer, hits and recall unchanged (65,056; 75.8%). Source repositories
rarely ship an English catalog with comp keys, so installed Workshop mods may be affected more often; that was not
measured.

## Keys of Defs the game generates are not a recall gap

The 11-16 audit lists 12,302 community keys whose Def exists nowhere in the mod, at least 4,876 of them for Defs the
game generates (`Make_*` 3,188, `Frame_*` 854, `Blueprint_*` 564, `Administer_*` 270). The official Japanese
translation shipped with RimWorld 1.6 (read only) has:

- 15 `RecipeDef` keys named `Make_*`. Each of the 15 is an explicit `<defName>` in the game's XML, not a generated
  recipe.
- No `Frame_*` or `Blueprint_*` keys.
- Keyed templates for the generated names: `RecipeMake`, `RecipeMakeJobString` and `RecipeAdminister`, each a short
  template taking the item label as its argument.

Generated recipes, frames and blueprints take their names from these templates and the translated item label, so a
translation MOD does not need keys for them. The editor correctly does not extract them. Not verified in a running
game for MOD items.

## Other misses checked by hand (all correct behaviour)

| case | finding |
|---|---|
| A medical-supplies mod, a drug cabinet Def (`label`/`description`, "no diagnostic") | A `PatchOperationFindMod` removes the Def when RimFridge is not active. The scan applied that patch. |
| An aquarium mod, `AQBeauty*.label` ("field only on an in-mod parent") | The inherited label is a single space on invisible, unselectable helper things. Nothing to translate. |
| A Combat Extended add-on, one toxic grenade ammo Def | `MayRequire="Ludeon.RimWorld.Biotech"`. The benchmark scans without an active-MOD list, so DLC-gated Defs are left out with a `conditional-context` warning. The editor reads the game's `ModsConfig.xml` and includes them when the DLC is active. |

## The 208 `unknown-field` keys

The 11-16 audit counts 208 community keys whose field is written in the mod's XML but whose class could not be
read. Re-scanning those mods with the current code (case-insensitive key match):

- 44 are now extracted: the `CombatExtended.AmmoCategoryDef.labelShort` keys (top-level known text field names
  applied to unreadable classes).
- 164 remain. Almost all belong to classes defined in another mod the target depends on: `RimWorldAccess` 62,
  `AlienRace` 45, `UniqueWeaponsUnbound` 15, `PipeSystem`/`VFEProps`/`VFEPirates` (Vanilla Expanded Framework) 21,
  `HugsLib` 10, `JecsTools` 1, `CombatExtended` 3. Corpus repositories ship no dependency DLLs, and the benchmark
  scans each mod alone. The editor itself adds the Assemblies of the user's active mods to the type information
  (`gui.scan_schema`, `scan_context.context_sources`) when a game of the scanned version is installed.
- Checked for HugsLib, whose DLL is in the corpus: with it as context, the four `rheirman` mods extract
  `UpdateFeatureDef.content` and `modNameReadable` ("what's new" dialog). Vanilla Expanded Framework and AlienRace
  are not in the corpus or installed here, so their fields were not checked this way.
- 6 keys use lower-case Def element names (`gameConditionDef`, `jobDef`) or fields of other shapes. Whether the game
  resolves a lower-case element name was not checked; they stay diagnostics.

That check found a false entry: HugsLib `UpdateFeatureDef.linkUrl`, an unattributed string whose value is a URL, was
extracted as text. A whole value that is one `scheme://` or `www.` address is now an internal value
(`text_semantics.classify_value`; `tests/test_text_semantics.py`). Corpus-wide this changes nothing (0 mods),
because such fields only become entries when a dependency's DLL is part of the scan.

## Not done

- No running-game check of the catalog-handle rename (the 1.6 game applied both index and handle keys in the
  2026-11-17 live test, so the rename changes which key is written, not whether the text applies).
- Fields of Vanilla Expanded Framework and AlienRace classes with those frameworks installed (not available here).
- A corpus run with each mod's dependencies as context; the benchmark has no dependency resolution.
