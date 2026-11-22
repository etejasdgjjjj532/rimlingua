"""Run an extracted portable app from another directory with Python/Git off PATH."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rimworld_translator.runtime import runtime_evidence


def verify(archive_path: Path, output_path: Path, *, allow_wine: bool = False, require_windows_client: bool = False) -> dict:
    evidence = runtime_evidence()
    if evidence['wine'] and not allow_wine:
        raise ValueError('Wine archive tests are supplementary; explicitly select --allow-wine.')
    if allow_wine and not evidence['wine']:
        raise ValueError('--allow-wine requires Windows Python running under Wine.')
    output_path = output_path.resolve()
    output_path.mkdir(parents=True,exist_ok=True)
    environment = dict(os.environ,PATH='')
    for name in ('PYTHONHOME','PYTHONPATH','VIRTUAL_ENV','CONDA_PREFIX'):
        environment.pop(name,None)
    report = {'archive':str(archive_path.resolve()),'external_python_and_git_on_path':False,'gui':[],
              'wine':evidence['wine'], 'native_windows_verified':False, 'native_windows_client_verified':False,
              'validation_scope':'wine-supplementary' if evidence['wine'] else 'native-gui'}
    with tempfile.TemporaryDirectory(prefix='rimworld-portable-archive-') as folder:
        root = Path(folder)
        if archive_path.suffix=='.zip':
            with zipfile.ZipFile(archive_path) as archive:
                for name in archive.namelist():
                    if not (root/name).resolve().is_relative_to(root):
                        raise ValueError('Archive contains a path outside its destination')
                archive.extractall(root)
        else:
            with tarfile.open(archive_path) as archive:
                archive.extractall(root,filter='data')
        bundle = root/'RimWorldTranslationEditor'
        executable = bundle/('RimWorldTranslationEditor.exe' if sys.platform=='win32' else 'RimWorldTranslationEditor')
        def run(arguments):
            result = subprocess.run([str(executable),*arguments],cwd=root,env=environment,
                                    capture_output=True,text=True,timeout=60)
            if result.returncode:
                raise RuntimeError(f'Portable process failed ({result.returncode}): {result.stderr}\n{result.stdout}')
        self_test = output_path/'self-test.json'
        run(['--self-test','--report',str(self_test)])
        report['self_test'] = json.loads(self_test.read_text(encoding='utf-8'))
        assert report['self_test']['ok'] and report['self_test']['frozen']
        for scale in ('1','2'):
            environment['QT_SCALE_FACTOR'] = scale
            output = output_path/f'scale-{scale}'
            arguments = ['--verify-gui','--output',str(output)]
            if not evidence['wine']:
                arguments.append('--require-native')
            if require_windows_client:
                arguments.append('--require-windows-client')
            run(arguments)
            gui = json.loads((output/'gui-report.json').read_text(encoding='utf-8'))
            assert gui['ok'] and gui['frozen']
            if evidence['wine']:
                assert not gui['native'] and gui['wine'] and gui['os']=='win32' and gui['qt_backend']=='windows'
            else:
                assert gui['native'] and not gui.get('wine')
            if require_windows_client:
                assert gui.get('native_windows_client_gui') is True
            assert gui['save_verified'] and gui['export_verified'] and gui['history_verified']
            assert gui['history_backends']==['file'], 'An external Git process was unexpectedly used'
            report['gui'].append({'scale':scale,'report':str(output/'gui-report.json'),
                                  'native':gui['native'],'wine':gui.get('wine',False),'frozen':gui['frozen'],'save_verified':True,
                                  'export_verified':True,'history_backends':gui['history_backends']})
        report['beginner_docs_present'] = all((bundle/name).is_file() for name in (
            'README.md','README.ja.md','docs/GETTING_STARTED.md','docs/GETTING_STARTED.ja.md','docs/DISTRIBUTION.md'))
        assert report['beginner_docs_present']
        report['native_windows_verified'] = sys.platform=='win32' and not evidence['wine']
        report['native_windows_client_verified'] = require_windows_client and report['native_windows_verified']
        report['ok'] = True
    (output_path/'archive-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--archive',type=Path)
    source.add_argument('--build-output',type=Path,help='Use the archive recorded by build_portable.py; works after version bumps')
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/portable-archive-verification')
    parser.add_argument('--allow-wine',action='store_true',help='Supplementary tests only; never native Windows evidence')
    parser.add_argument('--require-windows-client',action='store_true',help='Require Windows10/11 desktop OS, not Server/Wine/offscreen')
    args = parser.parse_args()
    if args.build_output:
        manifest = json.loads((args.build_output/'build-report.json').read_text(encoding='utf-8'))
        args.archive = Path(manifest['archive'])
        if manifest.get('application')!='rimworld-translation-editor' or args.archive.resolve().parent!=args.build_output.resolve():
            parser.error('Build report must point to an editor archive in the selected output directory.')
    report = verify(args.archive,args.output,allow_wine=args.allow_wine,require_windows_client=args.require_windows_client)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
