"""Repeatable large-editor/persistence check with synthetic, noncopyright inputs."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--entries',type=int,default=30000)
    parser.add_argument('--ram-limit-mib',type=int,default=2048)
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/performance.json')
    args = parser.parse_args()
    if not 10000<=args.entries<=100000:
        parser.error('Use 10000 to 100000 entries')
    if sys.platform.startswith('linux') and args.ram_limit_mib:
        import resource
        maximum = args.ram_limit_mib*1024*1024
        resource.setrlimit(resource.RLIMIT_AS,(maximum,maximum))
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from rimworld_translator.core import Entry,Project,Scan,export_mod
    from rimworld_translator.gui import Window
    from rimworld_translator.workflow import preview_replace,apply_changes
    app = QApplication([])
    report = {'schema':1,'platform':platform.platform(),'qt_backend':app.platformName(),
              'entry_count':args.entries,'languages':3,'ram_limit_mib':args.ram_limit_mib,'timings':{}}
    def measure(name,operation):
        start = time.perf_counter()
        result = operation()
        report['timings'][name] = round(time.perf_counter()-start,4)
        return result
    with tempfile.TemporaryDirectory(prefix='rimworld-performance-') as temporary:
        base = Path(temporary)
        source = base/'source'
        source.mkdir()
        entries = [Entry(f'DefInjected:ThingDef:Item{i}.label','DefInjected','ThingDef',f'Item{i}.label',f'Sample source item {i}','Defs/large.xml') for i in range(args.entries)]
        project = Project.create(source,Scan(entries=entries),['Japanese','French','German'])
        for lang in project.languages:
            project.switch_language(lang)
            for entry in project.entries:
                project.set_translation(entry.id,'sample translation '+str(entry.key))
        project.switch_language('Japanese')
        path = base/'work/project.json'
        measure('initial_save',lambda:project.save(path))
        stamp = path.stat().st_mtime_ns
        measure('unchanged_save',lambda:project.save(path))
        assert path.stat().st_mtime_ns==stamp,'An unchanged save wrote the project again'
        loaded = measure('load',lambda:Project.load(path))
        assert len(loaded.entries)==args.entries and len(loaded.translations)==3
        batch = measure('batch_preview_apply',lambda:apply_changes(loaded,preview_replace(loaded,'sample','replacement').changes))
        measure('batch_undo',lambda:batch.undo(loaded))
        measure('batch_redo',lambda:batch.redo(loaded))
        measure('export_three_languages',lambda:export_mod(loaded,base/'work/mod'))
        generated = {p:p.stat().st_mtime_ns for p in (base/'work/mod').rglob('*') if p.is_file()}
        measure('unchanged_export',lambda:export_mod(loaded,base/'work/mod'))
        assert generated=={p:p.stat().st_mtime_ns for p in generated},'Unchanged export rewrote files'
        loaded.save(path)
        window = Window(settings_path=base/'settings.json')
        window.error = lambda value:(_ for _ in ()).throw(AssertionError(str(value)))
        try:
            measure('gui_load_and_render',lambda:(window.load_project(path),window.show(),app.processEvents()))
            assert window.model.rowCount()==args.entries
            measure('gui_search',lambda:(window.search.setText('Item29999'),app.processEvents()))
            assert window.proxy.rowCount()==(1 if args.entries>=30000 else 0)
            window.search.clear()
            app.processEvents()
            last = window.proxy.index(args.entries-1,0)
            measure('gui_scroll_last',lambda:(window.table.setCurrentIndex(last),window.table.scrollTo(last),app.processEvents()))
            assert window.current.key==f'Item{args.entries-1}.label'
            args.output.parent.mkdir(parents=True,exist_ok=True)
            window.grab().save(str(args.output.with_suffix('.png')))
        finally:
            window.dirty=False
            window.close()
            app.processEvents()
        report['project_size_bytes'] = path.stat().st_size
        report['unchanged_writes_avoided'] = True
        report['batch_verified'] = True
        report['gui_verified'] = True
    if sys.platform.startswith('linux'):
        import resource
        report['peak_rss_mib'] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,1)
        try:
            hardware = subprocess.run(['lspci','-nn'],capture_output=True,text=True,timeout=5)
            report['graphics'] = [line for line in hardware.stdout.splitlines() if 'VGA' in line or 'Display controller' in line]
        except (OSError,subprocess.TimeoutExpired):
            report['graphics'] = []
    report['ok'] = True
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
