# Key audit, base vs. final (2026-11-20)

Static analysis only; no MOD code executed, no game run. `tools/key_audit.py run` (invocation in
`docs/DEVELOPMENT.md`) over the first 120 MODs (sorted order, `--limit 120`) of the 553 readable MODs of the pinned
corpus (`tools/corpus/manifest.json`; the full set takes about 1.5 hours per side on the development machine and
was not run). Official patterns from `Languages/*.tar` of the installed game library (406 DefInjected patterns).
Before = the development branch tip before this work, after = the working tree afterwards (IL field-use rule,
holdout L4 name variants, Core `About.xml` context, rescan reuse). Raw rows are kept out of git.

| measure | before | after | change |
|---|---:|---:|---:|
| entries extracted | 46,850 | 46,996 | +146 |
| truth keys (MOD's own translations) | 32,969 | 32,969 | 0 |
| truth hits | 28,016 | 28,054 | +38 |
| recall | 84.98% | 85.09% | +0.11 pt |
| translated_missed | 82 | 44 | -38 |
| evidenced entries | 39,998 | 40,152 | +154 |
| evidenced share | 85.37% | 85.44% | +0.07 pt |
| proven-internal entries | 280 | 291 | +11 |
| precision | 99.40% | 99.38% | -0.02 pt |
| official_missed | 31 | 34 | +3 |
| blocked / errors | 2 / 0 | 2 / 0 | 0 |

Reading: the recall gain comes from keys the MOD's own translation keeps (token-list and compare-only rules no
longer drop them) and from field-name variants in unreadable classes. The 11 extra proven-internal entries and 3
extra official-pattern misses are a small precision/recall cost that was not itemised; they have not been
investigated key by key. A 120-MOD sample is not a statement about the whole corpus.

## `assets/field_contracts.json` review

All 23 `owned` and 11 `legacy` rows are exact CLR declaring type + field (or Def type + key path) rules with a
reason and an `evidence` line naming the audit and the test; none matches a MOD name, package ID or a whole MOD.
Several owners sit in a MOD's namespace (for example Save Our Ship 2, Combat Extended) because that is where the
declaring class lives; each row is limited to that one type and field. They were left as they are: nothing in the
audits supports generalising them (a field called `interior` or `branch` on other types is not shown to be
internal). The one-word-list rule still requires `schema.known_defs` (or the game's Core as context).

## After review fixes

Same 120-MOD sample, same corpus listing and official-pattern file, run from a temporary worktree of the commit
that contained the review fixes.

| measure | before | after | after review fixes | change vs previous after |
|---|---:|---:|---:|---:|
| entries extracted | 46,850 | 46,996 | 47,003 | +7 |
| truth keys | 32,969 | 32,969 | 32,969 | 0 |
| truth hits | 28,016 | 28,054 | 28,054 | 0 |
| recall | 84.98% | 85.09% | 85.09% | 0 |
| translated_missed | 82 | 44 | 44 | 0 |
| evidenced entries | 39,998 | 40,152 | 40,152 | 0 |
| evidenced share | 85.37% | 85.44% | 85.42% | -0.02 pt |
| proven-internal entries | 280 | 291 | 291 | 0 |
| precision | 99.40% | 99.38% | 99.38% | 0 |
| official_missed | 31 | 34 | 34 | 0 |
| blocked / errors | 2 / 0 | 2 / 0 | 2 / 0 | 0 |

The review fixes only added 7 entries without evidence; hits, proven-internal (291) and official_missed (34) did
not move, so the extra counts versus the "before" run remain and are still not itemised. Same 120-MOD sample
limits apply.
