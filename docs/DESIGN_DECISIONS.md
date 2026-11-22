# Design decisions

This document merges three product-level documents: the confirmed design decisions (Q1 to Q20), the multi-version end goal, and the player-visible localization priority. It was translated from the maintainer's original notes (dated October and November 2026).

**A decision recorded here is a product specification, not a statement that it is implemented.** Tests and other docs refer to individual decisions by number (for example "Q17"), so the numbering is kept exactly.

Precedence: the player-visible localization priority (last part) takes precedence over any older wording that implies exhaustive extraction. It augments the confirmed decisions and the safety rules; it does not replace them.

---

## Part 1. Confirmed design decisions

Source: the maintainer's confirmed answers to 20 design questions (answers given 2026-10-14/15; Q17 answered 2026-11-15; Q16 amended 2026-11-17).

### Top-level premises and constraints

- **One source mod is translated at a time.** When translating mod A, prerequisite mod B, compatibility mod C, DLCs and libraries may be read as analysis context. The editor is not a multi-mod bundle project that translates B or C without being asked. Text that A adds to B's Defs is the exception: it is managed as a conditional translation candidate created by A (Q9). A translation project and the generated translation mod correspond to one target mod.
- **Existing third-party extraction tools are limited to analysis and comparison during development.** No library, executable, code, wrapper or call integration of such tools may be placed in the product, its distribution or the output translation mod, and none may be an install requirement. General extraction rules learned from analysis may be reimplemented as the project's own independent code, respecting legal requirements. The product must work standalone. Measured comparisons with competing tools happen only in an isolated development environment.
- **All versions declared by the source mod (`supportedVersions`) are eventually extracted individually**, and a **single multi-version translation mod** is output. Each version's data is protected independently. Future versions such as 1.7, 1.8, 1.9 and 1.10 are read without hard-coding.
- Checking combinations of prerequisite mods (Q3) is only an exploration of analysis contexts for finding the additional translation keys of the one source mod being translated. It is not an intention to translate the prerequisites together.
- No paid services or billing APIs, no unauthorized reuse of other authors' code, prerequisite mods are obtained only from legitimate free sources, and Workshop/Steam content and normal saves are protected. Heavy computation is to be controlled on low-memory machines (about 8 GiB).

### The answers

**Q1 = A: Supported versions follow the source mod's declaration.**
If About.xml declares 1.4/1.5/1.6 and a 1.3/ folder also exists, only 1.4/1.5/1.6 are formal extraction and output targets. 1.3 may be logged as undeclared but is not added to the supported versions. This is distinct from deciding which folders are active under LoadFolders and similar rules.

**Q2 = C: Put versions with insufficient legacy material on hold and process versions that have material first.**
If 1.2 to 1.6 are declared and there is no CLR material for 1.2, record 1.2 as incomplete/unverified and prioritize later versions that can be analyzed. If a version in the example (1.3 to 1.6) itself lacks material, hold it in the same way. Never silently mark an old version as "supported". The end goal of supporting all versions does not change.

**Q3 = C: Investigate combinations of conditional prerequisite mods.**
Check valid dependency configurations such as standard, A only, B only and A+B. If five keys appear only under A+B and originate from the source mod, extract them. To prevent combinatorial explosion, narrow valid configurations by dependency conditions; configurations beyond the processing limit are explicitly reported as "not investigated". The safety limit on execution is set by the coordinator; never enumerate without bound.

**Q4 = A: PatchOperations are handled by statically applying the XML patches.**
If A adds the text "can be repaired quickly" to B's Def description, statically compute PatchOperations, patch order and dependencies, and treat that text as A's translation target. If the patch cannot be statically reproduced, record it as unverified. Real-game verification as a separate step is not forbidden, but the main patch-analysis method is static.

**Q5 = A: Apply the existing generic rules to future versions immediately.**
If the declared versions are 1.6/1.7/1.10, also generate scan candidates for the not-yet-seen 1.7 and 1.10, and label them "new rules, not verified in the game". Compare version numbers numerically, not lexicographically (1.10 > 1.9). This is separate from any guarantee of support.

**Q6 = C: Unknown XML fields go to an unconfirmed candidate list.**
A sentence that looks like display text in `tooltipText` ("movement speed increases") is placed in the translation candidate list. If independent evidence shows that it is translatable, it moves to the normal list. This avoids confusion with configuration values that rewrite real data.

**Q7 = A: Strings, WordLists and similar files get a dedicated analyzer per format.**
For a Strings/WordLists/Names.txt file with 200 lines, read it with an independent parser that understands the format and generate the corresponding file per version. Do not translate every generic file wholesale and risk false extraction. Formats without support are recorded in diagnostics.

**Q8 = B: Statically analyze C# DLLs down to IL instructions.**
Investigate calls to `Translate` in `MyMod.Warning` and literals such as "oxygen shortage", and list places that may be usable for translation as candidates with evidence. Do not translate every DLL string indiscriminately. Never execute external DLLs and never modify them. If a string in code is not an XML translation key, do not assert that it can be overridden by the translation mod's XML; classify it as unsupported / requires additional implementation.

**Q9 = B: Text that A adds to B is a conditional translation target on A's side.**
If A's patch adds "electric attacks are possible" to B's weapon description, it becomes a candidate of A's translation in contexts where B is present. B's original text and B's own translation are not part of A's scope. Investigate per-version load order, original Def ownership and conflicts, and verify whether it can actually be applied.

**Q10 = C: Other tools are used for development, and measured if they can be run.**
With this tool at 520, the reference RimTrans at 540 and another tool at 505, comparators that can be run are measured at key level, and ones that do not work are studied through source/documentation. Reports state whether a result is measured or a design reference. Other people's tools are never integrated, embedded or made a runtime dependency.

**Q11 = B: Manual import from existing Japanese translation mods.**
For `WeaponABC.label = Plasma Rifle` with a reference translation, show a translation candidate with license and provenance. Import only the translations the user explicitly selects. If the rights terms are unclear, the text cannot be reused automatically.

**Q12 = B: Sharing a translation to other versions with the same key and same source text happens only after approval.**
If `Rifle.label` = "assault rifle" in 1.4/1.5/1.6 and only 1.6 is translated, propose applying it to 1.4/1.5, and change the translation only for the versions the user selects. Approval state also stays independent per version.

**Q13 = A: When the source text changes, keep the old translation as "needs review".**
For example, 1.5 "steel armor" was translated and 1.6 is "reinforced steel armor". Keep the old translation as a candidate marked "source changed / needs review". **Do not treat the old translation as approved for the new source; formal output requires re-review.**

**Q14 = A: Keep history for retired keys per version.**
If `LaserGun.label` exists only in 1.4, output it only for 1.4 and not for 1.6. Do not delete the translation history of the older version.

**Q15 = A: The formal extraction/edit list contains only confirmed targets.**
If it cannot be decided whether "Emergency Mode" is a UI string or an internal setting value, do not put it in the normal list; leave it in the diagnostic log as insufficient evidence. To avoid contradicting the dedicated candidate list of Q6, the provisional interpretation is: items with grounds for suspicion go to the candidate screen, items with weak grounds that look like internal values go to the diagnostic log only, and neither is part of formal output. (See the consistency notes below.)

**Q16 = A: Output independent translation XML for every version.**
If 1.4 and 1.5 have 300 keys each and 1.6 has 320, output the full set into each version's own Languages folder. Do not optimize by sharing through Common. Generate LoadFolders.xml so that each version loads only the files it needs. Do not mix version-specific keys into other versions.

> **Amendment (2026-11-17; the maintainer asked "can it be made so that all versions refer to it?" and chose "one set common to all versions"):** The GUI's formal output is not per-version folders plus LoadFolders. It writes one set into the root `Languages/` folder that all versions read (`core.export_shared`). The keys are the union of the versions that are ready; if the same key has different translations, the newer version's translation is adopted and the user is notified. The Q16 phrase "do not mix version-specific keys into other versions" is therefore not honored by this output (unneeded keys are ignored by the game). Q12 (sharing between versions only after approval) is kept for the editing state, but the merge at output time follows the rule above automatically. Q17 (do not output held versions) is kept. The per-version export (`export_versions`) remains in the code.

**Q17 = A: Output only the completed versions first (answered 2026-11-15).**
If it is unclear whether the 15 keys of 1.3 are translatable, formally output only 1.4 to 1.6. The output mod's About.xml `supportedVersions` and LoadFolders.xml list only the versions that were output. 1.3 is recorded as "unverified (held)" with the reason, and kept in the screen, the log and `.rimworld-translator.json` (`held_versions`). After it is resolved, re-export to add it. 1.0 is held because its dedicated load rules are unverified. If a version contains even one dangerous translation or an item needing re-review (Q13/Q19), only that version is held and the other versions are still output. If all versions are held, nothing is output. Untranslated keys are not output (the XML is not filled with source-text fallback). Implementation: `core.export_versions`.

**Q18 = A: The source mod is supplied as a local folder or ZIP.**
To translate an unregistered Workshop mod, the user passes a folder or ZIP they obtained legitimately, and one mod is analyzed. This answers the input UI for the translation target; it does not contradict the earlier permission to automatically obtain, from legitimate free sources, the prerequisite mods needed for analysis. A UI that automatically downloads the source mod from a Workshop URL is not a priority.

**Q19 = C: Separate validation for test output and formal output.**
Example: 500 keys, 490 translated, 3 placeholder mismatches, 7 untranslated. For test output, attempt XML output with measures that avoid serious breakage (such as excluding invalid keys) and with warnings. For formal output, block output if even one dangerous translation remains. Whether untranslated keys may fall back to the source text is to be decided next time (separate from Q17). Never silently output incorrect placeholders into XML.

**Q20 = C: Confirmed problems are fixed automatically by an automated assistant, and the coordinator verifies and then integrates into the main line.**
On finding a clear extraction bug: make a minimal fix with a new regression test in a dedicated worktree, have the coordinator review the diff, require that the existing 234+ tests, the relevant mod and unknown holdout mods pass, then reflect it non-destructively into the main line and continue. **Because the main branch had many uncommitted changes at the time, automatic integration that conflicts is prohibited. Never reset, stash, clean or overwrite the original uncommitted changes. Conflicting parts are held on an isolated branch and logged. No public push and no public release.** Commit messages were to be in Japanese at that time (this part of the source is specific to the maintainer's workflow; under the conflicting earlier no-unauthorized-commit rule, safe local preservation of results took priority for the time being, and integration work is allowed as long as it destroys no content).

### Consistency notes

1. **Q6 vs Q15.** Items that look like text but are unverified in CLR (like `tooltipText`) go to a dedicated needs-confirmation candidate list (Q6). Items that are unclear even as UI string versus internal identifier and have weak grounds (like "Emergency Mode") are not shown in the normal translation list and go to the diagnostic log (Q15). Neither enters "confirmed translation data"; both need the user's approval or verification. The boundary between categories uses confidence, type and evidence of use, and is managed by tests.
2. **Q3 vs one mod at a time.** Only A is translated. Dependencies B/C are execution context, and B/C's own ordinary strings are not translated. Strings that A adds to B/C (Q9) belong to A's translation pack.
3. **Q5 vs all supported versions / insufficient legacy material (Q2).** All declared versions are scan targets, but versions with insufficient legacy material are unverified. Future versions only get inferred key generation, and guarantees are staged. Do not declare complete extraction or behavior guarantees merely because metadata says a version exists.
4. **Q12/Q13 vs Q16.** Editing state is separated per version, and translations are shared only after explicit approval. Output is a full set per version (duplication is acceptable; see the Q16 amendment for the current GUI behavior).
5. **Q20 vs protection of user data.** Permission for automatic integration is not unconditional forced overwrite. Integrate only when validation passes and there is no conflict; on conflict, stop or hold on the isolated branch.
6. **Q18 vs fetching dependency mods.** Translating the source mod starts from a user-supplied local ZIP/folder, but the prerequisite mods needed for analysis may be fetched in isolation from free, legitimate sources.

### Open points

Q17 is settled as A (completed versions first). The boundary of Q6/Q15 and the non-conflicting integration of Q20 were presented as safe-side interpretations to avoid contradictions; if the maintainer intended otherwise, the maintainer's intent takes priority.

### Progress note

This part records adopted **design policy**, not that everything is implemented. A full-day production run loop has not been started. The existing real-game test only confirmed a single translation key on 1.6; no all-version in-game verification has been done.

---

## Part 2. Multi-version end goal

Source: the product goal of 2026-10-15. It is not a report that implementation is complete. Formal decisions are in Part 1; the current priority is in Part 3.

Summary of formal decisions: only versions declared by the source mod are formal targets (Q1 A); versions with insufficient material are held and other versions go first (Q2 C); future versions become unverified candidates via generic analysis (Q5 A); copying translations between versions is approval-based (Q12 B); independent full XML output per version (Q16 A, see its amendment); one mod at a time. At the time of writing only Q17 was undecided; it has since been settled as A.

### Top-level goal

**Extract every game version that the source mod supports and output a single multi-version translation mod.**

Maintainer's requirement (2026-10-15): "The final goal is to extract all versions supported by the mod and output them as a multi-version translation mod." This requirement ranks above earlier work such as the extraction audits, unknown-mod checks, comparison with existing Japanese translation mods, comparison of several extraction tools, and prerequisite mod investigation.

### Intended end-to-end workflow

1. Collect `supportedVersions` from the source mod's `About/About.xml`. Analyze `LoadFolders.xml`, the root / `Common` / per-version folders, and the mod's dependencies and DLC conditions.
2. For each declared version (for example 1.3, 1.4, 1.5, 1.6), **independently evaluate the effective Defs, Keyed, patches, inheritance and type information.** Check fallback to version folders, priority between root/Common, LoadFolders instructions, and the fact that 1.0 alone has different load rules.
3. Match prerequisite mods per version too. Sources that are free and legitimate to obtain go into an isolated folder with a recorded hash and provenance. Do not obtain old RimWorld game bodies or DLCs through unauthorized means. Where type information of an old game version is missing, continue static XML analysis and state "type information / in-game verification missing".
4. Keep each version's translation keys, source text, translations and approval state independently. Even for the same key, source text and meaning change between versions, so do not link them automatically. Offer a shared-translation candidate only when sameness can be shown.
5. Compare **per version** with the translations bundled in the source mod, independent Japanese translation mods and other extraction tools, distinguishing missing items, over-extraction, obsolete keys and dynamic strings.
6. Store each version's Languages in one translation mod, and generate `LoadFolders.xml` to control load conditions. `supportedVersions` in About.xml matches the versions that were generated and verified.
7. Machine validation, and real in-game display verification for versions where a game environment exists. Unverified versions are shown as unverified. The translation mod is independent of the source mod, specifies load order, and does not modify the source mod.

### Output image (source mod supporting 1.3 to 1.6)

```
MyMod-Japanese/
  About/
    About.xml                 # supportedVersions: 1.3, 1.4, 1.5, 1.6
    Preview.png
  LoadFolders.xml             # selects each version's Languages
  1.3/Languages/Japanese/DefInjected/ThingDef/Translations.xml
  1.3/Languages/Japanese/Keyed/Translations.xml
  1.4/Languages/Japanese/DefInjected/ThingDef/Translations.xml
  1.4/Languages/Japanese/Keyed/Translations.xml
  1.5/Languages/Japanese/DefInjected/ThingDef/Translations.xml
  1.5/Languages/Japanese/Keyed/Translations.xml
  1.6/Languages/Japanese/DefInjected/ThingDef/Translations.xml
  1.6/Languages/Japanese/Keyed/Translations.xml
  .rimworld-translator.json
```

Folder names and LoadFolders entries and priorities are generated according to the game's actual rules. Sharing through Common applies only to verified common keys. RimWorld 1.0 is special. Keys that exist only in one version are not copied to all versions without checking. (The current GUI's single shared `Languages/` output is described in the Q16 amendment in Part 1.)

### Gaps in the implementation at the time of writing

- `scan_mod(source, game_version=...)` already supports extraction for a single game version, and `resolve_load_folders` resolves per-version / Common / root / LoadFolders.
- However, `core.Project` mainly held a single `game_version` and a single `entries`. It had per-language translations, but **not independent translation state per game version**.
- `core.export_mod` wrote only a single `project.game_version` to About.xml, and output was limited to the root `Languages/`.
- An existing safety test (`test_export_advertises_only_the_scanned_game_versions`, named after the single-version behavior) exists. A multi-version implementation must keep that safety and replace it with new tests that check "declare every version that has real data" and "do not declare versions without data".

### Data model and compatibility

- `project.supported_versions`: the set of versions the source mod declares.
- `project.version_profiles[version]`: the folders actually loaded, the dependency configuration, schema and source hashes, extraction results and diagnostics.
- `project.translations_by_version[version][language][entry_id]`: translation text, review state and original source text, independent per version.
- `project.export_coverage[version]`: extracted, translated, source_verified, xml_validated, game_tested, blockers.
- `project.shared_suggestions`: verified cross-version translation reuse proposals.

Older schema=1 projects must load losslessly, through backward compatibility or a safe migration. Switching versions must not lose translations or approval states, and a change must not propagate wrongly into other versions' translations.

### Required tests

- Cases across 1.3/1.4/1.5/1.6 where the source of the same key changes, a version-only key appears, or a key is removed.
- LoadFolders.xml, Common/, root/, per-version folders, fallback to a later version, and priority when same-named XML overrides.
- RimWorld 1.0 special rules and case sensitivity on Linux.
- Per-version prerequisite mods, DLCs, PatchOperations, ParentName, Keyed/DefInjected.
- Per-version agreement, omissions and over-extraction against existing Japanese translation mods and comparisons with other extraction tools.
- Lossless migration of translations from old projects to the new format.
- A baseline of 108 existing mods, with 10 to 20 unknown mods as an independent holdout to verify generalization.
- The existing regression suite (234+ tests) plus new tests. Real-game checks only for versions that are legitimately owned and can be launched.

### Verification metrics

Report `declared_versions` (versions the source mod declares), `scanned_versions`, `exported_versions`, `xml_validated_versions`, `in_game_tested_versions` and `unverified_versions`, and count per-version omission candidates, confirmed omissions and over-extraction separately. Never claim "works in the game on all versions" from "works in-game on 1.6" alone.

### Compute budget note

The original planning assumed a PC with about 8 GiB of RAM; do not run heavy scans and game launches in parallel.

### Future versions (1.7, 1.8, 1.9, 1.10 and beyond)

Added requirement from the maintainer:

- Do not treat 1.6 as an upper limit. Discover supported versions dynamically from `supportedVersions` in About.xml and from LoadFolders.xml.
- Compare versions as arrays of numeric components, so that 1.10 comes after 1.9, and make 2.0 and similar representable.
- Manage per-version load rules, Def/Keyed/Strings and CLR type information as individual extensible adapters, so that when RimWorld updates, only the rules for the new version need to be added.
- When a new version is added to the source mod, add project data and translations for that version and keep the translations, approvals and review results of all previous versions.
- Write to `supportedVersions` only versions for which translation data actually exists and which can be loaded. The behavior of future versions is not guaranteed until confirmed in the actual game.
- Verify version ordering, diffs, additions, removals, migration and folder separation with synthetic test data covering 1.6 / 1.7 / 1.8 / 1.9 / 1.10 / 2.0.
- This item is a requirement for a design that makes future versions easy to add. It does not mean that the behavior of unreleased versions has already been verified.

This part is a design specification. It does not mean the product can already extract every supported version and output multiple versions.

---

## Part 3. Player-visible localization priority

Source: a maintainer clarification dated 2026-10-23. It **supersedes any older instruction implying that every mod-specific string, non-visible field or behavior must be reverse engineered or translated**. It augments, rather than replaces, the confirmed design answers (Q17 was unresolved when this was written and has since been settled as A), the single-target-mod rule, the multi-version end goal and the safety guarantees.

### The actual goal

> It is enough if item names and the UI become Japanese. For parts with very mod-specific processing, translate them if reference data is available.

**Outcome:** An English mod feels usable in the target language: its items, buildings, jobs, research, buttons, interface and descriptions make sense in play. This is not an instruction to translate or classify every string inside the mod's internals.

### Priority P0: visible, common localization

Extract and allow editing of language-bearing elements that have a known RimWorld-compatible output route, such as:

- names, labels and descriptions of items, weapons, armor, food, buildings, furniture, animals/characters, recipes and workbenches;
- research names/descriptions, bills, hediff descriptions, relevant faction/pawn labels, player-facing messages and tooltips;
- menu/button/tab labels, windows/panels, settings or UI labels, gameplay notifications, guidance and alerts;
- Keyed XML, DefInjected and genuinely player-visible `rulesStrings`. **Preserve syntax, grammar identifiers, placeholders and other non-language parts** (for example the source `subject->` prefix);
- text from the target mod's applicable XML and legitimately generated or modified source text, with correct load-order, patch and version provenance.

A missing player-visible string is high severity, but do not invent an export key or claim gameplay validity without evidence.

### Priority P1: unusual mod-specific UI or dynamic strings, only with enough reliable reference evidence

Examples: custom scripted menus, generated dialogue, specialized event panels, dynamic C# UI, framework-specific localization keys.

- Translate these **if both their display semantics and their actual translation hook/format can be independently established** from valid XML or canonical language catalogs, project code / CLR metadata / CIL use sites, game documentation and, when permitted, isolated game validation.
- Existing translation mods may reveal keys and patterns, but their texts are not automatically licensed for copying and are not a substitute for proving that a key works.
- If the text is real UI but the hook/output mapping is uncertain, show it as an **unverified candidate / needs evidence**, keeping source path, owner, version and the unknown, without exporting it automatically.
- If obtaining enough evidence would require unapproved invasive reverse engineering, undocumented hooks or speculative runtime patching, **defer it** rather than delaying the ordinary item/UI translations.

### Priority P2: not a translation target

Control-flow tags, Def names/IDs, package IDs, save metadata, internal unlock references, texture/asset paths, debug state, serialized objects, schema identifiers and arbitrary `System.String` values are **not** player-facing language by default.

Exclude values proven internal from the translation list and from generated XML. Preserve the source; retain focused audit diagnostics when relevant. Do not treat a large raw-string count as product progress.

### Product/UI acceptance criteria and reporting

1. Present a clear **basic translation workflow**: choose the target mod, scan, see the common player-visible strings, translate/review, save, and output a safe translation mod. Advanced analysis is a separate, optional diagnostic route.
2. Measurement is grounded in **verified player-visible examples**, by version and source, with independent oracles:
   - the number of confirmed player-visible candidate keys found and omitted;
   - the number of non-language values falsely admitted as translatable;
   - the number of optional complex/dynamic candidates with enough evidence to translate;
   - the number of unresolved dynamic UI strings and why (unknown output contract, absent game data, or missing permission).

   Do not use the raw extracted string count, coverage of the 108-mod baseline, or unresolved XML nodes as a proxy for success. A parser cannot guarantee that all runtime text was captured.
3. Stable regular RimWorld exports beat speculative mod-specific behavior: if a complex feature cannot be verified, ship the validated common item/UI strings and surface an honest limitation.
4. The unknown-field policy stays consistent with Q6/Q15: plausible language gets a separate review candidate, weakly indicated or internal-looking values remain diagnostics, and **neither enters formal export without verified translation support**.
5. The multi-version goal, original mod ownership and the Q17 hold still apply: translate only the single chosen mod, preserve translations and approvals per supported version, treat dependencies as analysis context, never rewrite the source mod, never fabricate dynamic translation keys, and never guess unresolved fallback rules.
6. Screenshots and GUI tests should check **what a player can actually translate without expert reverse engineering**, not just expert diagnostics. A technical advanced mode may be optional.

### Work order

1. **First**, verify names, descriptions, UI/Keyed messages and supported plain-text labels on a genuinely unfamiliar mod, record a version-scoped oracle, and make sure the output is valid.
2. **Second**, catch wrong internal values that could corrupt translation XML.
3. **Third**, address custom or dynamic mod-specific GUI text only if source/CLR/catalog/runtime reference proof is sufficient. Do not chase large amounts of uncertain strings at the expense of core usability.
4. **Fourth**, improve error/unknown reporting, non-destructive approval and export, and a straightforward GUI translation workflow, with positive-control tests.

This is a priority clarification, **not** a request to stop code tests, publish, force-merge, push to a public repository, install a dependency, start the game, or resolve Q17 (settled later as A). Existing isolation and original-content protections remain in force.
