# Real MOD extraction audit

Status: complete. The frozen corpus contains 108 distinct real MOD families: 18 installed Workshop snapshots and 90
public author sources. Identity, source-integrity and post-fix extraction checks completed on 2026-10-15.

The approved requirements, MOD payloads, original catalogs, assemblies and game data were kept in private,
untracked working directories. This public copy omits two metadata files that accompanied the audit:
`source-metadata.json` (identifiers, URLs, revisions and checksums of the selected MODs) and
`pinned-author-sources.json` (the seed list of the 90 public author sources). Both list other people's MODs and are
not distributed here. The corpus can be re-selected and re-fetched with `tools/retrieve_mod_corpus.py`
(see Reproduction), but the exact 108-MOD selection is not reproduced by this repository.

## Inputs and extraction method

The selected identities and immutable source revisions were recorded in the (omitted) metadata files. Core and DLC
are context inputs and are excluded from the MOD count. Forks, continuations, test metadata and non-independent
translation overlays were excluded, with reasons, in a private frozen manifest.

The audit calls the existing `rimworld_translator.core.scan_mod` pipeline, with installed RimWorld 1.6.4871
metadata, version selection, explicit active packages, Core/DLC and declared dependency context, and cold/warm
scans. The active scenario contains every selected MOD package and installed DLC; it is an analytical scenario
rather than anyone's actual load profile. No downloaded scripts or MOD assemblies are executed.

All source bytes, author repository bytes, installed originals and game context inputs are hashed before and after
use. Each MOD report records entries, duplicate blockers, diagnostics, XML failures, skipped fields, version
branches, unresolved dependencies, timing and source integrity. Independent evidence includes raw Def XML,
inheritance, patch values, English Keyed and other real catalogs, CLR field metadata, DLL user strings and shipped
C# `.Translate()` call literals.

## Evidence classifications

- `confirmed_miss`: an absent selected field is independently corroborated as an owned, translatable field with an
  unambiguous engine key.
- `possible_miss`: ownership, key construction, patch semantics, constructor defaults or runtime text visibility
  still require inspection.
- `correct_nontranslatable`: non-string/forbidden fields and intentional exclusions, including inactive versions or
  foreign catalog targets outside the MOD's extraction scope. This does not imply foreign text is intrinsically
  untranslatable.
- Canonical-key discrepancies are tracked separately. An engine-supported alternate key is not a proven loss of
  source text or failed injection.

Catalog exact-key overlap is corroboration, not recall. A zero-entry MOD is not automatically a failure. A
successful scan means the pipeline completed and repeated consistently; diagnostics may still record malformed XML,
unsupported patches or unresolved runtime behavior.

## Completed before/after run

| Measure | Before fixes | Final post-fix |
| --- | ---: | ---: |
| Distinct real MODs | 108 | 108 |
| Successful scans | 107 | 108 |
| Exceptions | 1 | 0 |
| Extracted entries | 46,164 | 46,259 |
| Confirmed missing candidate identities | 0 | 0 |
| Possible candidate identities | 30,877 | 31,437 |
| Source, game and repository integrity | pass | pass |

The only aggregate entry-count increase is 95 entries from one MOD (Map Reroll): 87 English Keyed entries and 8
DefInjected entries. Its source snapshot contains a Git LFS pointer instead of the optional runtime DLL; metadata
inspection now records that limitation and allows static XML/catalog extraction to continue. The remaining 31,437
possible candidates are unresolved evidence, not proven missing strings or a recall estimate.

The final per-MOD candidate identity totals are 41,815 exact corroborations, 57,395
intentional/foreign/inactive/nontranslatable exclusions, 31,437 possible misses and 0 confirmed misses. These
labels are evidence classes; they do not claim that every possible candidate is an actual display string. The 53,865
warning events comprise 42,098 distinct diagnostic messages and 11,767 repeats (no diagnostics were omitted). The
largest distinct categories are 30,515 unknown fields, 9,642 skipped lists, 1,586 patch-context notices, 161
unsupported patch operations and 141 DLL text notices. These are review signals, not 53,865 unique extraction
failures.

Three verified BodyPartRecord catalog keys were independently sampled across 12 custom-label fields. The existing
pipeline emitted the source strings under different handles; the fix reads the named translation-handle priority
and applies the verified `PostLoad` label alias for this exact engine type. A real catalog import preview changed
from 1 matching key plus 12 unknown keys to 13 matches, 0 unknown keys and 0 conflicts. Existing projects keep
translations on old aliases as stale entries; the new canonical entries remain blank until users review or import
the catalog.

Real Vehicle Framework metadata also exposed lazy `MemberRef.Signature` values that are absent for unrelated
members. The decoder now reads signatures only for `TranslationHandleAttribute` and tolerates absent metadata. Its
complete 1.6 assembly schema is retained, and its final scan emits 715 entries. The regression is covered by the
frozen real-DLL test when that private fixture is available. The final full suite at that time passed 234 tests.

An auditor review corrected 93 texture/asset path candidates as non-language identifiers. No source-text miss was
confirmed in the final corpus. The full per-MOD JSON/CSV and evidence were kept in a private, untracked run
directory; no MOD payloads or assemblies are committed.

## Reproduction

From a checkout, using its Python environment (the corpus seed file is not distributed; supply your own candidate
list or use `tools/corpus/manifest.json` with `tools/fetch_corpus.py`):

```sh
python tools/retrieve_mod_corpus.py \
  --candidates <your candidate list>.json \
  --output artifacts/mod-100-audit-reproduced --target 108
python tools/retrieve_mod_corpus.py \
  --output artifacts/mod-100-audit-reproduced --enrich-only
python tools/audit_mod_corpus.py \
  --manifest artifacts/mod-100-audit-reproduced/corpus-manifest.json \
  --output artifacts/mod-100-audit-reproduced --run-label reproduced \
  --game /path/to/installed/RimWorld
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
```

An identical corpus additionally requires the recorded installed Workshop inputs and game build. Missing local
Workshop inputs or later source unavailability must be reported as retrieval limits rather than replaced with
fixtures. The audit records interpreter, dependency versions, code hashes, scenario and all context hashes.
Fingerprint changes retain old reports in `superseded/`.

## Current limitations

Six author snapshots do not contain built runtime MOD DLLs (for example Pawn Rules, More Filters and four
development-source repositories). Their C# source can be inspected, but complete runtime schema or generated text
coverage is not established.

Custom patch operations, absent optional dependencies, generated definitions, constructor defaults and C# UI text
remain conservative candidates. This is a static extraction audit; it does not establish gameplay compatibility or
actual rendering for every MOD. The audit used a separate writable local Git workspace and did not push or publish
sources or reports.

Texture-only 1.5 patches selected for the all-packages scenario can still inherit foreign context translation
fields because ownership is currently tracked at definition level. This is reported as a precision limitation, not
as text authored by the patch MOD. Catalog alias migration also remains a manual review/re-import step for existing
projects.
