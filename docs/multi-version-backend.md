# Per-version extraction, Project, and test export (round 1)

This feature is a backend API. The full GUI flow for multi-version operations is not connected yet. It scans and edits independently only the versions declared in the About.xml of a single source MOD, and writes per-version XML into a single test translation MOD. No third-party extractor is required.

```python
from pathlib import Path
from rimworld_translator.multiversion import scan_declared_versions
from rimworld_translator.core import Project, export_versions_test

source = Path('/path/to/local/source-mod')
result = scan_declared_versions(source)
# Versions that fail (for example, missing reference data or dependency context) are recorded in result.failures,
# and scanning of the other versions continues. Cancellation propagates as an exception.
project = Project.create_versions(source, result.scans)
project.switch_version('1.6')  # select a declared version that has been extracted
project.set_translation('DefInjected:ThingDef:Example.label', 'Translation')
project.save(Path('/path/to/separate/workspace/project.json'))
warnings = export_versions_test(project, Path('/path/to/separate/test-mod'))
```

A Project cannot be created from empty scans. A Project that contains declared versions that have not been extracted can be kept, but the current test export API requires extraction results for all declared versions. This restriction does not decide the policy (Q17) for formal export that includes incomplete versions.

`scan_declared_versions` runs sequentially in numeric order (1.10 comes after 1.9). `contexts` accepts, keyed by declared version, a dictionary of `active_mods`, `schema`, `context_sources`, and `cache_path`. Provide type information and dependency sources that match each version. Type information for 1.6 is not automatically reused as validation evidence for older versions. A version with no context specified gets generic static analysis, and conditional MOD context is unknown. The cache cannot be written into the source MOD, Steam, or symlink targets.

```python
result = scan_declared_versions(source, contexts={
    '1.6': {'active_mods': ['sample.source', 'sample.dependency'],
            'context_sources': [Path('/path/to/read-only/dependency')]},
}, progress=lambda version, done, total: print(version, done, total))
```

Prerequisite MODs are analysis context. Only text that the target MOD adds to or replaces in a prerequisite Def is attributed to the target MOD; the prerequisite MOD's own original text is not mixed into the target. Text that the target MOD's own child Defs inherit from a prerequisite parent Def is treated as keys of that child.

`Project.version_profiles` stores, per version, entries, translations, per-language review, diagnostics, load folders, and dependency conditions. The existing `entries` is a compatibility view of the current version. Translations for the same ID are not automatically copied to other versions. `add_version_scan(version, scan)` updates only one version; when the source text changes, the old translation is kept and its approval is cleared. Obsolete keys remain in that version's stale history. Old schema 1 is still loaded as before, and saves that carry per-version state use schema 2.

Test export creates an independent full translation set for each `version/Languages/language/...` and generates About.xml and LoadFolders.xml. Nothing is shared into Common. Empty translations are omitted. Translations with serious QA errors such as placeholder problems are excluded with a warning. Invalid keys and dangerous output paths are rejected before writing. The output carries an ownership manifest and `test_only` / `unverified_versions`.

Static extraction of all versions does not mean completeness or in-game behavior has been verified. The coverage fields `source_verified` / `game_tested` stay at their initial value of false. 1.0 is rejected up front for test export because its load rules are awaiting verification. The old `export_mod` is for schema 1 single-version compatibility. It does not accept a Project that has even one new per-version profile, so partial extraction is not routed around into the legacy export.

Not implemented / undecided: formal all-version export (Q17 on hold), formal source-text fallback for untranslated entries, GUI, approval-gated translation sharing between versions, 1.0-specific load rules, validity checks of all dependency configurations and conditional output integration, dedicated analyzers for Strings/WordLists, IL candidate analysis of DLLs, and in-game verification of each version.

## Round 2: bounded exploration of per-version dependency scenarios

`dependency_profiles.plan_dependency_scenarios` analyzes, for each version declared by the source MOD, the exact override of `modDependenciesByVersion/v<version>` (an empty list is also valid), or the base dependencies when no entry exists for that version. From the conditions in the target MOD's LoadFolders/Defs/Patches, it builds hypotheses such as no optional dependency / A / B / A+B. It does not verify transitive dependencies, conflicts, obtained actual files, or load order. It does not guess a conversion from `FindMod` display names to packageId.

`multiversion.scan_declared_scenarios` scans each declared version and each scenario sequentially. Because the source text of the same key can differ depending on conditions, results are not merged unconditionally; they are returned as a dictionary of version -> scenario name -> Scan.

```python
from rimworld_translator.multiversion import scan_declared_scenarios

result = scan_declared_scenarios(source, max_scenarios=16)
for version, plan in result.plans.items():
    print(version, plan.total_scenarios, plan.unexamined_scenarios)
    for diagnostic in plan.diagnostics:
        print(diagnostic.code, diagnostic.message)
# Review the contents and conditions, and select explicitly for each version.
selected = {version: result.scans[version]['base']
            for version in result.declared_versions}
project = Project.create_versions(source, selected)
```

Failures are recorded in `result.failures[version][scenario_name]`, and planning failures under the name `<planning>`. The example above is for the case where every version has a base result; if there are failures or unexamined items, the contents need to be checked. Only the versions and configurations that succeeded can be kept, but the existing test export requires a Scan for all declared versions. Q17 for formal all-version export remains on hold.

Exploration stops at 16 scenarios per version by default (256 at most) and at 2000 condition-XML files by default. The number of unexamined combinations for discovered optional IDs and the diagnostic that undiscovered conditions remain due to XML truncation are separate. It is not a guarantee that valid dependency configurations have been covered exhaustively. Planning diagnostics are added to the selected Scan's diagnostics and stats and are kept after the Project is saved.

In `contexts`, `active_mods` are fixed active IDs and `context_sources` are the available dependency sources. This new API checks the packageId in each dependency source's About and passes only the dependencies that are active in that scenario to the extractor. Even if the actual files of a required dependency are not provided, it is included in the hypothetical active IDs, but `dependency-context-unverified` remains and it is not treated as complete extraction. The behavior of explicit contexts in the old `scan_declared_versions` / `scan_mod` is unchanged.

This round's static Patch improvements are exact matching of `PatchOperationFindMod` by the display names in the provided About files, and evaluation of the operation's own `MayRequire`. Negative branches for which name data is insufficient are deferred, and names derived from a DLC's ExpansionDef are not supported. The GUI, the conditional translation and output model for all scenarios, and in-game verification of all versions remain unimplemented.

## Round 5: connecting FindMod display names with per-version configurations

`plan_dependency_scenarios(..., context_sources=[dependency_folder, ...])` maps the display names of the target itself and of the provided dependency Abouts to packageIds. Display names are matched exactly and case-sensitively; no inferred matching between names and packageIds is done. Only referenced names are explored, and unused dependency sources are not enabled automatically. Multiple IDs with the same name keep their candidates and leave `findmod-ambiguous-name`; an unresolved mapping leaves `findmod-context`. Resolving display names from a DLC's ExpansionDef is not implemented.

`scan_declared_scenarios` passes that version's `contexts[version]['context_sources']` to the planner. A passed source is used only in configurations where it is active. The iterator is also fixed so that it can be reused within a version. A version whose material needed to start exploration cannot be read, for example because About is missing or malformed, becomes a `<planning>` failure, and scanning of other versions continues. The configurations remain unverified hypotheses.

The English DefInjected catalog now also handles nested XML under the type folder, so the example `DefInjected/ThingDef/Furniture/items.xml` is matched as `ThingDef`. Catalog-only unknown keys keep their existing needs-review state and are not treated as having confirmed translatability.

## Round 6: static Patch body and pre-validation of output destinations

`PatchOperationAdd` also applies the leading text node of a `value` added to an element XPath, in Append/Prepend order. Only the fields of the external Def that were modified are recorded as originating from the target MOD, and the Def's unchanged fields are not mixed into the translation list. XPaths that select a text node or an attribute itself remain a diagnostic target. Mixed content preserves patch order, but no feature was added to promote it into an ordinary translatable field.

For test/legacy export, for all payloads and the old manifest, cases where a destination is a directory, a parent is a regular file, or a planned new output destination collides with an unowned file are rejected before any write or delete. Re-export of regular files inside the owned manifest is maintained. This protects against predictable structural conflicts; it is not atomic updating of the whole output including mid-way I/O failures or concurrent external changes.

So that diagnostic generation and Project saving can continue even when the number of dependency configurations is huge, the planner's diagnostics are recorded with the exact formula `2^N - examined`. `DependencyPlan.total_scenarios` / `unexamined_scenarios` hold exact integers. The selected Scan's `stats.dependency_scenarios_total` / `dependency_scenarios_unexamined` are normally integers, and only when there are more than 2048 optionals become exact exponent-expression strings (for example `2^15000` / `2^15000 - 2`). The type is `int | str`. The number of explored scenarios stays within the existing limit, and the unexamined diagnostics and unverified coverage are not removed. The process-wide integer-to-string conversion limit is not changed.

Q17 for formal output, conditional output integration of all configurations, and in-game verification of all versions remain on hold / unimplemented.

## Round 7: forbidden XML characters in test export

If a translation contains characters forbidden in XML 1.0 (NUL, some control characters, lone surrogates, U+FFFE/U+FFFF), test export excludes only that translation with a warning and continues exporting other safe keys and versions. The translation text in the edit data itself is not deleted or replaced. The legacy single-version export still rejects it before writing, as before. Legal newlines, TAB, and supplementary-plane characters are preserved.

This is a safety measure for test export and does not decide formal all-version export or whether incomplete versions are allowed (Q17). In round 7, test export of lone surrogates was verified without a save in between. For the limits on saving, see the round 8 fix in the next section.

## Round 8: attribute Patch and saving Projects with invalid characters

The static `PatchOperationAttributeAdd` does not overwrite existing attributes and adds only to target nodes that lack the attribute. `AttributeRemove` changes only target nodes that have the attribute. For both, the worker is treated as successful if at least one target is eligible, and returns failure if all targets are unchanged because of the presence or absence of the attribute. Because the `success` modifier is applied to that result, text in a following Sequence step is not wrongly extracted or excluded. `AttributeSet` keeps updating existing attributes and adding missing ones. The primary confirmation of these rules is a non-executing static read of the legally owned 1.6 DLL, which does not mean older-version CLRs were verified.

`Project.save` keeps lone surrogates as JSON Unicode escapes for both schema 1 and 2, saving a state that can be fixed later. Ordinary Japanese and supplementary-plane characters stay as UTF-8. In test XML, even after a save and restore, only the dangerous translations are excluded with a warning, and translations and approvals of other safe versions are kept. Rejection of invalid XML in the legacy single-version export is also kept.

An adjacent high/low surrogate pair is merged into a different supplementary-plane character on JSON restore, so the original code units cannot be preserved. Saving such input is rejected in advance and the existing Project file is not replaced. Proper supplementary-plane characters (a single Unicode code point) can be saved. This is not a guarantee that every invalid string can be saved.

Formal all-version export and whether incomplete versions are allowed (Q17) remain undecided.

## Round 9: test-export protection for versions numerically equal to 1.0

The 1.0 rejection in test export compares each component of the version number numerically, not by exact string match. `1.00`, `01.0`, and `01.00`, which the declaration parser accepts, correspond to the same unverified load rules as 1.0, so they are rejected before writing to the destination. Declared notation is not normalized or rewritten. Even when rejected, stored per-version translations, approval state, and existing output are kept.

Ordinary 1.1 and later, numeric ordering of 1.9/1.10, and legacy single-version export are maintained. Test extraction and save/restore of all declared versions are possible, but formal all-version export and whether incomplete versions are allowed (Q17) remain undecided.

## Round 10: XML processing instructions and regression checks of per-version state

XML processing instructions (PIs) are not executed and are treated as XML nodes that XPath can reference. The persistent cache stores the PI's target, body, tail, and position, and can restore existing v3 ordinary elements without re-parsing. PIs directly under Defs/Keyed/English DefInjected catalogs are not treated as Defs or translation keys, and are not executed as operations in a Patch's operation list or inside a Sequence.

PIs inside a Def field are not included in field names or list numbers. The text/tail of a leaf split only by a PI are concatenated, and the PI body is not put into the translation. This is not a feature that turns every field that has ordinary child elements into text. It is static processing based on the string semantics of generic XML, and does not mean each version's game implementation was verified. PIs inside Keyed values are excluded as conventional nested values, and PIs inside identifiers are also unverified.

Using fixtures with correct answers for 6 versions (1.3/1.4/1.5/1.6/1.9/1.10), regression checks cover per-version save/restore, preservation of old translations and clearing of approval when the source changes, obsolete history, protection of other versions' translations and approvals, per-version full XML, protection of unmanaged files when updating managed output, and legacy single-version export. The policy for formal all-version export, Q17, and formal untranslated fallback is unchanged.


## Round 13: exploring conditional prerequisites and adding declared versions to the source MOD

`plan_dependency_scenarios` examines not only the target MOD's conditions but also the LoadFolders/Defs conditions of provided analysis contexts that can become active for that version. It covers only contexts that correspond to required, fixed IDs or discovered optional IDs, and when a new condition can activate another provided context, it tracks that independently of input order. Unrelated provided MODs, and conditions in a context's Patches that the extractor does not apply, are not added to the exploration budget. The existing limit is applied to the combined XML file count of the target MOD and contexts, and the truncation diagnostic is kept. The file path is recorded as the diagnostic source for the context. This is not a change that adds a prerequisite MOD's own existing text to the translation targets; it is a hypothesis exploration for examining text the target MOD inherits or adds.

PIs inside Keyed values, which were unsupported in round 10, are also distinguished from ordinary child elements. The PI body is not included, and the value's text/tail are concatenated. Nested Keyed values that have ordinary child elements are excluded as before. This is a limited change aligning general XML value handling with existing Def leaves, and is not an in-game guarantee of each version's RimWorld loader.

When the source MOD adds declared versions, explicitly calling `project.add_version_scan(new_version, scan, extend_declared_versions=True)` extends the declared set while keeping all the old declarations. Translations, approvals, history, and coverage of existing versions are kept, and translations and approvals are not shared into the new version. With the default False, an exact match of the declared set is required as before. Even with True, calls for an already declared version and removal of an old declaration are rejected. An old schema 1 single-version Project can also be migrated while keeping its existing version. If any newly declared versions remain unscanned, the all-version test export stops before writing.

```python
# When the source MOD is updated from declaring 1.3/1.6 to declaring 1.3/1.6/1.9/1.10.
# After preparing independent scan results for all newly declared versions, make the addition explicit.
project.add_version_scan('1.10', scans['1.10'], extend_declared_versions=True)
project.add_version_scan('1.9', scans['1.9'])
```

A GUI for detecting new versions and explicitly adding them is not implemented. Formal all-version export, formal viability of incomplete versions (Q17), formal untranslated fallback, and the history policy for when an old declaration is removed are not decided in this round.


## Round 14: ownership of Patch body, editing after version switch, and formal export after source changes

`PatchOperationAdd` recognizes as added text not only `value.text` but also non-empty tails that follow processing instructions and similar nodes. Text added to an external abstract parent field is extracted as keys of the inheriting Def, and unchanged external fields are not mixed into the target. When there is only a PI body and no visible text, the original text is not made owned by the target MOD.

`PatchOperationRemove` keeps the trailing text of the selected node. In the XML DOM, trailing text is an independent sibling node, but in lxml it is stored as the tail of the removed node, so before removal it is moved to the previous sibling's tail or the parent's text. The RemoveChild rule was confirmed by a non-executing, type-limited read of the legally owned 1.6 DLL and by independent DOM fixtures. It is not a check against each older-version CLR or the actual game. The tail boundaries of Replace/Insert are unverified.

`Project.entry_index` checks the reference identity of the list itself, in addition to the address and count of entries. Even if the address of a list discarded on version switch is reused, edits are not written into an Entry of a past version, and the current version's translation is saved. For the independent view used by per-version output, this reference cache is also released.

The existing single-version `export_mod` rejects, before writing to the destination, a case where an old translation whose source changed has not been re-reviewed for that language (Q13). After `mark_reviewed` it can be exported, and the handling of plain new / unapproved translations and of needs-review states without a source change is unchanged. Test export of all versions keeps old translations and needs-review warnings. The policy for formal all-version export, whether incomplete versions are allowed (Q17), and formal untranslated fallback is unchanged.

The known limitation that unrelated conditions inside a dependency context use the bounded-exploration budget was recorded while keeping the unexamined count and truncation diagnostics. To avoid missing extractions by removing conditions, no product change to the planner was made this time.

## Round 15: XML sibling nodes for Replace/Insert

`PatchOperationReplace` inserts the leading text, elements, processing instructions, and trailing text of `value` as independent siblings at the replacement position, and keeps the text that followed the replaced target. `PatchOperationInsert` uses the same node model: Append inserts right after the target, and Prepend (also when omitted) inserts right before it. To match the worker's iteration rule confirmed in the legally owned 1.6 DLL, multiple value child nodes are in reverse order for Insert and in forward order for Replace. A non-canonical Insert order is diagnosed, and an unknown effect is not treated as applied.

Added non-empty direct text is tracked as target-MOD-derived text of the parent field, and target keys inherited from an external abstract parent are also extracted. An empty replacement that adds no text does not take ownership of external text, and unchanged external fields are not mixed in. This is a confirmation of static rules through a type-limited, non-executing read of 1.6 and independent DOM fixtures, and does not mean that older-version CLRs, future versions, or in-game loading of PI-containing XML was verified.

For per-version Projects and test export, regression checks cover key deletion across 6 versions, save/restore, revival with source change, removal of old XML for a version changed to a dangerous translation while keeping other versions and user files, and explicit addition of 1.10 while keeping the existing 6 versions. The policy for formal all-version export, handling of incomplete versions (Q17), and formal untranslated fallback remains undecided.


## Round 16: XML null and restoration on export failure

In Def fields, nested objects, and list containers, when an attribute is named exactly `IsNull` and its value is `true` (case-insensitive), no translation text is extracted. The check is not done after stripping whitespace. A null list item still occupies its position at load time, so the numeric indexes of later items are not compacted, and null items are not counted in TranslationHandle duplicate counts. Null-specified handle fields and BodyPartRecord's customLabel are not reused for identifier generation. The basis is a type-limited, non-executing confirmation of the legally owned 1.6 DLL, not verification of older or future CLRs or the actual game. The same attribute rule is not applied without basis to the formats of other loaders such as Keyed.

The shared public routine for single-version and per-version test export prepares all files to be changed, together with their old contents, in temporary space on the same filesystem as the destination, and then swaps them in. If an exception occurs during writing, deletion of old files, or publication of the manifest, files that were already changed are restored to their previous contents. The manifest is published last, and unchanged files and unmanaged files are kept. If the restoration itself fails, backups are not deleted and the save location is reported in the exception. The saved `recovery.json` maps the destination and the relative paths to backups.

This restoration handles runtime exceptions that could be caught. There is no guarantee that all files switch simultaneously, no automatic recovery from power loss or forced process termination, and no guarantee for concurrent writes to the same destination. Formal all-version export, Q17, and formal untranslated fallback remain on hold.

## Round 17: unreachable dependency configurations, null Def roots, and version provenance

When a LoadFolders `li` has an unknown `ifmod*` attribute, the dependency planner does not explore that folder's conditions or the XML under it, matching the existing resolver, which excludes that folder in every configuration. The diagnostic for the unknown condition is kept. An unknown `MayRequire*` is not given the same treatment; conditions in other reachable folders, and the unexamined count and exploration-limit diagnostics, are kept. This does not imply anything about whether dependencies can be obtained, transitive requirements, conflicts, ordering, or completion of verification of all configurations.

When the exact `IsNull` attribute on a Def root is `true` (case-insensitive), extraction from that Def is stopped before inheritance and custom loader processing. A named null parent remains as an XML template for inheritance so that text of valid child Defs is not lost. Keys of the English DefInjected catalog are not deleted even if the static Def is null; they are kept as existing unresolved / needs-review candidates and are not promoted to a schema match. The basis is a type-limited, non-executing confirmation of the legally owned 1.6 DLL. It is not a guarantee for older or future versions in the actual game.

`add_version_scan` rejects, before changing state, a case where an old single-version project's selected version is not in the target declared set. This prevents the history of an undeclared version from being mixed into schema 2 and becoming impossible to restore after saving, and keeps the old schema 1 translations, approvals, and saved data. Normal single-version migration within the declarations and explicit addition of new versions are maintained. When restoring schema 2, it also verifies that each profile's `stats.active_version` matches the profile's version key.

Formal all-version export, Q17, and formal untranslated fallback remain on hold.

## Round 18: fixed dependency conditions, conditional attributes on strings, and ownership of rescan results

The dependency planner excludes from exploration LoadFolders branches that contradict the target itself, the version's required dependencies, and explicit active IDs, all of which are fixed as active in every configuration. This applies only when `IfModNotActive` contains a fixed ID, or when every ID of `IfModNotActiveAll` is fixed. Reachable branches that include optional IDs, MayRequire, and the unexamined count and exploration-limit diagnostics are kept. It does not include resolving all dependency conditions or guaranteeing that configurations work.

Translatable leaf fields confirmed by type information to be an ordinary non-list `System.String` are not excluded merely because of `MayRequire`/`MayRequireAnyOf`, since the ordinary string load in the legally owned 1.6 DLL does not evaluate these attributes. The existing handling of conditions on list items and objects, IsNull, and IfMod-family attributes is maintained. This is not an unconditional extension to heuristic extraction with unknown types or to all custom loaders, and is not an in-game guarantee for older or future versions.

`Project.rescan(scan)` copies the input Scan's Entries before updating version-specific translations, approvals, and source-change history. Even when the same Scan is reused for another Project, translations and approvals are not shared, and old translations are not written into the input extraction evidence. Independence between Projects is also kept in per-version save/restore and test XML.

Formal all-version export, the handling of incomplete versions (Q17), and formal untranslated fallback remain undecided.

## Round 23: contradictory conditions, standard Strings resources, and Scan independence

Within a single LoadFolders branch, when the dependency planner can prove an overlap of required and forbidden IDs, a total ban on ANY candidates, or a NotAll set that is entirely required, it excludes that unreachable branch from exploration. This also applies to conditions on optional IDs, but general SAT search is not performed. Branches that cannot be proven are kept, and the handling of bounded exploration and the unexamined count is maintained.

Standard TXT lists in subdirectories of `Languages/English/Strings/` are analyzed by a dedicated parser. Targets are, for example, `Strings/WordLists/Names.txt`; arbitrary TXT files and WordLists directly under the root are not targets. UTF-8 (BOM allowed) is read, then CRLF/LF splitting, trim, removal of comments from the first `//` onward, and exclusion of empty strings are applied in that order. The basis is a non-executing, type-limited confirmation of `LoadedLanguage` and `GenText` in the legally owned 1.6 DLL. Older and future versions are extracted by the generic rules and are not treated as verified in the game. WordInfo and custom formats remain as unsupported diagnostics.

Strings Entries keep the relative file and logical line number, as in `kind='Strings'`, `group='WordLists/Names.txt'`, `key='line_0'`. This ID is an identifier for edit state, not an XML translation key. File priority of LoadFolders and per-version state are kept, and a prerequisite MOD's Strings and existing Japanese text are not imported automatically.

Output goes to per-version files such as `Languages/Japanese/Strings/WordLists/Names.txt`. To preserve line count and order, all-line translations are validated per file, and translations that would cause commenting out, added lines, or missing lines are rejected. A partial translation is rejected before writing in formal single-version export, and in all-version test export that file is excluded with a warning. No source-text fallback has been added. The existing output ownership check and exception recovery are used.

`Project.create` copies the whole input Scan. The metadata of `rescan` is also copied, so edits such as translations, approvals, and diagnostics do not leak into another Project that uses the same Scan or into the input evidence. Existing schema 1/2 XML Entries can still be loaded. Formal all-version export, Q17, and formal untranslated fallback remain undecided.

For deleted Strings lines, old translations are kept as stale history and are excluded from the all-line translation check of the current file. Even if trailing lines are deleted, the remaining lines can be exported, and managed TXT files of resources whose lines were all deleted are removed on the next export. Files that contain currently blocked/excluded lines are still rejected.

## Round 24: local conditions of prerequisite MODs and character encodings of standard TXT

When examining an optional prerequisite MOD, LoadFolders contradiction checks reflect that its contents are used only in configurations where that MOD itself is active. This assumption is limited to the examination of that MOD and does not change it into a required dependency of all configurations. This prevents unreachable branches from consuming the bounded exploration budget and pushing out the source MOD's inherited text.

Standard Strings lists are read as UTF-8 and also as BOM-marked UTF-16/UTF-32 in LE/BE. The UTF-32 BOM is checked first, handling the prefix overlap with UTF-16. Trim follows the game's String.Trim, and U+001C to U+001F, which only Python treats as whitespace, are not removed from the source text. Corrupted encodings are not replaced; they are diagnosed and the resource is excluded, and rejection of export for translations containing control characters is kept. This is not a change that extends support to WordInfo or custom WordLists output.

Rescanning a single-version Project also verifies, before changing state, that the target MOD's packageId matches. Even with the same key and the same source text, existing translations and approvals are not carried over to a Scan of a different MOD. The existing version-change flow for the same MOD is maintained. Q17, formal all-version export, and formal untranslated fallback remain on hold.


## Formal all-version export (Q17 A confirmed / 2026-11-15)

`core.export_versions(project, target, versions=None)` formally exports only the versions that are ready. Versions that are unextracted, 1.0, have no exportable translations, or still have dangerous translations or translations needing re-review are put on hold; the reason is recorded in `VersionExportResult.held` and in the output marker, and they are not listed in About.xml/LoadFolders.xml either. Other versions continue to be exported, and if all versions are on hold nothing is written. Untranslated keys are not output. `export_versions_test` still test-exports all declared versions as before. In the GUI, "Export translation mod" runs this formal export for per-version projects and shows the exported versions, the held versions, and their reasons on the result screen (no automatic export on save).
