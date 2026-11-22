# Development and isolated verification

This is a Python 3.11+ / PySide6 desktop application. Work in the existing cloud checkout; no additional worktree is needed. The old tracked `.venv` link pointed at the original developer's computer and has been removed. Create a real ignored virtual environment, or use an existing environment explicitly:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install '.[dev]'
./run.sh
# An environment outside the checkout:
RW_TRANSLATOR_PYTHON=/workspace/venvs/rimworld-translation-editor/bin/python ./run.sh
```

For Windows use `.venv\Scripts\python.exe -m rimworld_translator`.

## Regression and GUI checks

Use the selected environment's Python (replace `python` below with its full path when necessary):

```bash
python tools/run_tests.py
python tools/run_tests.py discover -s tests -p test_incremental_versions.py -v
python tools/run_tests.py --script tools/verify_native_gui.py --output artifacts/gui-check
python tools/run_tests.py --script tools/smoke_gui.py
python tools/build_portable.py --dry-run
```

`run_tests.py` creates temporary config/data/cache/state and app-settings paths, configures QSettings to use temporary INI files (including Windows), and passes the same isolation to child interpreters. It pins imports to this checkout so a subprocess cannot accidentally test an older installed package. The runner removes its temporary state and returns the underlying command's exit status. Proxy/TLS settings are inherited unchanged.

The default Qt platform is `offscreen`, but only when `QT_QPA_PLATFORM` is unset: the runner keeps an inherited value. A desktop session that exports it (Omarchy/Hyprland sets `wayland;xcb`) therefore runs the GUI tests on the real display, where a tiling compositor overrides window sizes and focus and five layout/focus tests fail. On such a machine run `QT_QPA_PLATFORM=offscreen python tools/run_tests.py`. A real desktop check can select its normal platform explicitly, for example `QT_QPA_PLATFORM=xcb python tools/run_tests.py --script tools/verify_native_gui.py --require-native --output artifacts/gui-native`. GUI processes must be started through the runner before QApplication is constructed. A helper's `settings_path` alone does not isolate Qt file-dialog history. Retained reports go to the explicit output directory; temporary settings do not.

### Extraction recall/precision measurement (`tools/key_audit.py`)

Developer tool, not part of the product. It scans MODs through the same route as the editor with an unknown
active-MOD list (installed expansions and found prerequisites assumed loaded) and scores the keys against answer keys
that do not come from the extraction rules: the MOD's own non-English translations of its own Defs/Keyed keys (recall),
the official translations' Def type + field patterns, CLR attributes and Keyed catalogs (evidenced share), and values
equal to a Def name, Keyed key or texture path (proven internal entries; precision). Everything is read only; DLLs are
read as metadata and never executed; output stays under `--out` (keep it in `artifacts/` or a scratch folder, never in git).

```bash
LIB=~/.local/share/rimworld-translator/games          # one game folder per version: LIB/<version>/RimWorld
python tools/key_audit.py official --library $LIB --out artifacts/audit/official.jsonl
# A corpus from your MOD folders (default: the installed games' Mods and Workshop), each with its prerequisites:
python tools/key_audit.py corpus --library $LIB --out artifacts/audit/corpus.json
python tools/key_audit.py run --corpus artifacts/audit/corpus.json --official artifacts/audit/official.jsonl --out artifacts/audit/run-A
python tools/key_audit.py summary artifacts/audit/run-A artifacts/audit/run-B   # before/after with deltas
```

Qt plugin warnings on offscreen do not prove native display support. Real RimWorld/Workshop fixtures, in-game display, native Windows and portable packaging remain separate checks. Never claim skipped game-fixture tests establish game compatibility.

## Version workflows

- The normal scan selects game XML and CLR metadata only from an installation with the same known major/minor version as the requested scan. Missing/mismatched installations produce a structured diagnostic and generic static extraction; they are not evidence of version compatibility.
- **Check and add declared versions** remains available after all current profiles are scanned. New declarations and partial failures require selection of successful versions before import. Existing profiles, translations and approvals are preserved; removed declarations are rejected until their history policy is decided.
- Failed/unscanned profiles remain incomplete. Adding successful profiles is independent of formal export policy. The trial exporter still requires extraction for all declared versions.
- Saving a version-profile project saves JSON/history and directs the user to trial export. It does not call the legacy single-version exporter or imply that game files were updated.
- Q17 (formal output when some versions are incomplete) and formal untranslated fallback remain unresolved. No new policy is inferred by these repairs.

## Specification provenance and references

For the Qt isolation repair, the earlier investigation consulted official Qt `qtbase` v6.10.0 `qfiledialog.cpp`, `qsettings.cpp` and `qstandardpaths_unix.cpp`; local QFileDialog behavior was independently reproduced on PySide6 6.12.0. The reference source version is distinct from the installed runtime. REA (`e32a0494d42dedd5e79ca341d20c53f07479d9bb`, MIT for REA-authored material) was consulted only as a static evidence method; Awesome (`bc98e517ddca672f55f9857d714fc3ea3c3540b2`, CC0) only as a resource index. No third-party tool/code was installed or incorporated.
