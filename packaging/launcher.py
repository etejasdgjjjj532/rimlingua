"""Portable executable entry point with unattended runtime/GUI verification."""
import json
from pathlib import Path
import sys

from rimworld_translator.version import __version__


def main() -> int:
    if "--version" in sys.argv:
        if sys.stdout is not None:
            print(__version__)
        return 0
    if "--self-test" in sys.argv:
        import dnfile
        import lxml.etree
        import polib
        import PySide6
        import rimworld_translator
        from rimworld_translator.runtime import runtime_evidence

        assets = Path(rimworld_translator.__file__).parent / "assets/flags"
        result = {"version": __version__, "frozen": bool(getattr(sys, "frozen", False)),
                  "python": sys.version.split()[0], "qt": PySide6.__version__,
                  "lxml": lxml.etree.LXML_VERSION, "dnfile": dnfile.__version__,
                  "polib": polib.__version__, "flag_count": len(list(assets.glob("*.svg"))),
                  **runtime_evidence()}
        result["ok"] = result["flag_count"] >= 29 and (assets / "LICENSE").is_file()
        encoded = json.dumps(result, indent=2)
        if "--report" in sys.argv:
            path = Path(sys.argv[sys.argv.index("--report") + 1])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(encoded, encoding="utf-8")
        if sys.stdout is not None:
            print(encoded)
        return 0 if result["ok"] else 1
    if "--verify-gui" in sys.argv:
        from tools.verify_native_gui import main as verify
        args = sys.argv[1:]
        args.remove("--verify-gui")
        return verify(args)
    from rimworld_translator.gui import main as launch
    return launch()


if __name__ == "__main__":
    raise SystemExit(main())
