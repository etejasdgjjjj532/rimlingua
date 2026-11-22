"""Dialogs for the quality check, export review, sharing and multi-version tools.

They only present and collect; every decision is made by the backend modules (qa, export_diff, workshop,
interchange, multiversion, notes, scan_context). Copy goes through ``window.tr(ja, en)``.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                               QTableWidget, QTableWidgetItem, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .languages import LANGUAGES

ID_ROLE = Qt.UserRole + 7
_MAX_CHILDREN = 400   # per file in the export diff; the rest is summarised


def make_tree(headers, widths=()) -> QTreeWidget:
    view = QTreeWidget()
    view.setHeaderLabels(list(headers))
    view.setRootIsDecorated(False)
    view.setUniformRowHeights(True)
    view.setAlternatingRowColors(True)
    view.setEditTriggers(QAbstractItemView.NoEditTriggers)
    for column, width in enumerate(widths):
        view.setColumnWidth(column, width)
    return view


def language_label(code: str) -> str:
    return LANGUAGES[code][0].split('  (')[0] if code in LANGUAGES else code


def preflight_for(project, language=None):
    from .qa import preflight
    return preflight(project, language)


def scanned_versions(project) -> list[str]:
    """Versions that hold extracted rows (the editing version plus every stored profile), oldest first."""
    from .core import _version_key
    found = set(project.version_profiles) | {project.game_version}
    return sorted(found, key=_version_key)


def version_combo(project, current=None) -> QComboBox:
    combo = QComboBox()
    for version in scanned_versions(project):
        combo.addItem(version, version)
    if current is not None:
        combo.setCurrentIndex(max(0, combo.findData(current)))
    return combo


def language_combo(window, with_all=False) -> QComboBox:
    combo = QComboBox()
    if with_all:
        combo.addItem(window.tr('選んだ全言語', 'All selected languages'), None)
    for code in window.project.languages:
        combo.addItem(language_label(code), code)
    combo.setCurrentIndex(0 if with_all else max(0, combo.findData(window.project.language)))
    return combo


def row_key(entry_id):
    """The key part of a row id (``Kind:Group:key``); the key itself may contain colons."""
    return entry_id.split(':', 2)[-1]


def _item(columns, entry_id='', tooltip=''):
    item = QTreeWidgetItem([str(c) for c in columns])
    item.setData(0, ID_ROLE, entry_id)
    if tooltip:
        for column in range(len(columns)):
            item.setToolTip(column, tooltip)
    return item


# --- Quality check -------------------------------------------------------------------------------------------

STYLE_CODES = {'width_mixing', 'halfwidth_kana', 'same_as_source', 'sentence_ending', 'style_mixing'}


class PreflightView(QTabWidget):
    """The findings of ``qa.preflight`` in tabs; activating a row emits its entry id as ``jump``."""
    jump = Signal(str)

    def __init__(self, project, report, tr, parent=None):
        super().__init__(parent)
        self.setObjectName('preflightView')
        index = project.entry_index()

        def key(entry_id):
            entry = index.get(entry_id)
            return entry.key if entry else entry_id

        def issue_rows(issues):
            return [_item((key(i.entry_id), i.message, i.suggestion), i.entry_id, i.message) for i in issues]

        warnings = list(report.warnings)
        groups = {
            'errors': (tr('エラー', 'Errors'), issue_rows(report.errors)),
            'outdated': (tr('原文が変わった', 'Source changed'), issue_rows([w for w in warnings if w.code == 'source_changed'])),
            'style': (tr('表記・文体', 'Style'), issue_rows([w for w in warnings if w.code in STYLE_CODES])),
            'warnings': (tr('その他の警告', 'Other warnings'),
                         issue_rows([w for w in warnings if w.code != 'source_changed' and w.code not in STYLE_CODES])),
            'untranslated': (tr('未訳', 'Untranslated'),
                             [_item((e.key, e.english, ''), e.id, e.english) for e in report.untranslated]),
            'reviewed': (tr('確認済みなのにエラー', 'Reviewed with errors'), issue_rows(report.reviewed_with_errors)),
        }
        self.lists = {}
        headers = (tr('項目', 'Row'), tr('内容', 'Detail'), tr('直し方', 'Hint'))
        for name, (title, rows) in groups.items():
            view = make_tree(headers, (230, 420))
            view.setObjectName('preflight_' + name)
            for row in rows:
                view.addTopLevelItem(row)
            view.itemActivated.connect(lambda item, _c=0: self._emit(item))
            view.itemClicked.connect(lambda item, _c=0: self._emit(item))
            self.lists[name] = view
            self.addTab(view, f'{title} ({len(rows)})')
        filled = next((i for i, v in enumerate(self.lists.values()) if v.topLevelItemCount()), 0)
        self.setCurrentIndex(filled)

    def _emit(self, item):
        entry_id = item.data(0, ID_ROLE)
        if entry_id:
            self.jump.emit(entry_id)

    def counts(self) -> dict:
        return {name: view.topLevelItemCount() for name, view in self.lists.items()}


def preflight_summary(report, tr) -> str:
    return tr(f'エラー {len(report.errors)} 件 / 警告 {len(report.warnings)} 件 / 未訳・原文のまま {len(report.untranslated)} 件 / '
              f'英文変更あり {len(report.outdated)} 件 / 確認済みなのにエラー {len(report.reviewed_with_errors)} 件',
              f'{len(report.errors)} errors / {len(report.warnings)} warnings / {len(report.untranslated)} untranslated / '
              f'{len(report.outdated)} with changed source / {len(report.reviewed_with_errors)} reviewed with errors')


class QualityDialog(QDialog):
    """Non-modal quality check: stays open beside the editor so rows can be visited one after another."""
    def __init__(self, window):
        super().__init__(window)
        self.window_ = window
        tr = window.tr
        self.setObjectName('qualityCheck')
        self.setWindowTitle(tr('品質チェック', 'Quality check'))
        self.resize(900, 560)
        self.layout_ = QVBoxLayout(self)
        top = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        top.addWidget(self.summary, 1)
        self.language = language_combo(window)
        self.language.setVisible(len(window.project.languages) > 1)
        self.language.currentIndexChanged.connect(self.refresh)
        top.addWidget(self.language)
        again = QPushButton(tr('もう一度調べる', 'Check again'))
        again.clicked.connect(self.refresh)
        top.addWidget(again)
        self.layout_.addLayout(top)
        self.hint = QLabel()
        self.hint.setObjectName('muted')
        self.hint.setWordWrap(True)
        self.layout_.addWidget(self.hint)
        self.view = None
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.close)
        self.layout_.addWidget(buttons)
        self.refresh()

    def refresh(self, *_):
        window, tr = self.window_, self.window_.tr
        window.edit_detail()
        language = self.language.currentData()
        report = preflight_for(window.project, language)
        if self.view is not None:
            self.layout_.removeWidget(self.view)
            self.view.deleteLater()
        self.view = PreflightView(window.project, report, tr)
        self.view.jump.connect(self.go)
        self.layout_.insertWidget(2, self.view, 1)
        self.report = report
        self.summary.setText(preflight_summary(report, tr))
        other = language and language != window.project.language
        self.hint.setText(tr('行をクリックすると、その項目へ移動します。', 'Click a row to jump to it in the editor.')
                          + (tr(f'（表は {window.project.language} を表示中。この言語で確認するには切り替えてください）',
                                f' (The table shows {window.project.language}; switch to it to edit this language.)') if other else ''))

    def go(self, entry_id):
        self.window_.navigate_entry(entry_id)
        self.raise_()
        self.activateWindow()


# --- Export review -------------------------------------------------------------------------------------------

class ExportReviewDialog(QDialog):
    """What the export would do: the pre-flight verdict and a before/after file diff. Accepting means "write it"."""
    def __init__(self, window, report, diff, blocked, output):
        super().__init__(window)
        tr = window.tr
        self.window_, self.report, self.diff, self.blocked = window, report, diff, blocked
        self.open_quality = False
        self.can_export = diff is not None and blocked is None and report.ok
        self.setObjectName('exportReview')
        self.setWindowTitle(tr('書き出しの確認', 'Review before export'))
        self.resize(860, 600)
        layout = QVBoxLayout(self)
        verdict = QLabel()
        verdict.setWordWrap(True)
        verdict.setObjectName('exportVerdict')
        if self.can_export:
            verdict.setText(tr('出力前チェックでエラーはありません。下の変更を書き出します。',
                               'The pre-flight check found no errors. The changes below will be written.'))
        else:
            verdict.setText(tr('エラーがあるため書き出せません。下の項目を直してから、もう一度書き出してください。'
                               '（出力はまだ何も変更していません）',
                               'Export is blocked by errors. Fix the rows below and export again. (Nothing has been changed.)'))
        layout.addWidget(verdict)
        self.summary = QLabel(preflight_summary(report, tr))
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        layout.addWidget(QLabel(tr(f'出力先: {output}', f'Destination: {output}')))
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.changes = make_tree((tr('変更', 'Change'), tr('ファイル / キー', 'File / key')), (140,))
        self.changes.setRootIsDecorated(True)
        self.problems = make_tree((tr('項目', 'Row'), tr('理由', 'Reason')), (260,))
        if diff is not None:
            self._fill_changes(tr)
            self.tabs.addTab(self.changes, tr('出力の変更', 'Output changes'))
        entries = list(blocked.entries) if blocked is not None and hasattr(blocked, 'entries') else []
        if entries:
            index = window.project.entry_index()
            for language, entry_id, message in entries:
                entry = index.get(entry_id)
                self.problems.addTopLevelItem(_item((entry.key if entry else entry_id, message), entry_id, message))
        else:
            for issue in report.errors:
                self.problems.addTopLevelItem(_item((row_key(issue.entry_id), issue.message), issue.entry_id))
        if self.problems.topLevelItemCount():
            self.tabs.insertTab(0, self.problems, tr('出力できない項目', 'Blocking rows'))
            self.tabs.setCurrentIndex(0)
        self.preflight = PreflightView(window.project, report, tr)
        self.tabs.addTab(self.preflight, tr('チェック結果', 'Check results'))
        if diff is not None and diff.warnings:
            notes = QPlainTextEdit('\n'.join(diff.warnings[:300]))
            notes.setReadOnly(True)
            self.tabs.addTab(notes, tr(f'出力時の注意 ({len(diff.warnings)})', f'Output notices ({len(diff.warnings)})'))
        buttons = QDialogButtonBox()
        self.export_button = buttons.addButton(tr('書き出す', 'Export'), QDialogButtonBox.AcceptRole)
        self.export_button.setEnabled(self.can_export)
        self.export_button.setDefault(self.can_export)
        quality = buttons.addButton(tr('品質チェックを開く', 'Open quality check'), QDialogButtonBox.ActionRole)
        buttons.addButton(QDialogButtonBox.Cancel)
        quality.clicked.connect(self._quality)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _quality(self):
        self.open_quality = True
        self.reject()

    def _fill_changes(self, tr):
        diff = self.diff
        if diff.empty:
            self.changes.addTopLevelItem(_item((tr('変更なし', 'No changes'),
                                                tr(f'出力は今のまま（{diff.unchanged} ファイル）。', f'The output stays as it is ({diff.unchanged} files).'))))
            return
        for label, files in ((tr('追加', 'Added'), diff.added), (tr('変更', 'Changed'), diff.changed), (tr('削除', 'Removed'), diff.removed)):
            for change in files:
                parent = _item((label, change.path))
                lines = ([('+', k) for k in change.keys_added] + [('~', k) for k in change.keys_changed]
                         + [('-', k) for k in change.keys_removed])
                if lines:
                    parent.setText(1, f'{change.path}  ({len(change.keys_added)} +, {len(change.keys_changed)} ~, {len(change.keys_removed)} -)')
                for sign, name in lines[:_MAX_CHILDREN]:
                    parent.addChild(_item((sign, f'{sign} {name}')))
                if len(lines) > _MAX_CHILDREN:
                    parent.addChild(_item(('…', tr(f'他 {len(lines) - _MAX_CHILDREN} 件', f'{len(lines) - _MAX_CHILDREN} more'))))
                self.changes.addTopLevelItem(parent)
        footer = _item(('', tr(f'変更なし {diff.unchanged} ファイル', f'{diff.unchanged} files unchanged')))
        self.changes.addTopLevelItem(footer)


# --- Workshop material ---------------------------------------------------------------------------------------

class WorkshopDialog(QDialog):
    """Draft Steam Workshop text (title, description, changelog, checklist) and save it as text files. Never publishes."""
    def __init__(self, window):
        super().__init__(window)
        self.window_ = window
        tr = window.tr
        project = window.project
        self.setObjectName('workshopMaterial')
        self.setWindowTitle(tr('Workshop 用の文章を作る', 'Workshop page material'))
        self.resize(820, 640)
        layout = QVBoxLayout(self)
        note = QLabel(tr('Steam に公開するのはあなた自身です。ここではタイトル・説明・更新内容・公開前チェックのテキストを作るだけで、何も送信しません。',
                         'You publish in Steam yourself. This only drafts text files; nothing is uploaded.'))
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.translator = QLineEdit(window.settings.data['default_translator'] or project.metadata.get('author', ''))
        self.version_note = QLineEdit()
        self.version_note.setPlaceholderText(tr('例: 1.6 に対応、武器の名前を修正', 'e.g. Updated for 1.6, fixed weapon names'))
        self.include_diff = QCheckBox(tr('更新内容に出力ファイルの変化を含める', 'List output file changes in the changelog'))
        self.include_diff.setChecked(True)
        self.folder = QLineEdit(str(window.project_path.parent / 'workshop-material'))
        choose = QPushButton(tr('選ぶ…', 'Browse…'))
        choose.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.folder, 1)
        row.addWidget(choose)
        form.addRow(tr('翻訳者名', 'Translator'), self.translator)
        form.addRow(tr('バージョンのメモ', 'Version note'), self.version_note)
        form.addRow(self.include_diff)
        form.addRow(tr('保存先フォルダー', 'Save to folder'), row)
        layout.addLayout(form)
        self.tabs = QTabWidget()
        self.views = {}
        for name, title in (('description', tr('説明 (BBCode)', 'Description (BBCode)')), ('changelog', tr('更新内容', 'Changelog')),
                            ('checklist', tr('公開前チェック', 'Checklist')), ('title', tr('タイトル', 'Title'))):
            view = QPlainTextEdit()
            view.setReadOnly(True)
            self.views[name] = view
            self.tabs.addTab(view, title)
        layout.addWidget(self.tabs, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox()
        preview = buttons.addButton(tr('プレビューを更新', 'Refresh preview'), QDialogButtonBox.ActionRole)
        self.write_button = buttons.addButton(tr('ファイルに保存', 'Write files'), QDialogButtonBox.ActionRole)
        buttons.addButton(QDialogButtonBox.Close)
        preview.clicked.connect(self.refresh)
        self.write_button.clicked.connect(self.write)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def _browse(self):
        chosen = QFileDialog.getExistingDirectory(self, self.window_.tr('保存先を選ぶ', 'Choose folder'), self.folder.text())
        if chosen:
            self.folder.setText(chosen)

    def _options(self) -> dict:
        diff, note = None, ''
        if self.include_diff.isChecked():
            try:
                from .export_diff import export_diff
                self.window_.edit_detail()
                diff = export_diff(self.window_.project, self.window_.output_folder())
            except (ValueError, OSError) as exc:
                note = self.window_.tr('（出力ファイルの変化は含めていません: ', '(Output changes left out: ') + (self.window_.error_text(exc).splitlines() or [''])[0] + '）'
        self._diff_note = note
        return {'translator': self.translator.text().strip(), 'diff': diff, 'version_note': self.version_note.text().strip()}

    def refresh(self):
        from .workshop import workshop_material
        material = workshop_material(self.window_.project, **self._options())
        for name, view in self.views.items():
            view.setPlainText(getattr(material, name))
        self.status.setText(self._diff_note)

    def write(self):
        from .workshop import write_workshop_material
        window, tr = self.window_, self.window_.tr
        try:
            written = write_workshop_material(window.project, Path(self.folder.text().strip()), **self._options())
        except (ValueError, OSError) as exc:
            window.error(window.error_text(exc))
            return []
        self.status.setText(tr(f'{len(written)} ファイルを保存しました: {Path(written[0]).parent}',
                               f'Wrote {len(written)} files to {Path(written[0]).parent}'))
        window.statusBar().showMessage(self.status.text(), 10000)
        return written


# --- CSV / PO export -----------------------------------------------------------------------------------------

class ExchangeDialog(QDialog):
    def __init__(self, window, kind):
        super().__init__(window)
        tr = window.tr
        self.kind = kind
        self.setWindowTitle(tr('CSV を書き出す', 'Export CSV') if kind == 'csv' else tr('PO を書き出す', 'Export PO'))
        form = QFormLayout(self)
        self.language = language_combo(window, with_all=(kind == 'csv'))
        form.addRow(tr('言語', 'Language'), self.language)
        self.detailed = QCheckBox(tr('詳しい列を付ける（元ファイル・状態・以前の英文・メモ）', 'Add detail columns (source file, status, previous English, note)'))
        if kind == 'po':
            self.detailed.setEnabled(False)
            self.detailed.setToolTip(tr('PO には、メモ・以前の英文・要確認(fuzzy)を常に含めます。', 'PO always carries notes, the previous English and fuzzy flags.'))
        form.addRow(self.detailed)
        hint = QLabel(tr('書き出した CSV は表計算ソフトで編集し、「既存の翻訳を取り込む」で戻せます（status / review 列も読みます）。',
                         'Edit the CSV in a spreadsheet and bring it back with Import; the status and review columns are read.')
                      if kind == 'csv' else
                      tr('PO は Poedit などの翻訳ツールで編集できます。', 'PO files open in translation tools such as Poedit.'))
        hint.setWordWrap(True)
        form.addRow(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def choices(self):
        return self.kind, self.language.currentData(), self.detailed.isChecked() and self.kind == 'csv'


def write_exchange(project, path, kind, language, detailed):
    from .workflow import export_csv, export_po
    if kind == 'csv':
        export_csv(project, Path(path), language, detailed=detailed)
    else:
        export_po(project, Path(path), language)


def describe_bundle(path, tr) -> str:
    from .interchange import inspect_bundle
    info = inspect_bundle(path)
    languages = ', '.join(language_label(c) for c in info.languages)
    return tr(f'{info.name}\n元 MOD: {info.original_package_id}\n項目 {info.entries} 件 / 訳済み {info.translated} 件\n'
              f'言語: {languages}\n作成: {info.created}\n書き出し済み MOD: {"あり" if info.has_output else "なし"}',
              f'{info.name}\nSource MOD: {info.original_package_id}\n{info.entries} rows, {info.translated} translated\n'
              f'Languages: {languages}\nCreated: {info.created}\nGenerated MOD included: {"yes" if info.has_output else "no"}')


# --- Match another translation MOD ---------------------------------------------------------------------------

class MatchModDialog(QDialog):
    """See how another translation MOD lines up with this project before importing any of it."""
    def __init__(self, window):
        super().__init__(window)
        self.window_ = window
        tr = window.tr
        self.mod = None
        self.match = None
        self.counts = {}
        self.setObjectName('matchMod')
        self.setWindowTitle(tr('他の翻訳 MOD と照らし合わせる', 'Match another translation MOD'))
        self.resize(900, 640)
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.folder = QLineEdit()
        self.folder.setPlaceholderText(tr('翻訳 MOD のフォルダー（Languages フォルダーのあるもの）', 'Translation MOD folder (with a Languages folder)'))
        browse = QPushButton(tr('選ぶ…', 'Browse…'))
        browse.clicked.connect(self._browse)
        self.language = language_combo(window)
        read = QPushButton(tr('読み込む', 'Read'))
        read.clicked.connect(lambda: self.load(Path(self.folder.text().strip())))
        for widget in (self.folder, browse, self.language, read):
            top.addWidget(widget, 1 if widget is self.folder else 0)
        layout.addLayout(top)
        self.summary = QLabel(tr('フォルダーを選んで「読み込む」を押してください。何も変更しません。', 'Choose a folder and press Read. Nothing is changed.'))
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.license = QLabel()
        self.license.setWordWrap(True)
        self.license.setObjectName('licenseNote')
        layout.addWidget(self.license)
        self.tabs = QTabWidget()
        self.lists = {}
        for name, title, headers in (
                ('different', tr('訳が違う', 'Different'), (tr('項目', 'Row'), tr('自分の訳', 'Yours'), tr('相手の訳', 'Theirs'))),
                ('new', tr('自分は未訳', 'New for you'), (tr('項目', 'Row'), '', '')),
                ('missing', tr('相手が未訳', 'They lack'), (tr('項目', 'Row'), '', '')),
                ('unknown', tr('この MOD にないキー', 'Unknown keys'), (tr('キー', 'Key'), '', ''))):
            view = make_tree(headers, (300, 260))
            view.itemClicked.connect(lambda item, _c=0: self._jump(item))
            self.lists[name] = view
            self.tabs.addTab(view, title)
        layout.addWidget(self.tabs, 1)
        self.overwrite = QCheckBox(tr('訳が違う項目も取り込み候補にする（既存の訳を置き換える）', 'Also offer to replace differing translations'))
        layout.addWidget(self.overwrite)
        self.overwrite.toggled.connect(self._enable)
        buttons = QDialogButtonBox()
        self.import_button = buttons.addButton(tr('取り込みを確認…', 'Review import…'), QDialogButtonBox.ActionRole)
        self.import_button.setEnabled(False)
        buttons.addButton(QDialogButtonBox.Close)
        self.import_button.clicked.connect(self._import)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self):
        chosen = QFileDialog.getExistingDirectory(self, self.window_.tr('翻訳 MOD のフォルダーを選ぶ', 'Choose translation MOD folder'))
        if chosen:
            self.folder.setText(chosen)
            self.load(Path(chosen))

    def _key(self, entry_id):
        entry = self.window_.project.entry_index().get(entry_id)
        return entry.key if entry else entry_id

    def _jump(self, item):
        entry_id = item.data(0, ID_ROLE)
        if entry_id and entry_id in self.window_.project.entry_index():
            self.window_.navigate_entry(entry_id)
            self.raise_()

    def load(self, folder):
        from .interchange import match_translation_mod
        window, tr = self.window_, self.window_.tr
        window.edit_detail()
        self.import_button.setEnabled(False)
        try:
            match = match_translation_mod(window.project, folder, self.language.currentData())
        except (ValueError, OSError) as exc:
            # Forget the previous MOD, or toggling the overwrite box would re-enable Import for it.
            self.mod = self.match = None
            self.counts = {}
            for view in self.lists.values():
                view.clear()
            self.license.clear()
            self.summary.setText(window.error_text(exc))
            return None
        self.mod = Path(folder)
        self.match = match
        self.counts = {'new': len(match.new), 'same': len(match.same), 'different': len(match.different),
                       'unknown': len(match.unknown), 'missing': len(match.missing)}
        about = match.about
        name = about.get('name') or self.mod.name
        self.summary.setText(tr(
            f'{name}（作者: {about.get("author") or "不明"} / {about.get("packageId") or "-"}）\n'
            f'カバー率 {match.coverage:.0%}（{match.matched}/{match.total} 件）  ·  自分は未訳 {self.counts["new"]} / 同じ {self.counts["same"]} / '
            f'違う {self.counts["different"]} / 相手が未訳 {self.counts["missing"]} / 知らないキー {self.counts["unknown"]}',
            f'{name} (author: {about.get("author") or "unknown"} / {about.get("packageId") or "-"})\n'
            f'Coverage {match.coverage:.0%} ({match.matched}/{match.total})  ·  new {self.counts["new"]} / same {self.counts["same"]} / '
            f'different {self.counts["different"]} / they lack {self.counts["missing"]} / unknown keys {self.counts["unknown"]}'))
        self.license.setText(tr(match.license_note,
                                "Another person's translation follows its author's license. Check that reuse is allowed (license or permission) before importing. "
                                'Imported rows are marked for review.'))
        for view in self.lists.values():
            view.clear()
        for entry_id, ours, theirs in match.different:
            self.lists['different'].addTopLevelItem(_item((self._key(entry_id), ours, theirs), entry_id))
        for name_, ids in (('new', match.new), ('missing', match.missing)):
            for entry_id in ids:
                self.lists[name_].addTopLevelItem(_item((self._key(entry_id), '', ''), entry_id))
        for entry_id in match.unknown:
            self.lists['unknown'].addTopLevelItem(_item((entry_id, '', '')))
        self._enable()
        return match

    def _enable(self, *_):
        match = getattr(self, 'match', None)
        self.import_button.setEnabled(bool(match and (match.new or (match.different and self.overwrite.isChecked()))))

    def preview(self):
        from .interchange import preview_import_mod
        return preview_import_mod(self.window_.project, self.mod, self.language.currentData(), self.overwrite.isChecked())

    def _import(self):
        window, tr = self.window_, self.window_.tr
        try:
            preview = self.preview()
        except (ValueError, OSError) as exc:
            window.error(window.error_text(exc))
            return
        if window.confirm_preview(preview, tr('翻訳 MOD の取り込みプレビュー（取り込んだ行は要確認になります）',
                                              'Translation MOD import preview (imported rows are marked for review)')):
            window.apply_preview(preview)
            self.accept()


# --- Per-file assignment -------------------------------------------------------------------------------------

class AssignDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window_ = window
        tr = window.tr
        project = window.project
        self.setObjectName('assignFiles')
        self.setWindowTitle(tr('ファイルごとの担当者', 'Assign files to translators'))
        self.resize(760, 520)
        layout = QVBoxLayout(self)
        note = QLabel(tr('元ファイルごとに担当者名を決めます（分担の目印です。出力には影響しません）。',
                         'Name who works on each source file. This is a planning aid and does not affect the output.'))
        note.setWordWrap(True)
        layout.addWidget(note)
        files = {}
        for entry in project.entries:
            row = files.setdefault(entry.source_file, [0, 0])
            row[0] += 1
            row[1] += bool(entry.japanese.strip())
        self.table = QTableWidget(len(files), 4)
        self.table.setHorizontalHeaderLabels([tr('元ファイル', 'Source file'), tr('項目', 'Rows'), tr('訳済み', 'Translated'), tr('担当者', 'Translator')])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 340)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._original = {}
        for number, (name, (rows, done)) in enumerate(sorted(files.items())):
            for column, value in enumerate((name, rows, f'{done}/{rows}', project.assignments.get(name, ''))):
                item = QTableWidgetItem(str(value))
                if column != 3:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(number, column, item)
            self._original[name] = project.assignments.get(name, '')
        layout.addWidget(self.table, 1)
        self.summary = QLabel()
        layout.addWidget(self.summary)
        row = QHBoxLayout()
        assign = QPushButton(tr('選んだファイルを割り当てる…', 'Assign selected…'))
        clear = QPushButton(tr('選んだ割り当てを外す', 'Clear selected'))
        assign.clicked.connect(self._assign_selected)
        clear.clicked.connect(lambda: [self.set_translator(i, '') for i in self._selected_rows()])
        row.addWidget(assign)
        row.addWidget(clear)
        row.addStretch()
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.table.itemChanged.connect(lambda *_: self._summary())
        self._summary()

    def _selected_rows(self):
        return sorted({i.row() for i in self.table.selectedIndexes()})

    def translators(self):
        names = {self.table.item(r, 3).text().strip() for r in range(self.table.rowCount())}
        names.add(self.window_.settings.data['default_translator'])
        return sorted(n for n in names if n)

    def _assign_selected(self):
        rows = self._selected_rows()
        if not rows:
            return
        tr = self.window_.tr
        name, ok = QInputDialog.getItem(self, tr('担当者', 'Translator'), tr('担当者名', 'Translator name'), self.translators(), 0, True)
        if ok:
            for row in rows:
                self.set_translator(row, name)

    def set_translator(self, row, name):
        self.table.item(row, 3).setText(name.strip())

    def _summary(self):
        tr = self.window_.tr
        counts = {}
        for row in range(self.table.rowCount()):
            who = self.table.item(row, 3).text().strip() or tr('（未割り当て）', '(unassigned)')
            counts[who] = counts.get(who, 0) + 1
        self.summary.setText(' · '.join(f'{who}: {n}' for who, n in sorted(counts.items())))

    def commit(self) -> int:
        from .notes import assign_file
        changed = 0
        for row in range(self.table.rowCount()):
            name = self.table.item(row, 0).text()
            who = self.table.item(row, 3).text().strip()
            if who != self._original.get(name, ''):
                assign_file(self.window_.project, name, who)
                self._original[name] = who
                changed += 1
        if changed:
            self.window_.on_edit()
            self.window_.refresh_assignee_filter()
        return changed

    def _ok(self):
        self.commit()
        self.accept()


# --- Versions ------------------------------------------------------------------------------------------------

class VersionStatesDialog(QDialog):
    """Every declared version with its state and the reason, so a version left out of export is never a surprise."""
    def __init__(self, window, available='library'):
        super().__init__(window)
        tr = window.tr
        from .multiversion import library_versions, version_states
        self.setObjectName('versionStates')
        self.setWindowTitle(tr('版ごとの状態', 'Version states'))
        self.resize(900, 420)
        if available == 'library':
            from .game_library import library_directory
            try:
                available = library_versions(library_directory(override=window.settings.data['game_library']))
            except OSError:
                available = None
        window.edit_detail()
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([tr('版', 'Version'), tr('状態', 'State'), tr('正式出力', 'Formal export'),
                                              tr('訳済み', 'Translated'), tr('説明', 'Why')])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        labels = {'ready': tr('準備できた', 'Ready'), 'no_library_game': tr('ゲーム未登録', 'No library game'),
                  'unscanned': tr('未抽出', 'Not scanned'), 'unverified_load_rules': tr('ロード規則が未検証', 'Load rules unverified')}
        reasons = {
            'ready': tr('抽出済みで、ライブラリのゲームで型情報を確認しています。', 'Scanned and checked against the game in the library.'),
            'no_library_game': tr('この版のゲームがライブラリにありません。一般的な規則で抽出したため、型情報は未検証です。'
                                  'ライブラリに入れて再スキャンすると確認できます。',
                                  'No game for this version is in the library, so it was extracted with general rules and type information is unverified. '
                                  'Add the game to the library and rescan to check it.'),
            'unscanned': tr('まだ抽出していません。「宣言版を確認・追加」で抽出できます。', 'Not extracted yet. Use "Check and add declared versions".'),
            'unverified_load_rules': tr('RimWorld 1.0 のロード規則は未検証のため、正式出力には含めません（抽出と編集はできます）。'
                                        '1.0 のゲームがライブラリにない場合も、この版は書き出せません。',
                                        'RimWorld 1.0 load rules are unverified, so 1.0 is left out of formal export (you can still extract and edit it). '
                                        'Without a 1.0 game in the library it cannot be checked either.')}
        for state in version_states(window.project, available):
            row = self.table.rowCount()
            self.table.insertRow(row)
            cells = (state.version, labels.get(state.status, state.status), tr('出力できる', 'Yes') if state.exportable else tr('出力しない', 'No'),
                     f'{state.translated}/{state.entries}', reasons.get(state.status, state.message))
            for column, value in enumerate(cells):
                item = QTableWidgetItem(value)
                item.setToolTip(state.message)
                if column == 1:
                    item.setData(ID_ROLE, state.status)
                self.table.setItem(row, column, item)
        self.table.setWordWrap(True)
        self.table.setColumnWidth(0, 60)
        self.table.setColumnWidth(1, 190)
        self.table.setColumnWidth(2, 110)
        self.table.setColumnWidth(3, 90)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.resizeRowsToContents()
        layout.addWidget(self.table, 1)
        hint = QLabel(tr('ゲーム版ライブラリの場所は「設定」の「抽出」タブで確認できます。', 'The game library location is shown in Preferences, Extraction tab.'))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class CarryDialog(QDialog):
    """Copy translations from one version to another: preview first, apply after."""
    def __init__(self, window):
        super().__init__(window)
        self.window_ = window
        self.carry = None
        tr = window.tr
        self.setObjectName('carryVersions')
        self.setWindowTitle(tr('別の版へ訳を引き継ぐ', 'Carry translations to another version'))
        self.resize(900, 600)
        window.edit_detail()
        project = window.project
        layout = QVBoxLayout(self)
        form = QHBoxLayout()
        versions = scanned_versions(project)
        self.source = version_combo(project, versions[0])
        self.target = version_combo(project, versions[-1] if len(versions) > 1 else versions[0])
        self.language = language_combo(window)
        form.addWidget(QLabel(tr('引き継ぎ元', 'From')))
        form.addWidget(self.source)
        form.addWidget(QLabel(tr('引き継ぎ先', 'To')))
        form.addWidget(self.target)
        form.addWidget(self.language)
        form.addStretch()
        layout.addLayout(form)
        self.different = QCheckBox(tr('原文が違う項目も引き継ぐ（要確認になります）', 'Also carry rows whose English differs (marked for review)'))
        self.overwrite = QCheckBox(tr('引き継ぎ先の既存の訳を置き換える', 'Replace existing translations in the target'))
        layout.addWidget(self.different)
        layout.addWidget(self.overwrite)
        self.info = QLabel()
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.table = make_tree((tr('項目', 'Row'), tr('引き継ぎ先の今の訳', 'Target now'), tr('引き継ぐ訳', 'Carried'), tr('要確認', 'Review')), (260, 230, 230))
        layout.addWidget(self.table, 1)
        buttons = QDialogButtonBox()
        self.apply_button = buttons.addButton(tr('引き継ぐ', 'Apply'), QDialogButtonBox.AcceptRole)
        buttons.addButton(QDialogButtonBox.Close)
        self.apply_button.clicked.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for widget in (self.source, self.target, self.language):
            widget.currentIndexChanged.connect(self.refresh)
        for widget in (self.different, self.overwrite):
            widget.toggled.connect(self.refresh)
        self.refresh()

    def refresh(self, *_):
        from .multiversion import preview_carry
        tr = self.window_.tr
        self.table.clear()
        self.carry = None
        self.apply_button.setEnabled(False)
        source, target = self.source.currentData(), self.target.currentData()
        if source == target:
            self.info.setText(tr('違う版を選んでください。', 'Choose two different versions.'))
            return
        try:
            self.carry = preview_carry(self.window_.project, source, target, self.language.currentData(),
                                       self.overwrite.isChecked(), self.different.isChecked())
        except ValueError as exc:
            self.info.setText(self.window_.error_text(exc))
            return
        index = self.window_.project.entry_index()
        for item in self.carry.items:
            entry = index.get(item.entry_id)
            self.table.addTopLevelItem(_item((entry.key if entry else item.entry_id, item.before, item.after,
                                              tr('はい', 'yes') if item.review else ''), item.entry_id))
        skipped = self.carry.skipped
        names = {'missing': tr('相手の版にない', 'not in target'), 'english_differs': tr('原文が違う', 'English differs'),
                 'has_translation': tr('すでに訳がある', 'already translated'), 'blocked': tr('除外・要再確認', 'excluded or needs re-review'),
                 'unsafe': tr('記号が壊れる', 'would break placeholders')}
        self.info.setText(tr(f'{len(self.carry.items)} 件を引き継げます。', f'{len(self.carry.items)} rows can be carried.') + '  '
                          + tr('引き継がない項目: ', 'Left alone: ') + ', '.join(f'{names[k]} {v}' for k, v in skipped.items() if v))
        self.apply_button.setEnabled(bool(self.carry.items))

    def apply(self) -> int:
        from .multiversion import apply_carry
        window = self.window_
        if self.carry is None or not self.carry.items:
            return 0
        try:
            count = apply_carry(window.project, self.carry)
        except ValueError as exc:
            window.error(window.error_text(exc))
            self.refresh()
            return 0
        current = window.current.id if window.current else None
        window.populate()
        if current:
            window.navigate_entry(current)
        window.on_edit()
        window.statusBar().showMessage(window.tr(f'{count} 件を引き継ぎました。各項目を確認してください。', f'Carried {count} rows. Review them in the target version.'), 10000)
        return count

    def _apply(self):
        if self.apply():
            self.accept()


class VersionDiffDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window_ = window
        tr = window.tr
        self.setObjectName('versionDiff')
        self.setWindowTitle(tr('版どうしを比べる', 'Compare versions'))
        self.resize(940, 580)
        window.edit_detail()
        project = window.project
        versions = scanned_versions(project)
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.a = version_combo(project, versions[0])
        self.b = version_combo(project, versions[-1] if len(versions) > 1 else versions[0])
        self.language = language_combo(window)
        for widget in (QLabel(tr('版 A', 'Version A')), self.a, QLabel(tr('版 B', 'Version B')), self.b, self.language):
            top.addWidget(widget)
        top.addStretch()
        layout.addLayout(top)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.tabs = QTabWidget()
        self.lists = {}
        two = (tr('項目', 'Row'), 'A', 'B')
        for name, title, headers in (
                ('english_changed', tr('原文が違う', 'English differs'), (tr('項目', 'Row'), tr('原文 A', 'English A'), tr('原文 B', 'English B'), tr('訳 A', 'Translation A'), tr('訳 B', 'Translation B'))),
                ('translation_differs', tr('訳が違う', 'Translation differs'), (tr('項目', 'Row'), tr('訳 A', 'Translation A'), tr('訳 B', 'Translation B'), tr('原文', 'English'))),
                ('only_a', tr('A だけ', 'Only in A'), (tr('項目', 'Row'),)), ('only_b', tr('B だけ', 'Only in B'), (tr('項目', 'Row'),))):
            view = make_tree(headers, (230, 190, 190, 190))
            self.lists[name] = view
            self.tabs.addTab(view, title)
        layout.addWidget(self.tabs, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for widget in (self.a, self.b, self.language):
            widget.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def refresh(self, *_):
        from .multiversion import version_diff
        tr = self.window_.tr
        for view in self.lists.values():
            view.clear()
        a, b = self.a.currentData(), self.b.currentData()
        if a == b:
            self.summary.setText(tr('違う版を選んでください。', 'Choose two different versions.'))
            return
        try:
            diff = version_diff(self.window_.project, a, b, self.language.currentData())
        except ValueError as exc:
            self.summary.setText(self.window_.error_text(exc))
            return
        self.summary.setText(tr(
            f'{a} だけ {len(diff.only_a)} 件 / {b} だけ {len(diff.only_b)} 件 / 原文が違う {len(diff.english_changed)} 件 / 訳が違う {len(diff.translation_differs)} 件 / 同じ {diff.same} 件',
            f'Only in {a}: {len(diff.only_a)} / only in {b}: {len(diff.only_b)} / English differs: {len(diff.english_changed)} / '
            f'translation differs: {len(diff.translation_differs)} / same: {diff.same}'))
        for change in diff.english_changed:
            self.lists['english_changed'].addTopLevelItem(_item((row_key(change.entry_id), change.english_a, change.english_b, change.translation_a, change.translation_b), change.entry_id))
        for change in diff.translation_differs:
            self.lists['translation_differs'].addTopLevelItem(_item((row_key(change.entry_id), change.translation_a, change.translation_b, change.english_a), change.entry_id))
        for name, ids in (('only_a', diff.only_a), ('only_b', diff.only_b)):
            for entry_id in ids:
                self.lists[name].addTopLevelItem(_item((row_key(entry_id),), entry_id))
        for index, name in enumerate(self.lists):
            base = self.tabs.tabText(index).split(' (')[0]
            self.tabs.setTabText(index, f'{base} ({self.lists[name].topLevelItemCount()})')


# --- Inconsistent terms --------------------------------------------------------------------------------------

class InconsistentTermsView(QWidget):
    """English names the project translates in more than one way; clicking a wording visits its rows one by one."""
    jump = Signal(str)
    adopt = Signal(str, str)
    ROWS_ROLE = Qt.UserRole + 8

    def __init__(self, project, tr, language=None, parent=None):
        super().__init__(parent)
        from .glossary import inconsistent_terms
        self.setObjectName('inconsistentTerms')
        layout = QVBoxLayout(self)
        self.found = inconsistent_terms(project, language)
        self.hint = QLabel(tr('同じ英語に複数の訳があります。誤りのことも、文脈での使い分けのこともあります。訳をクリックすると、その訳を使う項目へ順に移動します。',
                              'The same English has several translations. That can be a mistake or a deliberate split by context. '
                              'Click a wording to visit the rows that use it, one after another.'))
        self.hint.setWordWrap(True)
        self.hint.setObjectName('muted')
        layout.addWidget(self.hint)
        self.tree = make_tree((tr('英語 / 訳', 'English / translation'), tr('件数', 'Rows')), (420,))
        self.tree.setRootIsDecorated(True)
        for item in self.found:
            top = _item((item.term, '', ''))
            top.setText(1, tr(f'{len(item.renderings)} 通り', f'{len(item.renderings)} wordings'))
            for rendering, ids in item.renderings.items():
                child = _item(('    ' + rendering, len(ids)))
                child.setData(0, self.ROWS_ROLE, (item.term, rendering, tuple(ids)))
                top.addChild(child)
            self.tree.addTopLevelItem(top)
            top.setExpanded(True)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.itemActivated.connect(self._clicked)
        self.tree.currentItemChanged.connect(lambda *_: self._sync())
        layout.addWidget(self.tree, 1)
        self.empty = QLabel(tr('訳のぶれはありません。', 'No terms with differing translations.'))
        self.empty.setVisible(not self.found)
        layout.addWidget(self.empty)
        self.adopt_button = QPushButton(tr('選んだ訳を用語集に登録', 'Register the selected wording in the glossary'))
        self.adopt_button.clicked.connect(self._adopt)
        layout.addWidget(self.adopt_button)
        self._next = {}
        self._sync()

    def _rows(self, item):
        return item.data(0, self.ROWS_ROLE) if item is not None else None

    def _sync(self):
        self.adopt_button.setEnabled(self._rows(self.tree.currentItem()) is not None)

    def _clicked(self, item, _column=0):
        data = self._rows(item)
        if data is None:
            return
        term, rendering, ids = data
        position = self._next.get((term, rendering), 0) % len(ids)
        self._next[(term, rendering)] = position + 1
        self.jump.emit(ids[position])

    def _adopt(self):
        data = self._rows(self.tree.currentItem())
        if data is not None:
            self.adopt.emit(data[0], data[1])


# --- Prerequisites -------------------------------------------------------------------------------------------

def effect_text(effect, tr):
    """One line on how many rows depend on a prerequisite, and a tooltip saying what could not be decided."""
    if effect is None:
        return '', ''
    types = tr('型 不明', 'types unknown') if effect.type_rows is None else tr(f'型 {effect.type_rows}', f'types {effect.type_rows}')
    text = tr(f'{effect.total} 行  (親Def {effect.parent_rows} / {types} / 条件付き {effect.conditional_rows})',
              f'{effect.total} rows  (parent {effect.parent_rows} / {types} / conditional {effect.conditional_rows})')
    notes = {'assemblies-unreadable': tr('この MOD の DLL を読めなかったため、C# 型に基づく行数は数えていません。',
                                         'The MOD\'s DLLs could not be read, so rows depending on its C# types are not counted.'),
             'conditional-def-level': tr('Def の内側にある MayRequire は、その Def の全行を数えています（上限値）。',
                                         'A MayRequire nested inside a Def counts every row of that Def (an upper bound).')}
    tip = tr('親Def: この MOD が定義する ParentName を継承する Def の行。型: この MOD の DLL が持つ C# 型のフィールドの行。'
             '条件付き: この MOD を MayRequire / IfModActive で名指す箇所の行。重なる行は1回だけ数えます。',
             'Parent: rows of Defs inheriting a ParentName this MOD defines. Types: rows of fields owned by a C# type in this MOD\'s DLLs. '
             'Conditional: rows under MayRequire / IfModActive naming this MOD. A row in several groups is counted once.')
    return text, '\n'.join([tip, *(notes[n] for n in effect.notes if n in notes)])


class PrerequisitesDialog(QDialog):
    """Missing prerequisite MODs as a subscribe-to list, plus the ones that were found."""
    def __init__(self, window, report, effects=None):
        super().__init__(window)
        from .scan_context import workshop_link
        self.window_ = window
        tr = window.tr
        self.setObjectName('prerequisites')
        self.setWindowTitle(tr('前提 MOD', 'Prerequisite MODs'))
        self.resize(860, 560)
        layout = QVBoxLayout(self)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        if report.missing:
            extra = (tr(f' 前提 MOD が足りないため、{report.unverified_fields} 件の項目は型情報で確認できませんでした（MOD ごとの内訳は分かりません）。',
                        f' Because of the missing MODs, {report.unverified_fields} fields could not be checked against C# types (the count cannot be split per MOD).')
                     if report.unverified_fields else '')
            self.note.setText(tr(f'足りない前提 MOD が {len(report.missing)} 件あります。購読（導入）してから「元 MOD を再スキャン」すると、抽出の精度が上がります。',
                                 f'{len(report.missing)} prerequisite MODs are missing. Subscribe to (install) them and rescan for a more reliable extraction.') + extra)
        else:
            self.note.setText(tr('足りない前提 MOD はありません。', 'No prerequisite MODs are missing.'))
        layout.addWidget(QLabel(tr('足りない MOD', 'Missing')))
        self.missing = make_tree((tr('名前', 'Name'), 'packageId', tr('Workshop のリンク', 'Workshop link')), (240, 240))
        for item in report.missing:
            self.missing.addTopLevelItem(_item((item.name, item.package_id, workshop_link(item) or tr('（id 不明: 名前で Workshop を検索）', '(id unknown: search the Workshop by name)'))))
        layout.addWidget(self.missing, 1)
        layout.addWidget(QLabel(tr('見つかった MOD（参考）', 'Found (for reference)')))
        effects = effects or {}
        self.found = make_tree((tr('名前', 'Name'), 'packageId', tr('場所・同梱の言語', 'Location / shipped languages'),
                                tr('この MOD に依存する行', 'Rows depending on it')), (240, 240, 360))
        for item in sorted(report.found, key=lambda i: (i.official, i.name.casefold())):
            detail = str(item.folder or '')
            if item.translations:
                detail += '   [' + ', '.join(item.translations) + ']'
            if item.unsupported:
                detail += tr('   ※この版に未対応と宣言', '   (does not declare this game version)')
            text, tip = effect_text(effects.get(item.package_id), tr)
            self.found.addTopLevelItem(_item((item.name, item.package_id, detail, text), tooltip=tip))
        layout.addWidget(self.found, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        copy = buttons.addButton(tr('足りない MOD をコピー', 'Copy missing list'), QDialogButtonBox.ActionRole)
        openpage = buttons.addButton(tr('選んだ MOD の Workshop を開く', 'Open selected in browser'), QDialogButtonBox.ActionRole)
        copy.clicked.connect(lambda: self._copy(report, workshop_link))
        openpage.clicked.connect(lambda: self._open(report, workshop_link))
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _copy(self, report, link):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText('\n'.join(f'{m.name}  {m.package_id}  {link(m)}'.rstrip() for m in report.missing))

    def _open(self, report, link):
        row = self.missing.currentItem()
        if row is None:
            return
        match = next((m for m in report.missing if m.package_id == row.text(1)), None)
        if match and link(match):
            QDesktopServices.openUrl(QUrl(link(match)))
