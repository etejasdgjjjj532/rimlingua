"""Compile the diagnostic MOD against the installed game's Mono API.

The free Roslyn compiler is cached locally. Game and third-party assemblies
are compiler references only; none are executed by this build process.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
COMPILER_VERSION = "4.14.0"
COMPILER_URL = (
    "https://api.nuget.org/v3-flatcontainer/microsoft.net.compilers.toolset/"
    f"{COMPILER_VERSION}/microsoft.net.compilers.toolset.{COMPILER_VERSION}.nupkg"
)
REFERENCES = (
    "mscorlib.dll", "netstandard.dll", "System.dll", "System.Core.dll", "System.Xml.dll", "Assembly-CSharp.dll",
    "UnityEngine.CoreModule.dll", "UnityEngine.IMGUIModule.dll", "UnityEngine.ScreenCaptureModule.dll",
)


def compiler(cache: Path, allow_download: bool = True) -> Path:
    target = cache / COMPILER_VERSION
    csc = target / "tasks/netcore/bincore/csc.dll"
    if csc.is_file():
        return csc
    if not allow_download:
        raise FileNotFoundError(f"Roslyn compiler not cached: {csc}")
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="roslyn-", dir=cache) as temporary:
        archive = Path(temporary) / "compiler.nupkg"
        with urllib.request.urlopen(COMPILER_URL, timeout=90) as source, archive.open("wb") as output:
            shutil.copyfileobj(source, output)
        destination = Path(temporary) / "package"
        with zipfile.ZipFile(archive) as package:
            package.extractall(destination)
        if not (destination / "tasks/netcore/bincore/csc.dll").is_file():
            raise RuntimeError("Compiler package did not contain csc.dll")
        target.mkdir(parents=True, exist_ok=True)
        shutil.copytree(destination, target, dirs_exist_ok=True)
        (target / "download.json").write_text(json.dumps({
            "url": COMPILER_URL, "version": COMPILER_VERSION,
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "license": "MIT", "source": "https://github.com/dotnet/roslyn",
        }, indent=2) + "\n", encoding="utf-8")
    return csc


def build_probe(game: Path, destination: Path, cache: Path, allow_download: bool = True) -> dict:
    managed = game / "RimWorldLinux_Data/Managed"
    if not managed.is_dir():
        managed = game / "RimWorldWin64_Data/Managed"
    missing = [name for name in REFERENCES if not (managed / name).is_file()]
    if missing:
        raise FileNotFoundError("RimWorld Mono references missing: " + ", ".join(missing))
    dotnet = shutil.which("dotnet")
    if dotnet is None:
        raise FileNotFoundError("The build needs a local dotnet runtime; the released editor does not")
    csc = compiler(cache, allow_download)
    assemblies = destination / "Assemblies"
    assemblies.mkdir(parents=True, exist_ok=True)
    output = assemblies / "RimWorldTranslatorProof.dll"
    source = ROOT / "tools/runtime_probe/TranslationProof.cs"
    argv = [dotnet, str(csc), "-nologo", "-nostdlib+", "-target:library", "-langversion:7.3",
            "-optimize+", "-deterministic+", "-out:" + str(output),
            *["-reference:" + str(managed / name) for name in REFERENCES], str(source)]
    result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                            env={**os.environ, "DOTNET_ROLL_FORWARD": "Major"}, timeout=90)
    if result.returncode:
        raise RuntimeError("Probe compilation failed:\n" + result.stdout + result.stderr)
    about = destination / "About"
    about.mkdir(parents=True, exist_ok=True)
    (about / "About.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ModMetaData><name>RimWorld Translation Runtime Proof</name><author>RimWorld Translation Editor</author>'
        '<packageId>local.rimworldtranslator.runtimeproof</packageId>'
        '<supportedVersions><li>1.6</li></supportedVersions>'
        '<description>Disposable diagnostic window displaying actual loaded ThingDef labels. '
        'Not a gameplay mod.</description></ModMetaData>\n', encoding="utf-8")
    report = {
        "dll": str(output), "compiler_version": COMPILER_VERSION, "compiler_source": COMPILER_URL,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "dll_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "references": [str(managed / name) for name in REFERENCES],
        "command": argv, "third_party_mod_assemblies_executed": False,
    }
    (destination / "build-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--compiler-cache", type=Path, default=ROOT / "artifacts/sol-runtime/compiler")
    parser.add_argument("--no-download", action="store_true")
    args = parser.parse_args()
    print(json.dumps(build_probe(args.game, args.destination, args.compiler_cache, not args.no_download), indent=2))


if __name__ == "__main__":
    main()
