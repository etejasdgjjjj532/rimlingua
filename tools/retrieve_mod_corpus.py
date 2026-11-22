#!/usr/bin/env python3
"""Acquire a private audit corpus from public author archives and installed mods.

Downloaded content is inspected as data only; no downloaded scripts are executed.
"""
from __future__ import annotations
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from rimworld_translator.platforms import discover_installations
MAX_ARCHIVE = 256 * 1024 * 1024
MAX_TREE = 768 * 1024 * 1024
MAX_FILES = 50000


def utc():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def atomic_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def digest_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def tree_manifest(root):
    result = []
    for p in sorted(root.rglob("*")):
        if p.is_symlink():
            raise ValueError(f"symlink in source: {p}")
        if p.is_file():
            result.append({"path": p.relative_to(root).as_posix(), "bytes": p.stat().st_size,
                           "sha256": digest_file(p)})
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    return result, hashlib.sha256(encoded).hexdigest()


def safe_extract(archive, destination):
    with zipfile.ZipFile(archive) as z:
        members = z.infolist()
        if len(members) > MAX_FILES or sum(i.file_size for i in members) > MAX_TREE:
            raise ValueError("archive expansion limit exceeded")
        names = set()
        for i in members:
            p = PurePosixPath(i.filename)
            mode = i.external_attr >> 16
            if p.is_absolute() or ".." in p.parts or "\\" in i.filename or ":" in i.filename:
                raise ValueError(f"unsafe archive member: {i.filename}")
            if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                raise ValueError(f"non-regular archive member: {i.filename}")
            if i.filename in names:
                raise ValueError(f"duplicate archive member: {i.filename}")
            names.add(i.filename)
        for i in members:
            target = destination.joinpath(*PurePosixPath(i.filename).parts)
            if i.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(i) as source, target.open("wb") as dest:
                    shutil.copyfileobj(source, dest)


def categories(name, root, files, requested):
    cats = set(requested)
    text = name.casefold()
    terms = {"biotech": ("biotech", "races", "xenotype", "genetics"),
             "ideology": ("ideolog",), "royalty": ("royalty", "psycast", "persona"),
             "anomaly": ("anomaly", "insanity"), "combat": ("combat", "ce ", "weapons", "guns", "armor", "armour"),
             "weapons": ("weapon", "gun", "rifle", "launcher"), "apparel": ("apparel", "armor", "armour"),
             "races": ("races", "alien"), "factions": ("faction",), "vehicles": ("vehicle", "ship", "srts"),
             "furniture": ("furniture",), "buildings": ("storage", "power", "hygiene", "factory"),
             "ui": ("hud", "tab", "menu", "minimap", "overlay", "picker", "palette"),
             "performance": ("performance", "rocketman", "pathfinding", "image opt"),
             "libraries": ("framework", "harmony", "hugslib", "prepatcher", "fishery", "lib"),
             "graphics": ("texture", "graphic", "hair", "perspective", "moonlight", "fx"),
             "sound": ("music", "sound", "scream", "poking", "quiet instrument"),
             "translation": ("translation", "localization")}
    for cat, words in terms.items():
        if any(w in text for w in words): cats.add(cat)
    paths = [x["path"].casefold() for x in files]
    has_defs = any("defs/" in x for x in paths)
    has_patches = any("patches/" in x for x in paths)
    has_cs = any(x.endswith(".cs") for x in paths)
    has_dll = any(x.endswith(".dll") for x in paths)
    if has_patches: cats.add("patches")
    if has_patches and not has_defs: cats.add("patch-only")
    if has_cs or has_dll: cats.add("csharp")
    else: cats.add("xml-only")
    if any("/definjected/" in x or "/keyed/" in x for x in paths): cats.add("translation-catalogs")
    if any(re.search(r"(?:^|/)1\.[0-9]+/", x) for x in paths) or (root / "LoadFolders.xml").exists():
        cats.add("version-conditional")
    total = sum(x["bytes"] for x in files)
    cats.add("large" if total >= 20 * 1024 * 1024 else "small")
    if not cats - {"xml-only", "csharp", "small", "large", "version-conditional", "translation-catalogs", "patches"}:
        cats.add("gameplay")
    return sorted(cats), has_cs and not has_dll


def mod_records(base, info, evidence):
    records, excluded = [], []
    abouts = sorted((p for p in base.rglob("*") if p.name.casefold() == "about.xml"
                     and p.parent.name.casefold() == "about"), key=lambda x: (len(x.parts), str(x)))
    for about in abouts:
        relative = about.relative_to(base).as_posix()
        if any(part.casefold() in {"tests", "test", "examples", "example", "templates", "template"}
               for part in about.relative_to(base).parts):
            excluded.append({"source_url": info["source_url"], "about_path": relative, "reason": "test/example metadata"})
            continue
        try:
            data = ET.parse(about).getroot()
            if data.tag.casefold() != "modmetadata": raise ValueError("not ModMetaData")
            name = (data.findtext("name") or "").strip()
            package = (data.findtext("packageId") or "").strip()
            if not name or not package: raise ValueError("missing name/packageId")
            root = about.parent.parent
            files, tree_sha = tree_manifest(root)
            cats, missing = categories(name, root, files, info.get("category", []))
            if info.get("repository_cs_file_count", 0):
                cats = sorted(set(cats) - {"xml-only"} | {"csharp"})
                missing = missing or not any(x["path"].lower().endswith(".dll") for x in files)
            key = re.sub(r"[^A-Za-z0-9_.-]", "_", package.casefold())
            tree_path = evidence / "trees" / (key + "-" + tree_sha[:12] + ".json")
            atomic_json(tree_path, {"source_path": str(root.resolve()), "tree_sha256": tree_sha, "files": files})
            id_path = next((p for p in about.parent.iterdir() if p.name.casefold() == "publishedfileid.txt"), None)
            wid = id_path.read_text().strip() if id_path else info.get("workshop_id", "")
            records.append({**info, "source_path": str(root.resolve()), "name": name, "package_id": package,
                "workshop_id": wid, "category": cats, "about_path": str(about.resolve()),
                "version": data.findtext("modVersion") or "", "supported_versions": [e.text for e in data.findall("supportedVersions/li")],
                "authors": data.findtext("author") or ", ".join(e.text or "" for e in data.findall("authors/li")),
                "tree_manifest_path": str(tree_path.resolve()), "tree_sha256": tree_sha,
                "file_count": len(files), "tree_bytes": sum(x["bytes"] for x in files),
                "mod_family": package.casefold(),
                "source_only_missing_runtime_assemblies": missing or (info.get("repository_cs_file_count", 0) > 0 and not any(x["path"].lower().endswith(".dll") for x in files)),
                "runtime_assembly_status": "source-only-no-DLL" if missing else "DLL-present-or-XML-only",
                "assembly_paths": [x["path"] for x in files if x["path"].lower().endswith(".dll")]})
        except (ET.ParseError, OSError, ValueError) as e:
            excluded.append({"source_url": info["source_url"], "about_path": relative, "reason": str(e)})
    return records, excluded


def acquire(repo, output):
    started = time.monotonic()
    url = "https://github.com/" + repo["repository"]
    attempt = {"source_url": url, "started_at": utc()}
    try:
        sha = repo.get("revision")
        if sha is None:
            cmd = subprocess.run(["git", "ls-remote", url + ".git", "HEAD"], capture_output=True,
                                 text=True, timeout=60, check=True)
            sha = cmd.stdout.split()[0]
        if not re.fullmatch("[0-9a-f]{40}", sha): raise ValueError("invalid Git revision")
        attempt["revision"] = sha
        archive_url = "https://codeload.github.com/" + repo["repository"] + "/zip/" + sha
        attempt["archive_url"] = archive_url
        key = repo["repository"].replace("/", "__") + "-" + sha[:12]
        archive = output / "retrieval" / "archives" / (key + ".zip")
        archive.parent.mkdir(parents=True, exist_ok=True)
        if not archive.exists():
            tmp = archive.with_suffix(".zip.part")
            req = urllib.request.Request(archive_url, headers={"User-Agent": "RimWorldTranslationEditor-private-audit"})
            with urllib.request.urlopen(req, timeout=90) as r, tmp.open("wb") as f:
                size = 0
                while block := r.read(1024 * 1024):
                    size += len(block)
                    if size > MAX_ARCHIVE: raise ValueError("archive download limit exceeded")
                    f.write(block)
            tmp.replace(archive)
        dest = output / "corpus" / key
        if not dest.exists():
            staging = Path(tempfile.mkdtemp(prefix=key + "-", dir=output / "corpus"))
            safe_extract(archive, staging)
            staging.replace(dest)
        repository_root = next((p for p in dest.iterdir() if p.is_dir()), dest)
        repository_files, repository_sha = tree_manifest(repository_root)
        repository_manifest = output / "retrieval/repositories" / (key + ".json")
        atomic_json(repository_manifest, {"source_path": str(repository_root.resolve()), "tree_sha256": repository_sha, "files": repository_files})
        info = {"source_url": url, "revision": sha, "acquisition": "author-github",
                "repository_tree_manifest_path": str(repository_manifest.resolve()), "repository_tree_sha256": repository_sha,
                "archive_url": archive_url, "archive_path": str(archive.resolve()),
                "archive_sha256": digest_file(archive), "archive_bytes": archive.stat().st_size,
                "retrieved_at": utc(), "category": repo.get("category", []),
                "repository_root": str(repository_root.resolve()),
                "repository_root_path": str(repository_root.resolve()),
                "repository_cs_file_count": sum(1 for p in dest.rglob("*") if p.is_file() and p.suffix.casefold() == ".cs"),
                "source_completeness": "public-author-source-archive; runtime completeness not assumed"}
        records, excluded = mod_records(dest, info, output / "retrieval")
        attempt.update(status="acquired" if records else "no-real-mod-root", mod_roots=len(records),
                       archive_bytes=info["archive_bytes"], archive_sha256=info["archive_sha256"])
        return records, excluded, attempt
    except Exception as e:
        attempt.update(status="failed", error=f"{type(e).__name__}: {e}")
        return [], [], attempt
    finally:
        attempt.update(finished_at=utc(), elapsed_seconds=round(time.monotonic() - started, 3))


def enrich_manifest(manifest, output):
    """Fingerprint entire author repository including sibling C# Source folders."""
    repositories = {}
    catalog = {}
    for path in (output / "retrieval").glob("*-repositories.json"):
        for repo in json.loads(path.read_text()):
            catalog[repo["full_name"].casefold()] = repo
    for mod in manifest["mods"]:
        if mod["acquisition"] != "author-github":
            continue
        archive = Path(mod["archive_path"])
        key = archive.stem
        if key not in repositories:
            base = output / "corpus" / key
            root = next((p for p in base.iterdir() if p.is_dir()), base)
            path = output / "retrieval/repositories" / (key + ".json")
            if path.exists():
                previous = json.loads(path.read_text())
                files, sha = previous["files"], previous["tree_sha256"]
            else:
                files, sha = tree_manifest(root)
                atomic_json(path, {"source_path": str(root.resolve()), "tree_sha256": sha, "files": files})
            repo_name = mod["source_url"].removeprefix("https://github.com/")
            metadata = catalog.get(repo_name.casefold(), {})
            license_info = metadata.get("license") or {}
            repositories[key] = {"repository_root": str(root.resolve()), "repository_root_path": str(root.resolve()),
                "repository_tree_sha256": sha, "repository_tree_manifest_path": str(path.resolve()),
                "repository_cs_file_count": sum(x["path"].casefold().endswith(".cs") for x in files),
                "repository_license_spdx": license_info.get("spdx_id", "not-recorded"),
                "repository_license_paths": [x["path"] for x in files if Path(x["path"]).name.casefold().startswith(("license", "copying"))]}
        mod.update(repositories[key])
        missing = mod["repository_cs_file_count"] > 0 and not mod["assembly_paths"]
        mod["source_only_missing_runtime_assemblies"] = missing
        mod["runtime_assembly_status"] = "source-only-no-DLL" if missing else "DLL-present-or-XML-only"
    pinned = {}
    for mod in manifest["mods"]:
        workshop_id = mod.get("workshop_id", "")
        family = "workshop:" + workshop_id if workshop_id.isdigit() else "package:" + mod["package_id"].casefold()
        mod["family_id"] = family
        mod["mod_family"] = family
        if mod["acquisition"] == "author-github":
            repository = mod["source_url"].removeprefix("https://github.com/")
            pinned[(repository, mod["revision"])] = {"repository": repository, "revision": mod["revision"], "category": mod["category"]}
    atomic_json(output / "retrieval/pinned-candidates.json", {"selection": "Immutable revisions of acquired public author repositories; private audit only.", "candidates": list(pinned.values())})
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "artifacts/mod-100-audit")
    parser.add_argument("--candidates", type=Path, default=REPO_ROOT / "artifacts/mod-100-audit/retrieval/candidates.json")
    parser.add_argument("--target", type=int, default=100)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--enrich-only", action="store_true")
    args = parser.parse_args()
    out = args.output.resolve()
    (out / "corpus").mkdir(parents=True, exist_ok=True)
    manifest_path = out / "corpus-manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {
        "schema_version": 1, "created_at": utc(), "target": args.target, "mods": [], "attempts": [], "excluded": []}
    if args.enrich_only:
        enrich_manifest(manifest, out)
        manifest["updated_at"] = utc()
        atomic_json(manifest_path, manifest)
        return 0
    manifest["target"] = args.target
    seen = {x["package_id"].casefold() for x in manifest["mods"]}
    seen_name = {re.sub(r"\s*\(continued\)|\s*\(forked\)|\s*\bfork\b", "", x["name"].casefold()).strip()
                 for x in manifest["mods"]}
    def save():
        manifest["updated_at"] = utc()
        manifest["achieved_count"] = len(manifest["mods"])
        atomic_json(manifest_path, manifest)
        atomic_json(out / "retrieval/progress.json", {"updated_at": utc(), "target": args.target,
            "achieved_count": len(manifest["mods"]), "attempts": len(manifest["attempts"]),
            "failures": sum(x.get("status") == "failed" for x in manifest["attempts"]),
            "state": "target-reached" if len(manifest["mods"]) >= args.target else "acquiring"})
    def add(records, exclusions, attempt):
        manifest["attempts"].append(attempt)
        manifest["excluded"].extend(exclusions)
        for rec in records:
            namekey = re.sub(r"\s*\(continued\)|\s*\(forked\)|\s*\bfork\b", "", rec["name"].casefold()).strip()
            reason = ("duplicate-package-id" if rec["package_id"].casefold() in seen else
                      "same-mod-fork-or-continuation" if namekey in seen_name else
                      "beyond-requested-target" if len(manifest["mods"]) >= args.target else "")
            if reason:
                manifest["excluded"].append({"source_url":rec["source_url"], "package_id":rec["package_id"],
                    "source_path":rec["source_path"], "name":rec["name"], "reason":reason})
            else:
                seen.add(rec["package_id"].casefold()); seen_name.add(namekey); manifest["mods"].append(rec)
        save()
        print(f"{len(manifest['mods'])}/{args.target}: {attempt['source_url']} {attempt['status']}", flush=True)
    installed_done = {x["source_url"] for x in manifest["attempts"] if x.get("acquisition") == "installed-workshop"}
    for installation in discover_installations():
        if not installation.workshop or not installation.workshop.exists(): continue
        for source in sorted(installation.workshop.iterdir()):
            if not source.is_dir(): continue
            url = "https://steamcommunity.com/sharedfiles/filedetails/?id=" + source.name
            if url in installed_done: continue
            if not source.name.isdigit():
                manifest["excluded"].append({"source_path":str(source), "reason":"not a numeric Workshop item directory"}); continue
            try:
                files, sha = tree_manifest(source)
                dest = out / "corpus" / ("workshop-" + source.name)
                if not dest.exists(): shutil.copytree(source, dest, symlinks=False)
                copied, copied_sha = tree_manifest(dest)
                if copied_sha != sha: raise ValueError("installed snapshot does not match original")
                info = {"source_url":url, "original_source_path":str(source.resolve()), "revision":"installed-tree-sha256:" + sha,
                        "acquisition":"installed-workshop", "archive_sha256":None, "archive_path":None,
                        "retrieved_at":utc(), "workshop_id":source.name, "installed_original_tree_sha256":sha,
                        "source_completeness":"read-only installed Workshop snapshot"}
                records, excluded = mod_records(dest, info, out / "retrieval")
                add(records, excluded, {"source_url":url,"acquisition":"installed-workshop","status":"snapshot-verified",
                     "retrieved_at":utc(),"tree_sha256":sha,"original_path":str(source)})
            except Exception as e:
                add([],[],{"source_url":url,"acquisition":"installed-workshop","status":"failed","error":str(e)})
    accepted_urls = {x["source_url"] for x in manifest["mods"]}
    done = {x["source_url"] for x in manifest["attempts"] if x.get("status") == "no-real-mod-root"
            or (x.get("status") == "acquired" and x["source_url"] in accepted_urls)}
    candidates = [x for x in json.loads(args.candidates.read_text())["candidates"]
                  if "https://github.com/" + x["repository"] not in done]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for start in range(0,len(candidates),args.workers):
            if len(manifest["mods"]) >= args.target: break
            for result in pool.map(lambda repo: acquire(repo,out), candidates[start:start+args.workers]): add(*result)
    enrich_manifest(manifest, out)
    save()
    return 0 if len(manifest["mods"]) >= args.target else 2


if __name__ == "__main__":
    raise SystemExit(main())
