# Contributing to rimlingua

Thank you for your interest in rimlingua. This document explains what the project is, how to set it up, which principles it follows, and how to contribute.

## What the project is

rimlingua is a standalone Python 3.11+ / Qt (PySide6) desktop editor for translating RimWorld mods. You pick one mod, the editor scans it, shows the player-visible strings, lets you translate and review them, and writes a separate translation mod. It is an unofficial, community tool and is not endorsed by Ludeon Studios.

Before changing extraction, export or version handling, please read [docs/DESIGN_DECISIONS.md](docs/DESIGN_DECISIONS.md). It records the product decisions (numbered Q1 to Q20, which tests and docs refer to), the multi-version goal and the player-visible localization priority.

## Development setup

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for environment setup, GUI checks and the extraction measurement tool. In short:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install '.[dev]'
./run.sh
```

## Running the tests

```bash
python tools/run_tests.py
```

Always use this runner instead of calling the test framework directly. It creates temporary config, data, cache and state directories, points Qt settings at temporary files, pins the UI language so results do not depend on your operating system locale, and makes child interpreters import this checkout. Do not run GUI tests against your personal settings. Details and further commands (single test files, native GUI verification, packaging dry run) are in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

Please run the relevant tests after every change and add a regression test for each bug you fix. A passing offscreen run does not prove native display support, and skipped game-fixture tests do not prove game compatibility.

## Principles

- **Static analysis only.** Never execute a mod's DLL. Managed assemblies may be read as metadata, IL and string literals, but not loaded or run. Do not attach to processes or access targets you are not authorized to examine.
- **Protect original data.** The editor and its tools must never modify original Steam/Workshop mods, the RimWorld installation, saves or personal translation projects. Output always goes to a separate translation mod.
- **Player-visible text first.** Item, building and research names and descriptions, Keyed messages and player-facing UI come first. Highly mod-specific dynamic text is translated only when reliable evidence shows that players see it and that a safe translation route exists. Unproven text stays an unverified candidate and out of formal exports. Do not chase every internal string, and do not treat a large raw string count as progress.
- **Do not overclaim coverage.** Results from a limited set of mods do not establish full coverage. Report what was measured, on what sample and by which independent check.
- **Separate static analysis from game behaviour.** A rule derived from XML or decompiled metadata is a static finding. Only a check in the actual game shows what a player sees. Say which one your evidence is.
- **Corroborate extraction fixes.** Back each extraction change with independent evidence (real XML or CLR metadata) and a regression test, not just with the output of the rule you changed.
- **Third-party tools are research material.** Do not bundle, wrap or depend on other translation or extraction tools, and do not copy third-party source into the project without a license review.

## Contribution rules

- **Language.** English is the primary language for code comments, commit messages, issues, pull requests and documentation. Translations of the user interface and the README may be added next to the English originals.
- **No game-derived data.** Do not commit RimWorld game files, extracted game text, textures, assemblies or save data.
- **No other people's mod content.** Do not commit files from other authors' mods, including their text, translations and assets. Use small synthetic fixtures that you wrote yourself.
- **No personal data.** No names, e-mail addresses, local paths, tokens or settings from your own machine in code, tests, fixtures or logs.
- **Free of charge.** The app is free. Do not add advertising, donation prompts, paid features or payment links inside the application. Ludeon's EULA restricts monetizing content based on the game, and the project stays on the safe side of that.
- **Keep the disclaimer.** Keep the unofficial / not-endorsed-by-Ludeon notice in the README and in the About information of the app and of generated mods.
- **Small, reviewable changes.** Prefer the simplest solution, avoid new dependencies when the standard library or existing ones suffice, and keep unrelated changes out of the same pull request.

## Reporting issues

Open an issue with:

- the app version and your operating system;
- what you did, what you expected and what happened;
- the mod name and the declared game versions, if the problem is about a particular mod (describe the problem or attach a minimal synthetic example; do not attach copyrighted mod files);
- relevant log output with personal paths removed.

For a missing or wrongly extracted string, name the Def type and field or the Keyed key, and say whether you saw the text in the game. For security-sensitive problems, please do not post details publicly; contact the maintainers through the channel listed in the README.
