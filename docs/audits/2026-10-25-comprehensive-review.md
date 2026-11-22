# Comprehensive review of the RimWorld translation editor

Review date: 2026-10-25 (Asia/Tokyo)
Subject: the editor at a feature branch that fixed the version workflow.

## Conclusion

As an offline editing tool for translation work, the current implementation is in good shape. In a dedicated virtual
environment, 747 tests were run: 741 passed, 6 were skipped and 0 failed. Regression tests cover extraction, QA,
difference import, per-version state, protection of the original MOD and the Qt GUI broadly.

It is not yet sufficient as release-quality assurance, however. In-game display, an independent holdout of unknown
MODs, native Windows and uninstalled Workshop samples are all unverified, and the completeness of extraction for
dynamic C# strings and custom loaders cannot be guaranteed.

## Findings by severity

### High - not enough real-environment evidence to judge a formal release

**Evidence**

- The development checkpoint of the time stated that in-game display, unknown MODs and native Windows end-to-end
  runs were not done.
- The 6 skipped tests are skipped because the RimWorld game itself, the Workshop translation samples and the CLR
  metadata fixtures are not present in the environment.
- The README does not guarantee a real Windows machine, a CI run or compatibility with all MODs.

**Impact**

A passing test run cannot be read as "it displays correctly on the player's screen", "the Windows distribution
works" or "any MOD is extracted completely".

**Recommended actions**

1. In an isolated copy of the real game, check `label`, `description`, UI tooltips and Keyed strings of representative MODs.
2. Use at least one unknown MOD as a blind holdout, and measure missed display strings and wrongly extracted internal
   values separately.
3. On native Windows 10/11, exercise the GUI, DPI, saving, export, installation and restore.
4. Obtain the results of a hosted CI run.

### High - unknown or dynamic player-visible strings can be deliberately left out of the output

**Evidence**

- The extraction code does not turn strings into translation entries unless they match a known schema or a limited
  heuristic; they go to diagnostics instead.
- Strings that come from DLLs, and word-info data, are treated as unverified when their safety cannot be confirmed.
- A survey of formats in an external project (Remis) likewise concludes that dynamic generation, custom loaders and
  unknown Def paths cannot be settled by static analysis alone.

**Assessment**

The design decision not to mistranslate internal IDs is correct. This is less a defect than an explicit trade-off
against completeness of player-visible text.

**Recommended actions**

Label diagnostics explicitly as "display candidate", "internal-value candidate" and "unverified", and measure the
candidate miss rate on an unknown-MOD holdout. Do not promote anything automatically without evidence.

### Medium - `Strings` files require complete translation per file

**Evidence**

- The export code leaves out of the formal output any `Strings` file that contains an untranslated line.
- This is safe because those resources are position-based, but even one untranslated line prevents the other
  translated lines from being exported.

**Impact**

It is more conservative than "partial output" and, compared with tools that allow gradual translation, finished work
may not be reflected in the game output.

**Recommended actions**

If the conservative policy stays, emphasise the per-file reason in the UI. If partial output is introduced, add a
dedicated writer whose handling of line numbers, blank lines, comments and fallback has been confirmed in the real game.

### Medium - XML output is generated XML and does not preserve the original comments, whitespace or declaration

**Evidence**

- The export code generates a new `LanguageData` document for the translation MOD.
- The Python XML documentation and a comparison document of an external project point out that ordinary XML
  re-serialisation loses comments, formatting and line endings, so writing back into an original document safely
  needs dedicated handling.

**Assessment**

This fits the product's purpose of generating a new translation MOD without modifying the original MOD. It is a
limitation only if the goal is reversible editing of existing translation files or preserving author comments.

**Recommended actions**

If an overwrite-edit feature for existing files is added, keep it separate from the current new-file writer and use
raw-span replacement.

### Medium - copyright and distribution terms of Preview images depend on the user

**Evidence**

- By default the export generates a Preview image, and the original image can be used for it.
- The README explains the option of not using the original image and the need to check the original author's terms.

**Recommended actions**

Show a mandatory confirmation about licensing in the first-run wizard when the original Preview is used. Continue
not to publish or post to GitHub automatically.

### Low - running the tests directly in a bare environment produces many cascading errors

Running `python tools/run_tests.py` in a standard Python environment made the GUI, PNG and PO paths fail one after
another because `PySide6` and `polib` were not installed. In a dedicated environment that satisfied the dependencies
in `pyproject.toml`, all 747 tests passed. This is a reproducibility problem in the development procedure, not a
product bug.

It would help to state in the README's test instructions either a virtual environment with the dependencies
installed or a portable verification command.

## Strengths confirmed

- The XML parser disables external entities and network access.
- Placeholders, RichText, escapes, line breaks and grammar tokens are checked by QA, and dangerous translations are
  stopped before the formal output.
- `Keyed`, `DefInjected`, `Strings`, per-version LoadFolders, inheritance, conditional patches and CLR field
  semantics are handled separately.
- The Qt `QAbstractTableModel` emits `dataChanged`, and workers are separated from the GUI with `moveToThread`.
  This follows the official Qt model/view and worker-object guidance.
- Original MODs are never modified directly; the output manifest, backup, restore, symlinks and path traversal are checked.
- Compared with `TokcDK/RimworldModTranslator` (simple language-file editing), `DrizztGaming/Mod-Translation-Toolkit`
  (version support, existing DefInjected first, dictionary diagnostics) and `Drlinglong/Remis` (source-preserving,
  diagnostic design), the current tool puts strong emphasis on safety and evidence.

## Verification boundary

| Area | Verdict |
|---|---|
| Tests | 747 in a dedicated environment, 0 failures, 6 skipped |
| Static analysis | extraction, QA, export, Qt model/view, workers and distribution code reviewed |
| Documentation cross-check | Qt model/view, QThread and the Python XML specification checked |
| GitHub material | compared with existing translation tools and RimWorld format notes |
| Real game | not newly run in this environment; earlier records are treated only as limited real-game evidence |
| Native Windows | not verified |
| Blind holdout of unknown MODs | not verified |

## External references

- [TokcDK/RimworldModTranslator](https://github.com/TokcDK/RimworldModTranslator)
- [DrizztGaming/Mod-Translation-Toolkit](https://github.com/DrizztGaming/Mod-Translation-Toolkit)
- [Drlinglong/Remis format survey](https://github.com/Drlinglong/Remis/blob/main/docs/zh/developer/multi-game-rimworld-evidence.md)
- [Qt for Python QAbstractItemModel](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QAbstractItemModel.html)
- [Qt for Python QThread](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QThread.html)
- [Python ElementTree](https://docs.python.org/3/library/xml.etree.elementtree.html)
