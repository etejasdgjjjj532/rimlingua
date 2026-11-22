# Installation and distribution

## Users: Windows 10/11

A Windows x64 EXE/ZIP is generated locally in `dist/windows-wine/`.
The `wine-preview` in the file name marks a preview built under Wine for
auxiliary verification only.
Launching on a real Windows 10/11 machine, DPI behavior, and native builds have
not been verified.
The extraction steps below apply to both the preview and future native Windows
builds.
For the Windows Wine preview, the extracted EXE was launched on a PATH without
Python or Git, and editing, saving, XML export, and file history were checked at
100%/200% scale.
This is not verification on a real Windows machine or of the in-game display on
Windows.

1. Download the **Windows x86_64 ZIP** from the distribution page. A public
   repository and distribution page have not been created yet. Use the locally
   generated artifacts or the Actions artifacts described below. No made-up
   download URL has been configured.
2. Right-click the ZIP and choose **Extract All**. Do not launch the app from
   inside the ZIP.
3. Double-click **RimWorldTranslationEditor.exe** in the extracted
   `RimWorldTranslationEditor` folder.
4. Use **New translation** to select the source MOD and choose the languages
   and where to save your work. To continue existing work, use **Open project**
   and open its `project.json`.

Installing Python, Git, or VS Code is not required. RimWorld and the source MOD
are still needed separately.
`_internal/` is the folder required to run Python, Qt, and the other bundled
components. The app will not start if you move only the EXE. When you create a
shortcut to the app, point it at the EXE.
This app is not code-signed. Verify the download source and the SHA-256 before
use.

## Users: Linux

1. Download the **Linux x86_64 tar.gz** and extract it with an archive manager.
2. Run the file of the same name inside the extracted
   `RimWorldTranslationEditor` folder. If your file manager does not allow it to
   launch, enable "Executable" in that file's properties.
3. You can also launch it from a terminal.

```bash
cd /path/to/RimWorldTranslationEditor
chmod +x RimWorldTranslationEditor
./RimWorldTranslationEditor
```

Python and Git are not needed separately. The OS's glibc, X11 or Wayland, fonts,
and similar components are required. This is an onedir portable distribution,
not an AppImage.
A Linux binary may fail to start on a glibc older than the one of the OS it was
built on.
The `libc` and `host` fields in `release-manifest.json` hold the actual values of
the build environment.
The portability of this local Arch build is not the same as that of a build made
on an Ubuntu 22.04 runner. The CI build is configured to be produced on an older
Ubuntu.

## Opening, moving, and updating a translation project

- Work data is stored in a folder separate from where the app is extracted. The
  default suggestion is `Documents/RimWorldTranslations/`.
- To move or back up a project, copy the **entire project folder**, including
  `project.json`, the history, and the generated `mod/`. If the location of the
  source MOD has changed, keep the old project, create a new project from the
  new source MOD, and import the translations from the old `mod/`. Past review
  states and history remain in the old project.
- Before updating the app, save your work, then copy and keep the project
  folder. Extract the new app into a **separate folder**, launch it, and open the
  existing `project.json`. Keep the previous app until you have confirmed that
  opening, editing, saving, and exporting work.
- Updating a source MOD is separate from updating the app. Use **Rescan source
  MOD** to pull in the changes and review the translations whose original text
  changed. Do not specify the source MOD or the game folder as the location
  where your work is saved.
- Update checking is disabled by default. Only when the user enables it and a
  real public GitHub `owner/repository` is configured does the app check for the
  latest stable release. It sends no translation text, projects, or usage
  statistics to GitHub and reads only the anonymous release API. It performs no
  automatic installation or automatic overwriting.
  If no distribution source is configured, it makes no network request and
  treats this as "distribution source not configured".

## Developers: Building on the same OS

PyInstaller is not a cross-compiler for other operating systems. Build the
Windows EXE on Windows and the Linux binary on Linux. Python 3.11 or later is
required.
Python and the dependency libraries are needed only for development; end users
are given the bundled distribution.

Linux:


```bash
python3 -m venv .venv
.venv/bin/python -m pip install '.[dev]'
.venv/bin/python tools/run_tests.py
.venv/bin/python tools/build_portable.py --dry-run
.venv/bin/python tools/build_portable.py
```

Windows PowerShell:


```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install '.[dev]'
.venv\Scripts\python.exe tools/run_tests.py
.venv\Scripts\python.exe tools/build_portable.py --dry-run
.venv\Scripts\python.exe tools/build_portable.py
```

The output is `dist/RimWorldTranslationEditor/` and the following
archives/checksums.


```text
dist/rimworld-translation-editor-0.4.0-linux-x86_64.tar.gz
dist/rimworld-translation-editor-0.4.0-linux-x86_64.tar.gz.sha256
dist/rimworld-translation-editor-0.4.0-windows-x86_64.zip
dist/rimworld-translation-editor-0.4.0-windows-x86_64.zip.sha256
dist/build-report.json
```

The build launches the bundled binary in a separate process with `--self-test`
and checks the Python/Qt/XML/PO/CLR-metadata dependencies and the flag assets.
Before an archive is created, it verifies that no game files, MOD files, or
private working data have been included. The licenses of the dependencies are
collected in `licenses/`.
The public license of the editor itself has not yet been chosen by the author, so
it must be decided before publication.

## Verifying the native GUI / HiDPI

GUI verification uses only synthetic translation projects. It does not capture
the original MOD or game images. At 100% and 200% it checks the layout of the
table, the edit fields, and the save/export buttons, the accessible names, Tab
navigation, item selection, and PNG saving.

Linux desktop:


```bash
QT_QPA_PLATFORM=xcb QT_SCALE_FACTOR=1 .venv/bin/python tools/run_tests.py --script tools/verify_native_gui.py --require-native --output artifacts/gui-linux-1
QT_QPA_PLATFORM=xcb QT_SCALE_FACTOR=2 .venv/bin/python tools/run_tests.py --script tools/verify_native_gui.py --require-native --output artifacts/gui-linux-2
QT_SCALE_FACTOR=1 dist/RimWorldTranslationEditor/RimWorldTranslationEditor --verify-gui --require-native --output artifacts/binary-linux-1
```

Windows PowerShell:


```powershell
$env:QT_QPA_PLATFORM = 'windows'
$env:QT_SCALE_FACTOR = '1'
.venv\Scripts\python.exe tools/run_tests.py --script tools/verify_native_gui.py --require-native --output artifacts/gui-windows-1
$env:QT_SCALE_FACTOR = '2'
.venv\Scripts\python.exe tools/run_tests.py --script tools/verify_native_gui.py --require-native --output artifacts/gui-windows-2
Start-Process -Wait dist\RimWorldTranslationEditor\RimWorldTranslationEditor.exe -ArgumentList '--verify-gui --require-native --output artifacts/binary-windows-2'
```

To verify an extracted EXE on Windows 10/11, no development Python is needed
either. In PowerShell, move to the extraction folder and run the following. It
uses synthetic working data, so it does not change any real MOD, save, or game
settings.

```powershell
$env:QT_QPA_PLATFORM = 'windows'
foreach ($scale in 1, 2) {
    $env:QT_SCALE_FACTOR = "$scale"
    $process = Start-Process -FilePath '.\RimWorldTranslationEditor.exe' -ArgumentList "--verify-gui --require-native --require-windows-client --output verification/windows-scale-$scale" -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Windows client GUI verification failed at scale $scale" }
    $report = Get-Content "verification/windows-scale-$scale/gui-report.json" -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $report.ok -or -not $report.native_windows_client_gui) { throw 'Native Windows 10/11 evidence is missing' }
}
```

This strict check does not succeed on Wine, offscreen, or Windows Server.
The JSON and PNG files in `verification/` are the material required for the next
verification on a real Windows machine.

Once the 100%/200% reports for the same EXE are available, you can bundle the
verification evidence and finalize the archive and SHA-256 in the development
environment as follows. Reports with a different EXE SHA-256, failed operations
or layouts, only one of the two scales, or results that treat Wine as native are
rejected.

```powershell
.venv\Scripts\python.exe tools/verify_portable_archive.py --build-output dist --output artifacts/extracted --require-windows-client
.venv\Scripts\python.exe tools/build_portable.py --finalize artifacts/extracted/scale-1/gui-report.json artifacts/extracted/scale-2/gui-report.json
```

Save `gui-report.json` and the PNGs of the normal and compact layouts in each
folder.
An offscreen result with `native: false` is not evidence of a native display.
Results from Wine or Linux are never recorded as confirming Windows 10/11.
Even when the window is larger than the virtual screen, the actual value is
recorded in `fits_screen`.

## GitHub Actions and releases

`.github/workflows/build.yml` runs, on standard Ubuntu 22.04 / Windows runners,
the full test suite, native GUI captures at 100%/200%, the OS-specific builds,
and a GUI check of the bundled EXE, and saves the archives, checksums,
diagnostic JSON, and PNGs as Actions artifacts.
The default configuration is limited to standard runners of a public repository.
For a private repository, select the manual input
`private_free_quota_confirmed=true` only if you have checked the free quota and
the billing-stop settings yourself. The workflow does not use larger runners.
For GitHub's explanation of the free quota, see the official documents below.

Currently no remote repository or native Windows machine is connected, and no
results have been obtained for a Windows build, the Windows GUI, or a GitHub CI
run. The Windows EXE has been generated as a local Wine preview. GitHub CLI
authentication is available, but the billing, usage, and budget APIs returned
404, so the free quota and the stop-on-overage setting could not be verified.
Until that can be confirmed, no private Actions will be started. Creating,
pushing to, and publishing a public repository requires the author's explicit
permission. The existence of a workflow is not evidence that it has been run.

The standard `windows-latest` verifies on Windows Server, which is separate from
verification on a Windows 10/11 desktop. The manual input
`verify_windows11_client=true` verifies the same x64 ZIP at 100%/200% on the
standard `windows-11-arm` runner through Windows x64 emulation. This is a result
from a real Windows 11 OS, but not from x64 hardware. The additional evidence on
success is saved in the `verification-windows11-client-x64-emulation` artifact,
and nothing rewrites the manifest of the original ZIP built on Server as
desktop-verified.

Steps after publication is permitted and a remote repository is available:

1. Confirm all tests and the native GUI, then update `version.py` and the
   CHANGELOG.
2. After checking the code and license to be published, push the commit and the
   `v0.4.0` tag. This tool and workflow neither create a repository nor
   automatically push local code.
3. Open **Portable release** in Actions and run it with the tag specified.
   `publish=false` is the default and first produces only build/test artifacts.
4. Check the diagnostic JSON and PNGs for Windows/Linux. Only if both OSes are
   green, re-run with `publish=true` to attach the archives/checksums for both
   OSes to a **draft release**. The protection rules of the `release`
   environment can also be used.
5. Check the draft's changelog, downloads, and copyright notices, and the author
   performs the final publication from the GitHub UI. Issue templates for bug
   reports and feature requests are also provided.

A bug report should include the OS, the app version, the GUI scale, the
reproduction steps, and the expected result.
`gui-report.json` and `release-manifest.json` are useful, but do not attach the
original text of a real project, private files of the source MOD, or personal
paths without permission.

Official specifications: [PyInstaller native bundles](https://pyinstaller.org/en/stable/usage.html),
[Qt HiDPI](https://doc.qt.io/qt-6/highdpi.html),
[GitHub standard runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners),
[GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions),
[spending budgets](https://docs.github.com/en/billing/how-tos/set-up-budgets).

## English quick setup and upgrade guide

Download the archive for your OS. A public release repository has not yet been
configured, so use the local build or Actions artifact until the author publishes
one. On Windows, extract the **entire ZIP** and double-click
`RimWorldTranslationEditor.exe`. On Linux, extract the **entire tar.gz** and run
`RimWorldTranslationEditor` (enable executable permission if needed). Keep the
`_internal/` directory next to the executable. End users do not install Python,
Git, or VS Code. RimWorld and your source MOD are separate prerequisites.

Start a translation with the new-MOD action, choose languages, and keep the
workspace outside the application folder. Reopen existing work by selecting
`project.json`. Save and export your translation; follow the editor's install
instructions for your local game. The editor distribution contains no game/MOD
assets. Check the source author's license before publishing generated previews.

To upgrade, save and back up the **whole project folder**, extract the new app
into a **new folder**, and reopen `project.json`. Verify editing, saving and
exporting before retiring the older app. Application upgrades and source-MOD
rescans are independent. Update lookup is anonymous and opt-in; no repository
is guessed, no project text is uploaded, and nothing is automatically installed.

Developers: create a Python 3.11+ virtual environment, run
`python -m pip install '.[dev]'`, `python tools/run_tests.py`, and
`python tools/build_portable.py` **on the target OS**. PyInstaller is not a
cross-compiler. Linux archives need a compatible glibc and graphical desktop;
the actual build platform is in `release-manifest.json`. The local Arch build
has a newer libc baseline than the configured Ubuntu CI build.

The CI matrix is configured to run native Windows Server/Linux binaries and save
100%/200% GUI captures plus accessibility and geometry reports. The optional
`verify_windows11_client` job tests the same x64 ZIP on the standard Windows 11
Arm64 runner using Windows x64 emulation; separate client evidence is uploaded
without changing the Server-built ZIP manifest. Offscreen/Wine never count as
native Windows evidence. A local Windows Wine-preview EXE exists, but native
Windows and hosted CI results remain unverified. GitHub authentication works;
free-quota and paid-overage blocking could not be verified through billing APIs.
No private CI job, public push or publication was initiated. Release publishing defaults to off and can create a draft only after
both OS jobs pass. The author must choose the editor source license before
public distribution. See `licenses/` for third-party terms and `CHANGELOG.md`
for release changes.
