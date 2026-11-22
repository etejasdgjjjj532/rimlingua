"""Editor actions around import, diagnostics, history, preferences and game tests."""
from __future__ import annotations
from dataclasses import asdict
import json
from pathlib import Path
import threading
import xml.etree.ElementTree as ET
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QAction, QKeySequence, QFont, QShortcut
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSpinBox, QTableView, QTabWidget, QToolButton, QVBoxLayout, QWidget)
from .gui_share import ShareMixin
from .i18n import install_qt_translator, text, translate_static_ui
from .platforms import discover_installations
from .workflow import (apply_changes, export_csv, export_po, preview_import,
                       preview_replace, translation_memory, set_glossary_term,
                       remove_glossary_term)


class ChangePreviewModel(QAbstractTableModel):
    def __init__(self, changes, language):
        super().__init__()
        self.changes, self.language = changes, language
    def rowCount(self,parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.changes)
    def columnCount(self,parent=QModelIndex()):
        return 0 if parent.isValid() else 3
    def data(self,index,role=Qt.DisplayRole):
        if index.isValid() and role in (Qt.DisplayRole,Qt.ToolTipRole):
            c = self.changes[index.row()]
            return [f'{c.language} / {c.id}',c.before,c.after][index.column()]
    def headerData(self,section,orientation,role=Qt.DisplayRole):
        if orientation==Qt.Horizontal and role==Qt.DisplayRole:
            return [text('キー',self.language),text('変更前',self.language,'Before'),text('変更後',self.language,'After')][section]


class GameTestWorker(QObject):
    finished = Signal(object,str)
    stage = Signal(str)
    def __init__(self, installation, mod, destination, sources, packages, language):
        super().__init__()
        self.args = installation,mod,destination,sources,packages,language
        self.cancel = threading.Event()
    def run(self):
        try:
            from .game_testing import prepare_game_test, launch_game_test
            installation,mod,destination,sources,packages,language = self.args
            self.stage.emit('Preparing a disposable game copy…')
            plan = prepare_game_test(installation,mod,destination,source_mods=sources,active_packages=packages,language=language)
            self.stage.emit('RimWorld is running with isolated configuration and logs…')
            result = launch_game_test(plan,timeout=120,cancel=self.cancel)
            self.finished.emit(result,'')
        except Exception as exc:
            self.finished.emit(None,str(exc))


class ToolsMixin(ShareMixin):
    def tr(self,japanese,english=None):
        return text(japanese,self.ui_language,english)

    def discovered_games(self):
        return discover_installations(custom_paths=self.settings.data['game_paths'])

    def output_folder(self, trial=False):
        """The checked folder the translation MOD goes to; every export, install and test uses this."""
        from .output_paths import resolve_output
        return resolve_output(self.project_path, self.project, self.settings.data, self.discovered_games(), trial=trial)

    def error_text(self, exc):
        from .output_paths import OutputLocationError
        return exc.text(self.ui_language) if isinstance(exc, OutputLocationError) else str(exc)

    def setup_tools(self):
        self.undo_batches, self.redo_batches = [],[]
        self.last_export_error = ''
        self.scan_progress = QProgressBar(self)
        self.scan_progress.setMaximumWidth(220)
        self.cancel_scan_button = QPushButton(self.tr('スキャンを中止','Cancel scan'))
        self.cancel_scan_button.clicked.connect(self.cancel_scan)
        self.statusBar().addPermanentWidget(self.scan_progress)
        self.statusBar().addPermanentWidget(self.cancel_scan_button)
        self.scan_progress.hide()
        self.cancel_scan_button.hide()
        self.source_filter = QLineEdit()
        self.source_filter.setPlaceholderText(self.tr('元ファイルで絞り込み','Filter by source file'))
        self.source_filter.setAccessibleName(self.tr('元ファイルを絞り込む','Filter source files'))
        self.source_filter.textChanged.connect(self.filter_changed)
        self.search_row.insertWidget(2,self.source_filter)
        for label,code in [('確認済み','reviewed'),('承認済み','approved'),('新しい項目','new'),('除外した項目','excluded')]:
            self.status_filter.addItem(self.tr(label,{'reviewed':'Reviewed','approved':'Approved','new':'New','excluded':'Excluded'}[code]),code)
        self.export_button.clicked.disconnect()
        self.export_button.clicked.connect(self.export_with_review)
        self.git_side.clicked.disconnect()
        self.git_side.clicked.connect(self.show_history)
        self.git_side.setText(self.tr('履歴と復元','History and restore'))
        self.guide_skip = QPushButton(self.tr('ガイドをスキップ','Skip guide'),self.welcome_page)
        self.guide_skip.clicked.connect(self.skip_tutorial)
        self.welcome_page.layout().addWidget(self.guide_skip)
        self.quick_welcome = QWidget()
        col = QVBoxLayout(self.quick_welcome)
        col.addStretch()
        note = QLabel(self.tr('新しく翻訳する MOD を選ぶか、最近のプロジェクトを開いてください。','Choose a source MOD or open a recent translation project.'))
        note.setWordWrap(True)
        col.addWidget(note)
        new = QPushButton(self.tr('新しい翻訳を始める','Start a translation'))
        new.clicked.connect(self.new_project)
        opened = QPushButton(self.tr('保存した翻訳を開く','Open saved translation'))
        opened.clicked.connect(self.open_project)
        col.addWidget(new)
        col.addWidget(opened)
        col.addStretch()
        self.views.addWidget(self.quick_welcome)
        if self.settings.data['tutorial_dismissed']:
            self.views.setCurrentWidget(self.quick_welcome)
        for action in self.findChildren(QAction):
            action.setShortcut(QKeySequence())
        self.rebuild_menus()
        translate_static_ui(self)
        self.set_editor_font(self.settings.data['font_size'],persist=False)
        self.statusBar().showMessage(self.tr('準備完了  ·  新規プロジェクトから始めてください','Ready · Choose or open a translation project'))
        QWidget.setTabOrder(self.search,self.status_filter)
        QWidget.setTabOrder(self.status_filter,self.source_filter)
        QWidget.setTabOrder(self.source_filter,self.table)
        QWidget.setTabOrder(self.table,self.japanese)
        QWidget.setTabOrder(self.japanese,self.reviewed)
        if self.settings.load_error:
            self.statusBar().showMessage(self.tr('設定を読み直せませんでした。標準設定で起動しました。','Settings could not be read; using defaults.'),10000)

    def rebuild_menus(self):
        for old in self.menuBar().actions():
            if old.menu() is not None:
                old.menu().deleteLater()
        self.menuBar().clear()
        self.project_tool_actions = []
        def menu(jp,en,items):
            m = self.menuBar().addMenu(self.tr(jp,en))
            for jp,en,callback,shortcut,needs_project in items:
                a = QAction(self.tr(jp,en),m)
                if shortcut:
                    a.setShortcut(QKeySequence(shortcut))
                a.triggered.connect(callback)
                m.addAction(a)
                if needs_project:
                    self.project_tool_actions.append(a)
                    a.setEnabled(bool(self.project) and not self.busy)
            return m
        file_menu = menu('ファイル','File',[
            ('新しい翻訳','New translation',self.new_project,'Ctrl+N',False),
            ('プロジェクトを開く','Open project',self.open_project,'Ctrl+O',False),
            ('保存して書き出す','Save and export',self.save,'Ctrl+S',True),
            ('翻訳 MOD を書き出す','Export translation mod',self.export_with_review,'Ctrl+E',True),
            ('既存の翻訳を取り込む','Import translations',self.import_translations,'Ctrl+I',True),
            ('他の翻訳 MOD と照らし合わせる…','Match another translation MOD…',self.match_mod_dialog,'',True),
            ('CSV を書き出す','Export CSV',lambda:self.exchange_export('csv'),'',True),
            ('PO を書き出す','Export PO',lambda:self.exchange_export('po'),'',True),
            ('Workshop 用の文章を作る…','Workshop material…',self.workshop_material_dialog,'',True),
            ('プロジェクトバンドルを書き出す…','Export project bundle…',self.export_bundle_dialog,'',True),
            ('プロジェクトバンドルを開く…','Import project bundle…',self.import_bundle_dialog,'',False)])
        recent = file_menu.addMenu(self.tr('最近のプロジェクト','Recent projects'))
        for value in self.settings.data['recent_projects']:
            path = Path(value)
            action = recent.addAction(path.parent.name)
            action.setToolTip(str(path))
            action.setEnabled(path.is_file())
            action.triggered.connect(lambda _checked=False,p=path:self.open_recent(p))
        menu('編集','Edit',[
            ('一括変更を元に戻す','Undo batch',self.undo_batch,'Ctrl+Alt+Z',True),
            ('一括変更をやり直す','Redo batch',self.redo_batch,'Ctrl+Alt+Y',True),
            ('一括置換','Batch replace',self.batch_replace,'Ctrl+H',True),
            ('表示条件を更新','Refresh filters',self.filter_changed,'Ctrl+F5',True),
            ('用語集','Glossary',self.glossary_dialog,'',True),
            ('同じ原文の翻訳候補','Translation memory',self.memory_dialog,'Ctrl+M',True),
            ('確認済みにする','Mark reviewed',self.mark_reviewed,'Ctrl+Return',True),
            ('承認済みにする','Mark approved',self.approve_current,'',True),
            ('この項目の除外を切り替える','Toggle entry exclusion',self.exclude_current,'',True),
            ('抽出の分類を変更','Classify candidate',self.classify_current,'',True)])
        project_menu = menu('プロジェクト','Project',[
            ('品質チェック…','Quality check…',self.quality_check_dialog,'Ctrl+Shift+K',True),
            ('元 MOD を再スキャン','Rescan source MOD',self.rescan,'Ctrl+R',True),
            ('前提 MOD…','Prerequisite MODs…',self.prerequisites_dialog,'',True),
            ('ファイルごとの担当者…','Assign files to translators…',self.assign_files_dialog,'',True),
            ('版ごとの状態…','Version states…',self.version_states_dialog,'',True),
            ('別の版へ訳を引き継ぐ…','Carry translations to another version…',self.carry_versions_dialog,'',True),
            ('版どうしを比べる…','Compare versions…',self.version_diff_dialog,'',True),
            ('ゲーム版・有効 MOD の抽出設定','Game version and active MODs',self.extraction_context_dialog,'',True),
            ('抽出と翻訳の診断','Extraction and QA',self.show_warnings,'',True),
            ('履歴と復元','History and restore',self.show_history,'',True),
            ('配布用 MOD 情報','Translation MOD metadata',self.metadata_dialog,'',True),
            ('出力先フォルダーを設定','Set output folder',self.output_folder_dialog,'',True)])
        project_menu.addAction(self.reopen_trial_report_action)
        menu('ゲーム','Game',[
            ('翻訳 MOD を導入・更新','Install or update translation MOD',self.install_dialog,'',True),
            ('導入済み翻訳を復元','Restore installed translation',self.restore_install_dialog,'',True),
            ('必要 MOD と読み込み順','Dependencies and load order',self.dependencies_dialog,'',True),
            ('隔離コピーでゲームをテスト','Test a disposable game copy',self.launch_test_dialog,'',True)])
        view_menu = self.menuBar().addMenu(self.tr('表示','View'))
        from PySide6.QtGui import QActionGroup
        group = QActionGroup(self)
        group.setExclusive(True)
        self.theme_actions = {}
        for value,jp,en in (('system','システムに合わせる','Follow system'),('light','ライト','Light'),('dark','ダーク','Dark')):
            action = QAction(self.tr(jp,en),self)
            action.setCheckable(True)
            action.setChecked(self.settings.data['theme_mode']==value)
            action.triggered.connect(lambda _checked=False,v=value:self.set_theme_mode(v))
            group.addAction(action)
            view_menu.addAction(action)
            self.theme_actions[action] = value
        view_menu.addSeparator()
        self.tree_action = QAction(self.tr('分類ツリーを表示','Show classification tree'),self)
        self.tree_action.setCheckable(True)
        self.tree_action.setChecked(self.settings.data['show_tree'])
        self.tree_action.setShortcut(QKeySequence('Ctrl+T'))
        self.tree_action.triggered.connect(lambda checked=False:self.set_tree_visible(self.tree_action.isChecked()))
        view_menu.addAction(self.tree_action)
        self.reduce_motion_action = QAction(self.tr('動きを減らす','Reduce motion'),self)
        self.reduce_motion_action.setCheckable(True)
        self.reduce_motion_action.setChecked(self.settings.data['reduce_motion'])
        self.reduce_motion_action.triggered.connect(lambda checked=False:self.set_reduce_motion(self.reduce_motion_action.isChecked()))
        view_menu.addAction(self.reduce_motion_action)
        toggle =QAction(self.tr('ライト/ダークを切り替え','Toggle light/dark'),self)
        toggle.setShortcut(QKeySequence('Ctrl+Shift+D'))
        toggle.triggered.connect(self.toggle_theme)
        view_menu.addAction(toggle)
        menu('ヘルプ','Help',[
            ('設定・文字サイズ・ゲームの場所','Preferences and game paths',self.preferences_dialog,'',False),
            ('キーボードショートカット一覧','Keyboard shortcuts',self.shortcut_help,'',False),
            ('ガイドを表示','Show getting-started guide',self.show_tutorial,'',False),
            ('アップデートを確認','Check for updates',self.check_updates_dialog,'',False),
            ('問題報告用の情報をコピー','Copy diagnostic information',self.copy_diagnostic_info,'',False)])

    def save_preferences(self):
        try:
            self.settings.save()
        except OSError as exc:
            self.statusBar().showMessage(self.tr('設定の保存先を確認してください: ','Check the settings location: ')+str(exc),10000)

    def set_gui_language(self,language):
        from .settings import UI_LANGUAGES, resolve_ui_language
        if language not in UI_LANGUAGES:
            raise ValueError('Unsupported GUI language')
        # The stored choice may be 'system'; the editor itself always runs in 'ja' or 'en'.
        shown = resolve_ui_language(language)
        self.ui_language = shown
        self.settings.data['ui_language'] = language
        from PySide6.QtWidgets import QApplication
        install_qt_translator(QApplication.instance(),shown)
        translate_static_ui(self)
        self.rebuild_menus()
        self.save_preferences()
        self.reset_flag_combos()
        if self.project:
            self.populate()
        self._aid_signature, self._force_suggestions = None, True
        if self.project:
            self.sync_panel()
        self.refresh_aids()
        translate_static_ui(self)

    def apply_theme(self):
        """Apply the stored light/dark/system preference, the font size and the matching application palette."""
        from PySide6.QtWidgets import QApplication
        from .theme import PALETTES, application_palette, resolve_mode, stylesheet, system_prefers_dark
        mode = resolve_mode(self.settings.data['theme_mode'],system_prefers_dark())
        self.theme_mode_resolved = mode
        app = QApplication.instance()
        if app is not None:
            if not getattr(app,'_rw_fusion',False):
                app.setStyle('Fusion')
                app._rw_fusion = True
                from PySide6.QtGui import QGuiApplication
                QGuiApplication.styleHints().colorSchemeChanged.connect(lambda *_:self.apply_theme())
            app.setPalette(application_palette(mode))
        self.setStyleSheet(stylesheet(mode,int(self.settings.data['font_size'])))
        tokens = PALETTES['dark' if mode=='dark' else 'light']
        if getattr(self,'model',None) is not None:
            self.model.status_colors = {'untranslated':tokens['muted'],'translated':tokens['ok'],'needs-review':tokens['warn'],
                                        'changed':tokens['info'],'stale':tokens['disabled'],'internal':tokens['disabled'],
                                        'excluded':tokens['disabled']}
            if self.model.rowCount():
                self.model.dataChanged.emit(self.model.index(0,0),self.model.index(self.model.rowCount()-1,0))
        if hasattr(self,'update_empty_state'):
            self.update_empty_state()

    def set_theme_mode(self,mode,persist=True):
        if mode not in {'system','light','dark'}:
            raise ValueError('Unsupported theme')
        self.settings.data['theme_mode'] = mode
        self.apply_theme()
        for action,value in getattr(self,'theme_actions',{}).items():
            action.setChecked(value==mode)
        if persist:
            self.save_preferences()

    def toggle_theme(self):
        self.set_theme_mode('light' if getattr(self,'theme_mode_resolved','dark')=='dark' else 'dark')

    def set_editor_font(self,size,persist=True):
        if not 8<=int(size)<=24:
            raise ValueError('Choose a font size between 8 and 24')
        self.settings.data['font_size'] = int(size)
        font = QFont(self.font())
        font.setPointSize(int(size))
        self.setFont(font)
        self.apply_theme()
        for editor in (self.english,self.japanese,self.table):
            editor.setFont(font)
        if persist:
            self.save_preferences()

    def skip_tutorial(self):
        self.settings.data['tutorial_dismissed'] = True
        self.save_preferences()
        if not self.project:
            self.views.setCurrentWidget(self.quick_welcome)

    def show_tutorial(self):
        self.settings.data['tutorial_dismissed'] = False
        self.save_preferences()
        if self.project:
            self.info_dialog(self.tr('翻訳の流れ','Translation workflow'),self.tr('1. 元 MOD と言語を選ぶ\n2. 訳を入力して保存（自動書き出し）\n3. 診断を確認しゲームに導入\n元 MOD が更新されたら再スキャン。取り込み・用語集・履歴はメニューから使えます。','1. Choose source MOD and languages\n2. Translate and save (also exports)\n3. Review diagnostics and install\nRescan after source updates. Imports, glossary and history are available from the menus.'))
        else:
            self.views.setCurrentWidget(self.welcome_page)

    def open_recent(self,path):
        if self.confirm_switch():
            self.load_project(path)

    def info_dialog(self,title,value):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(820,480)
        col = QVBoxLayout(dialog)
        display = QPlainTextEdit()
        display.setReadOnly(True)
        display.setPlainText(value)
        col.addWidget(display)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        col.addWidget(buttons)
        dialog.exec()

    def confirm_preview(self,preview,title):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(880,540)
        col = QVBoxLayout(dialog)
        col.addWidget(QLabel(self.tr(f'変更 {len(preview.changes)} 件 / 競合 {len(preview.conflicts)} 件 / 不明キー {len(preview.unknown)} 件',f'{len(preview.changes)} changes / {len(preview.conflicts)} conflicts / {len(preview.unknown)} unknown keys')))
        table = QTableView()
        model = ChangePreviewModel(preview.changes,self.ui_language)
        table.setModel(model)
        table.horizontalHeader().setStretchLastSection(True)
        table.setColumnWidth(0,280)
        table.setColumnWidth(1,220)
        col.addWidget(table,1)
        issues = [*preview.conflicts,*preview.unknown,*preview.warnings]
        if issues:
            details = QPlainTextEdit('\n'.join(issues[:200]))
            details.setReadOnly(True)
            details.setMaximumHeight(130)
            col.addWidget(details)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(self.tr('変更を適用','Apply changes'))
        buttons.button(QDialogButtonBox.Ok).setEnabled(bool(preview.changes))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        col.addWidget(buttons)
        return dialog.exec()==QDialog.Accepted

    def apply_preview(self,preview):
        if not self.project or self.busy or not preview.changes:
            return False
        batch = apply_changes(self.project,preview.changes)
        self.undo_batches.append(batch)
        self.redo_batches.clear()
        current = self.current.id if self.current else None
        self.populate()
        if current:
            self.navigate_entry(current)
        self.on_edit()
        return True

    def undo_batch(self):
        if self.project and not self.busy and self.undo_batches:
            batch = self.undo_batches[-1]
            try:
                batch.undo(self.project)
                self.undo_batches.pop()
                self.redo_batches.append(batch)
                self.populate()
                self.on_edit()
            except ValueError as exc:
                self.error(exc)

    def redo_batch(self):
        if self.project and not self.busy and self.redo_batches:
            batch = self.redo_batches[-1]
            try:
                batch.redo(self.project)
                self.redo_batches.pop()
                self.undo_batches.append(batch)
                self.populate()
                self.on_edit()
            except ValueError as exc:
                self.error(exc)

    def import_translations(self):
        if not self.project or self.busy:
            return
        options = [self.tr('XML / CSV / PO / 差分ファイル','XML / CSV / PO / diff file'),self.tr('翻訳 MOD・言語フォルダー','Translation MOD or language folder')]
        choice,ok = QInputDialog.getItem(self,self.tr('取り込み','Import'),self.tr('取り込み元','Import source'),options,0,False)
        if not ok:
            return
        if choice==options[0]:
            value,_ = QFileDialog.getOpenFileName(self,self.tr('翻訳を取り込む','Import translations'),'','Translations (*.xml *.csv *.po *.diff *.patch)')
        else:
            value = QFileDialog.getExistingDirectory(self,self.tr('翻訳フォルダーを選ぶ','Choose translation folder'))
        if not value:
            return
        base_folder = None
        if Path(value).suffix.casefold() in {'.diff','.patch'}:
            base = QFileDialog.getExistingDirectory(self,self.tr('差分の基準 XML フォルダー（読み取り専用）','Base XML folder for the diff (read only)'))
            if not base:
                return
            base_folder = Path(base)
        try:
            preview = preview_import(self.project,Path(value),base_folder=base_folder)
            if preview.conflicts and QMessageBox.question(self,self.tr('既存の訳を保持','Preserve existing work'),self.tr('異なる既存の訳は保持します。プレビューで既存の訳の上書きも検討しますか？','Different existing translations are preserved. Include overwrite candidates in the preview?'),QMessageBox.Yes|QMessageBox.No,QMessageBox.No)==QMessageBox.Yes:
                preview = preview_import(self.project,Path(value),overwrite=True,base_folder=base_folder)
            if self.confirm_preview(preview,self.tr('取り込みプレビュー','Import preview')):
                self.apply_preview(preview)
        except Exception as exc:
            self.error(exc)

    def batch_replace(self):
        if not self.project or self.busy:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr('一括置換','Batch replace'))
        form = QFormLayout(dialog)
        find,replace = QLineEdit(),QLineEdit()
        regex = QCheckBox(self.tr('正規表現','Regular expression'))
        visible = QCheckBox(self.tr('表示中の項目だけ','Only visible entries'))
        visible.setChecked(True)
        form.addRow(self.tr('検索する訳文','Find in translation'),find)
        form.addRow(self.tr('置換後','Replace with'),replace)
        form.addRow(regex)
        form.addRow(visible)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec()==QDialog.Accepted:
            try:
                ids = [self.model.entries[self.proxy.mapToSource(self.proxy.index(i,0)).row()].id for i in range(self.proxy.rowCount())] if visible.isChecked() else None
                preview = preview_replace(self.project,find.text(),replace.text(),ids,regex.isChecked())
                if self.confirm_preview(preview,self.tr('置換プレビュー','Replacement preview')):
                    self.apply_preview(preview)
            except Exception as exc:
                self.error(exc)

    def glossary_dialog(self):
        if not self.project or self.busy:
            return
        existing = getattr(self,'glossary_window',None)
        if existing is not None:
            existing.close()
            existing.deleteLater()
        dialog = self.glossary_window = QDialog(self)
        dialog.setWindowTitle(self.tr('用語集','Glossary'))
        dialog.resize(640,560)
        outer = QVBoxLayout(dialog)
        tabs = QTabWidget()
        outer.addWidget(tabs,1)
        page = QWidget()
        col = QVBoxLayout(page)
        col.addWidget(QLabel(self.tr('プロジェクト共通の用語集です。QA は現在の翻訳先で照合します。','This glossary is shared by the project. QA checks it for the current target language.')))
        listing = QListWidget()
        col.addWidget(listing)
        row = QHBoxLayout()
        original,translated = QLineEdit(),QLineEdit()
        original.setPlaceholderText('English')
        translated.setPlaceholderText(self.tr('訳語','Translation'))
        row.addWidget(original)
        row.addWidget(translated)
        col.addLayout(row)
        actions = QHBoxLayout()
        add,remove = QPushButton(self.tr('追加・更新','Add / update')),QPushButton(self.tr('選択語を削除','Remove selected term'))
        actions.addWidget(add)
        actions.addWidget(remove)
        col.addLayout(actions)
        def refresh():
            listing.clear()
            for key,value in sorted(self.project.glossary.items()):
                item = QListWidgetItem(key+'  →  '+value,listing)
                item.setData(Qt.UserRole,key)
        def update():
            try:
                set_glossary_term(self.project,original.text(),translated.text())
                refresh()
                self.on_edit()
            except ValueError as exc:
                self.error(exc)
        def delete():
            if listing.currentItem():
                remove_glossary_term(self.project,listing.currentItem().data(Qt.UserRole))
                refresh()
                self.on_edit()
        add.clicked.connect(update)
        remove.clicked.connect(delete)
        refresh()
        from .dialogs_tools import InconsistentTermsView
        dialog.inconsistent = view = InconsistentTermsView(self.project,self.tr)
        tabs.addTab(page,self.tr('用語集','Glossary'))
        tabs.addTab(view,self.tr(f'訳のぶれ ({len(view.found)})',f'Inconsistent terms ({len(view.found)})'))
        view.jump.connect(self.navigate_entry)
        def adopt(term,translation):
            try:
                set_glossary_term(self.project,term,translation)
            except ValueError as exc:
                self.error(exc)
                return
            refresh()
            self.on_edit()
            self.statusBar().showMessage(self.tr(f'用語集に登録しました: {term} → {translation}',f'Added to the glossary: {term} → {translation}'),6000)
        view.adopt.connect(adopt)
        if view.found:
            tabs.setCurrentWidget(view)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(dialog.close)
        outer.addWidget(close)
        dialog.show()  # not modal: the table beside it follows the jumps

    def memory_dialog(self):
        if not self.current or self.busy:
            return
        suggestions = translation_memory(self.project,self.current.id)
        if not suggestions:
            self.info_dialog(self.tr('翻訳メモリ','Translation memory'),self.tr('同じ原文に対する訳はまだありません。','There are no translations of this exact source text yet.'))
            return
        text_value,ok = QInputDialog.getItem(self,self.tr('翻訳候補','Translation suggestions'),self.tr('同じ原文の既存訳から選ぶ','Choose a translation of the same source'),[s.translation for s in suggestions],0,False)
        if ok:
            self.japanese.setPlainText(text_value)

    def navigate_entry(self,identity):
        self.search.clear()
        self.source_filter.clear()
        self.status_filter.setCurrentIndex(0)
        self.filter_changed()
        entry = self.project.entry_index().get(identity) if self.project else None
        if entry:
            row = self.model.row_for_id.get(identity)
            if row is not None:
                index = self.proxy.mapFromSource(self.model.index(row,0))
                self.table.setCurrentIndex(index)
                self.table.scrollTo(index)
                self.japanese.setFocus()

    def exclude_current(self):
        if self.current and not self.busy:
            self.current.excluded = not self.current.excluded
            self.model.dataChanged.emit(self.model.index(self.model.row_for_id[self.current.id],0),self.model.index(self.model.row_for_id[self.current.id],3))
            self.sync_detail()
            self.on_edit()
            self.filter_changed()

    def classify_current(self):
        if not self.current or self.busy:
            return
        options = [self.tr('翻訳項目（実ゲームで確認済み）','Translation candidate verified in game'),self.tr('手動確認が必要','Needs manual review'),self.tr('抽出ミスとして除外','Exclude false positive')]
        value,ok = QInputDialog.getItem(self,self.tr('抽出の分類','Candidate classification'),self.current.key,options,0,False)
        if ok:
            index = options.index(value)
            self.current.classification = ['verified','manual-review','false-positive'][index]
            self.current.excluded = index==2
            self.current.review = index==1
            self.current.evidence[:] = [line for line in self.current.evidence if not line.startswith('User classification: ')]
            self.current.evidence.append('User classification: '+self.current.classification)
            self.sync_detail()
            self.on_edit()
            self.filter_changed()

    def approve_current(self):
        self.mark_reviewed(approved=True)

    def choose_scan_context(self,source):
        from .scan_context import default_context,validate_context
        from .installation import available_mod_paths,read_mod_metadata
        from .platforms import user_data_directory
        games = discover_installations(custom_paths=self.settings.data['game_paths'])
        game = games[0] if games else None
        try:
            if self.project and Path(self.project.source).resolve()==Path(source).resolve():
                initial = {'game_version':self.project.game_version,
                           'active_mods':self.project.active_mods if self.project.active_mods_known or self.project.active_mods else None}
            else:
                initial = default_context(source,game,self.mods_config_file())
            candidates = {}
            from .platforms import mod_folders
            for path in [*(available_mod_paths(game) if game else []),*mod_folders(self.user_mod_roots().all()),Path(source)]:
                try:
                    metadata = read_mod_metadata(path)
                    candidates[metadata.package_id] = metadata.name
                except (ValueError,OSError,ET.ParseError):
                    continue
            for package in initial['active_mods'] or []:
                candidates.setdefault(package,package)
        except Exception as exc:
            self.error(exc)
            return None
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr('ゲーム版・有効 MOD の抽出設定','Game version and active MODs'))
        dialog.resize(680,560)
        col = QVBoxLayout(dialog)
        note = QLabel(self.tr('抽出に使う条件を選びます。ゲームの設定は変更しません。\n確定すると再スキャンし、既存の訳をキーで引き継ぎます。',
                             'Choose extraction conditions. The game settings remain unchanged.\nApplying rescans the source and retains existing translations by key.'))
        note.setWordWrap(True)
        col.addWidget(note)
        if initial.get('warning'):
            warning = QLabel(initial['warning'])
            warning.setWordWrap(True)
            col.addWidget(warning)
        version = QComboBox()
        version.setObjectName('scanVersion')
        version.setEditable(True)
        version.addItems(sorted({'1.4','1.5','1.6',initial['game_version']},reverse=True))
        version.setCurrentText(initial['game_version'])
        form = QFormLayout()
        form.addRow(self.tr('RimWorld の版','RimWorld version'),version)
        col.addLayout(form)
        unknown = QCheckBox(self.tr('有効 MOD が不明（条件付き項目は警告して除外）','Active MODs unknown (warn and exclude conditional items)'))
        unknown.setObjectName('unknownActiveMods')
        unknown.setChecked(initial['active_mods'] is None)
        col.addWidget(unknown)
        search = QLineEdit()
        search.setPlaceholderText(self.tr('MOD 名・packageId で検索','Search MOD name or package ID'))
        col.addWidget(search)
        listing = QListWidget()
        listing.setObjectName('activeModList')
        selected = set(initial['active_mods'] if initial['active_mods'] is not None else ['ludeon.rimworld'])
        if initial['active_mods'] is None:
            try:
                selected.add(read_mod_metadata(source).package_id)
            except (ValueError,OSError,ET.ParseError):
                pass
        def fill(active):
            listing.clear()
            for package,name in sorted(candidates.items(),key=lambda item:item[1].casefold()):
                item = QListWidgetItem(f'{name}  [{package}]',listing)
                item.setData(Qt.UserRole,package)
                item.setFlags(item.flags()|Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if package in active else Qt.Unchecked)
        fill(selected)
        listing.setEnabled(not unknown.isChecked())
        unknown.toggled.connect(lambda checked:listing.setEnabled(not checked))
        search.textChanged.connect(lambda query:[listing.item(i).setHidden(query.casefold() not in listing.item(i).text().casefold()) for i in range(listing.count())])
        col.addWidget(listing,1)
        extra = QLineEdit()
        extra.setPlaceholderText(self.tr('一覧にない packageId（カンマ区切り、任意）','Additional package IDs, comma separated (optional)'))
        col.addWidget(extra)
        read_profile = QPushButton(self.tr('ゲームの MOD 設定を読み込む','Read game MOD settings'))
        def import_profile():
            config = self.mods_config_file() or user_data_directory()/'Config/ModsConfig.xml'
            filename,_ = QFileDialog.getOpenFileName(self,self.tr('ModsConfig.xml を選ぶ','Choose ModsConfig.xml'),str(config),'MOD settings (*.xml)')
            if not filename:
                return
            try:
                loaded = default_context(source,game,Path(filename),strict_profile=True)
                for package in loaded['active_mods'] or []:
                    candidates.setdefault(package,package)
                fill(set(loaded['active_mods'] or []))
                unknown.setChecked(loaded['active_mods'] is None)
            except Exception as exc:
                self.error(exc)
        read_profile.clicked.connect(import_profile)
        col.addWidget(read_profile)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(self.tr('この条件でスキャン','Scan with these conditions'))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        col.addWidget(buttons)
        if dialog.exec()!=QDialog.Accepted:
            return None
        active = None if unknown.isChecked() else [listing.item(i).data(Qt.UserRole) for i in range(listing.count()) if listing.item(i).checkState()==Qt.Checked]
        if active is not None:
            import re
            active += [p.strip() for p in re.split(r'[,;\s]+',extra.text()) if p.strip()]
        try:
            return validate_context(version.currentText().strip(),active)
        except ValueError as exc:
            self.error(exc)
            return None

    def extraction_context_dialog(self):
        if not self.project or self.busy:
            return
        source = Path(self.project.source)
        context = self.choose_scan_context(source)
        if context is not None:
            self.start_scan(source,context=context)

    def show_history(self):
        if not self.project or self.busy:
            return
        from .history import list_snapshots,restore_snapshot_report
        try:
            records = list_snapshots(self.project_path)
            dialog = QDialog(self)
            dialog.setWindowTitle(self.tr('履歴と復元','History and restore'))
            dialog.resize(820,480)
            col = QVBoxLayout(dialog)
            col.addWidget(QLabel(self.tr('復元前にも現在のデータをバックアップします。元 MOD は変更しません。','Current data is backed up before restoring. The source MOD is unchanged.')))
            listing = QListWidget()
            for record in records:
                item = QListWidgetItem(f'{record.time}  {record.message}  [{record.backend} / {record.id[:12]}]',listing)
                item.setData(Qt.UserRole,record.id)
            col.addWidget(listing)
            buttons = QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
            buttons.button(QDialogButtonBox.Ok).setText(self.tr('選択した履歴を復元','Restore selected snapshot'))
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            col.addWidget(buttons)
            if dialog.exec()==QDialog.Accepted and listing.currentItem() and self.save():
                # Regenerate into the checked output folder the editor uses everywhere else, not just ``mod``.
                report = restore_snapshot_report(self.project_path,listing.currentItem().data(Qt.UserRole),self.output_folder())
                self.project = report.project
                self.undo_batches.clear()
                self.redo_batches.clear()
                self.dirty = False
                self.populate()
                if report.notices or not report.output_updated:
                    self.info_dialog(self.tr('履歴から復元しました','Restored from history'),
                                     self.tr('プロジェクトを復元しました。','The project was restored.')
                                     +('' if report.output_updated else self.tr('\n翻訳 MOD は更新していません。現在の出力フォルダーをそのまま残しています。','\nThe translation MOD was not updated; the current output folder was kept.'))
                                     +''.join('\n- '+notice for notice in report.notices))
        except Exception as exc:
            self.error(self.error_text(exc))

    def show_warnings(self):
        if not self.project:
            return
        from .qa import qa_project
        from .diagnostic_text import explain, technical_label
        language = self.ui_language
        plain_of = lambda diagnostic: explain(diagnostic, language)
        diagnostics = [*self.project.diagnostics]
        diagnostics += [{'message':issue.message,'entry_id':issue.entry_id,'suggestion':issue.suggestion} for issue in qa_project(self.project)]
        if not diagnostics:
            diagnostics = [{'message':w,'entry_id':'','suggestion':''} for w in self.project.warnings]
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr('抽出と翻訳の診断','Extraction and translation diagnostics'))
        dialog.resize(900,520)
        col = QVBoxLayout(dialog)
        col.addWidget(QLabel(self.tr('翻訳項目はダブルクリックで移動できます。未検証候補は選択して出典を確認してください。',
                                    'Double-click translation entries to navigate. Select unverified candidates to inspect their source.')))
        search = QLineEdit()
        search.setObjectName('diagnosticSearch')
        search.setPlaceholderText(self.tr('保持済み診断を検索（本文・元ファイル・所有者型・フィールド）',
                                         'Search retained diagnostics (text, source file, owner, field)'))
        search.setClearButtonEnabled(True)
        # Search filters live; Enter must not activate the dialog's default page button.
        for key in (Qt.Key_Return, Qt.Key_Enter):
            shortcut = QShortcut(QKeySequence(key), search)
            shortcut.setContext(Qt.WidgetShortcut)
            shortcut.activated.connect(lambda: None)
        col.addWidget(search)
        listing = QListWidget()
        col.addWidget(listing,1)
        pages = QHBoxLayout()
        previous = QPushButton(self.tr('前のページ', 'Previous page'))
        previous.setObjectName('diagnosticPreviousPage')
        following = QPushButton(self.tr('次のページ', 'Next page'))
        following.setObjectName('diagnosticNextPage')
        page_status = QLabel()
        page_status.setObjectName('diagnosticPageStatus')
        pages.addWidget(previous)
        pages.addWidget(page_status,1)
        pages.addWidget(following)
        col.addLayout(pages)
        hint = QPlainTextEdit()
        hint.setObjectName('diagnosticDetail')
        hint.setReadOnly(True)
        col.addWidget(hint)
        # The original developer text stays reachable, but folded away until asked for.
        technical = QPlainTextEdit()
        technical.setObjectName('diagnosticTechnical')
        technical.setReadOnly(True)
        technical.setMaximumHeight(130)
        technical.hide()
        technical_toggle = QToolButton()
        technical_toggle.setObjectName('diagnosticTechnicalToggle')
        technical_toggle.setCheckable(True)
        technical_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        technical_toggle.setArrowType(Qt.RightArrow)
        technical_toggle.setText(technical_label(language))
        def fold_technical(shown):
            technical_toggle.setArrowType(Qt.DownArrow if shown else Qt.RightArrow)
            technical.setVisible(shown)
        technical_toggle.toggled.connect(fold_technical)
        col.addWidget(technical_toggle)
        col.addWidget(technical)
        source_pages = QHBoxLayout()
        source_previous = QPushButton(self.tr('前の原文ページ', 'Previous source page'))
        source_previous.setObjectName('diagnosticSourcePreviousPage')
        source_previous.setEnabled(False)
        source_following = QPushButton(self.tr('次の原文ページ', 'Next source page'))
        source_following.setObjectName('diagnosticSourceNextPage')
        source_following.setEnabled(False)
        source_match = QPushButton(self.tr('原文の最初の一致ページ', 'First matching source page'))
        source_match.setObjectName('diagnosticSourceMatchPage')
        source_match.setEnabled(False)
        source_status = QLabel()
        source_status.setObjectName('diagnosticSourcePageStatus')
        source_status.setWordWrap(True)
        source_pages.addWidget(source_previous)
        source_pages.addWidget(source_status, 1)
        source_pages.addWidget(source_following)
        source_pages.addWidget(source_match)
        col.addLayout(source_pages)
        source_start = 0
        source_match_start = None
        source_page_size = 4096
        def preview(value, limit=4096):
            text = str(value)
            if len(text) <= limit:
                return text
            return text[:limit] + self.tr(f'…（表示を省略・保持 {len(text)} 文字）',
                                          f'… (preview truncated; {len(text)} retained characters)')
        def render_detail(item):
            source_previous.setEnabled(False)
            source_following.setEnabled(False)
            source_status.clear()
            if not item:
                hint.clear()
                technical.clear()
                return
            diagnostic = item.data(Qt.UserRole + 1)
            plain = plain_of(diagnostic)
            technical.setPlainText(preview(plain.technical))
            details = [preview(plain.title)]
            if plain.action:
                details.append(preview(plain.action))
            unknown = diagnostic.get('code') == 'unknown-field'
            if unknown:
                details.append(self.tr(
                    '未検証の候補です。翻訳可能とは確認されていません。通常の翻訳項目・正式出力の対象には追加しません。',
                    'Unverified candidate. Localizability is unconfirmed. It is not added to translation entries or formal exports.'))
            for key, jp, en in [('source_file', '元ファイル', 'Source file'),
                                ('owner_type', '所有者型', 'Owner type'),
                                ('field_path', 'フィールド', 'Field')]:
                if unknown or diagnostic.get(key):
                    details.append(self.tr(jp, en) + ': ' + preview(diagnostic.get(key) or self.tr('不明', 'Unknown')))
            if unknown:
                source_text = str(diagnostic.get('source_text') or '')
                start = source_start
                end = min(start + source_page_size, len(source_text))
                details.append(self.tr('原文', 'Source text') + ': ' +
                               (source_text[start:end] or self.tr('不明', 'Unknown')))
                if source_text:
                    source_status.setText(self.tr(
                        f'保持原文 {start + 1}–{end} / {len(source_text)} 文字（Unicodeコードポイント）',
                        f'Retained source {start + 1}–{end} / {len(source_text)} characters (Unicode code points)'))
                source_previous.setEnabled(start > 0)
                source_following.setEnabled(end < len(source_text))
                if len(source_text) > source_page_size:
                    details.append(self.tr('このページ外の原文は表示を省略しています。前後の原文ページで確認できます。',
                                           'Source outside this page is omitted. Use the source page buttons to inspect it.'))
                if diagnostic.get('source_text_truncated'):
                    length = preview(diagnostic.get('source_text_length', '?'), 64)
                    details.append(self.tr(f'原文は一部省略されています（全 {length} 文字）。元ファイルで全文を確認してください。',
                                           f'Source text is truncated ({length} characters total). Inspect the source file for the full text.'))
            hint.setPlainText('\n'.join(details))
        def show_detail(item, _previous=None):
            nonlocal source_start, source_match_start
            source_start = 0
            source_match_start = None
            needle = search.text().casefold()
            diagnostic = item.data(Qt.UserRole + 1) if item else {}
            if needle and diagnostic.get('code') == 'unknown-field':
                text = str(diagnostic.get('source_text') or '')
                match = text.casefold().find(needle)
                if match >= 0:
                    folded_start = 0
                    match_start = None
                    for index, character in enumerate(text):
                        folded_end = folded_start + len(character.casefold())
                        if match_start is None and match < folded_end:
                            match_start = index
                        if match + len(needle) <= folded_end:
                            # Keep aligned pages unless they split the original match.
                            aligned_start = match_start // source_page_size * source_page_size
                            source_match_start = (aligned_start if index + 1 <= aligned_start + source_page_size
                                                  else match_start)
                            break
                        folded_start = folded_end
            source_match.setEnabled(source_match_start is not None)
            render_detail(item)
        def change_source_page(offset):
            nonlocal source_start
            source_start = max(0, source_start + offset * source_page_size)
            render_detail(listing.currentItem())
        source_previous.clicked.connect(lambda: change_source_page(-1))
        source_following.clicked.connect(lambda: change_source_page(1))
        def show_source_match():
            nonlocal source_start
            if source_match_start is not None:
                source_start = source_match_start
                render_detail(listing.currentItem())
        source_match.clicked.connect(show_source_match)
        listing.currentItemChanged.connect(show_detail)
        def go(item):
            if item.data(Qt.UserRole + 1).get('code') == 'unknown-field':
                return
            ident = item.data(Qt.UserRole)
            if ident and ident in self.project.entry_index():
                dialog.accept()
                self.navigate_entry(ident)
        listing.itemDoubleClicked.connect(go)
        page_size = 1500
        page = 0
        filtered = diagnostics
        def show_page(number):
            nonlocal page
            page = number
            listing.clear()
            start = page * page_size
            end = min(start + page_size, len(filtered))
            for diagnostic in filtered[start:end]:
                plain = plain_of(diagnostic)
                item = QListWidgetItem(preview(plain.title, 512),listing)
                item.setData(Qt.UserRole,diagnostic.get('entry_id',''))
                item.setToolTip(preview(plain.action))
                item.setData(Qt.UserRole + 1, diagnostic)
            first = start + 1 if filtered else 0
            page_status.setText(self.tr(f'{first}–{end} / 検索結果 {len(filtered)} 件（保持済み全 {len(diagnostics)} 件）',
                                        f'{first}–{end} / {len(filtered)} matches ({len(diagnostics)} retained total)'))
            previous.setEnabled(page > 0)
            following.setEnabled(end < len(filtered))
            if listing.count():
                listing.setCurrentRow(0)
            else:
                hint.clear()
                technical.clear()
        def filter_diagnostics(query):
            nonlocal filtered
            needle = query.casefold()
            keys = ('message', 'code', 'entry_id', 'source_file', 'owner_type', 'field_path',
                    'source_text', 'suggestion')
            def searchable(diagnostic):
                plain = plain_of(diagnostic)
                return [str(diagnostic.get(key) or '') for key in keys] + [plain.title, plain.action]
            filtered = [diagnostic for diagnostic in diagnostics
                        if not needle or any(needle in value.casefold() for value in searchable(diagnostic))]
            show_page(0)
        search.textChanged.connect(filter_diagnostics)
        previous.clicked.connect(lambda: show_page(page - 1))
        following.clicked.connect(lambda: show_page(page + 1))
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(dialog.reject)
        col.addWidget(close)
        show_page(0)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def metadata_dialog(self):
        if not self.project or self.busy:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr('配布用 MOD 情報','Translation MOD metadata'))
        form = QFormLayout(dialog)
        widgets = {}
        for code,jp,en,default in [('name','翻訳 MOD 名','Translation MOD name',self.project.name),('author','翻訳者','Translator',self.settings.data['default_translator']),('description','説明','Description','Community translation; requires the original MOD.'),('license','翻訳のライセンス（任意）','Translation license (optional)',self.settings.data['default_license'])]:
            w = QLineEdit(self.project.metadata.get(code,default))
            widgets[code] = w
            form.addRow(self.tr(jp,en),w)
        preview = QCheckBox(self.tr('元 MOD のプレビュー画像を使う（公開時は元作者の許諾を確認）','Use source artwork (check permission before publishing)'))
        preview.setChecked(self.project.metadata.get('use_source_preview','false')=='true')
        form.addRow(preview)
        notice = QLabel(self.tr('元 MOD のプレビュー画像は元作者の著作物です。公開前に使用許諾・ライセンスを確認してください。',
                              'The source MOD\'s preview image belongs to its author. Check the licence or permission before publishing.'))
        notice.setWordWrap(True)
        form.addRow(notice)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec()==QDialog.Accepted:
            for key,widget in widgets.items():
                self.project.metadata[key] = widget.text().strip()
            self.project.metadata['use_source_preview'] = 'true' if preview.isChecked() else 'false'
            self.on_edit()

    def choose_game(self):
        values = discover_installations(custom_paths=self.settings.data['game_paths'])
        if not values:
            selected = QFileDialog.getExistingDirectory(self,self.tr('RimWorld のゲーム本体フォルダー','RimWorld game folder'))
            if not selected:
                return None
            values = discover_installations(custom_paths=[Path(selected)])
            if not values:
                self.error(self.tr('Data/Core とゲーム実行ファイルのあるフォルダーを選んでください。','Choose the game folder containing Data/Core and the RimWorld executable.'))
                return None
            self.settings.data['game_paths'].append(selected)
            self.save_preferences()
        if len(values)>1:
            labels = [str(v.root) for v in values]
            selected,ok = QInputDialog.getItem(self,self.tr('ゲームの場所','Game installation'),self.tr('使用するゲームを選ぶ','Choose installation'),labels,0,False)
            if not ok:
                return None
            return values[labels.index(selected)]
        return values[0]

    def install_dialog(self):
        if not self.project or self.busy or not self.generate():
            return
        game = self.choose_game()
        if not game:
            return
        from .installation import review_installation,install_translation
        try:
            plan = review_installation(self.output_folder(),game,source=Path(self.project.source))
            summary = '\n'.join(plan.actions)+f'\n\n{plan.file_count} files / {plan.total_bytes//1024} KiB\n'
            summary += self.tr('元 MOD の有効化が必要です。更新前には翻訳だけをバックアップします。','Enable the original MOD as well. Only the previous translation package is backed up.')
            if QMessageBox.question(self,self.tr('導入内容を確認','Review installation'),summary,QMessageBox.Ok|QMessageBox.Cancel,QMessageBox.Cancel)==QMessageBox.Ok:
                result = install_translation(plan)
                self.info_dialog(self.tr('導入完了','Installation complete'),str(result.destination)+(('\nBackup: '+str(result.backup)) if result.backup else ''))
        except Exception as exc:
            self.error(exc)

    def restore_install_dialog(self):
        if not self.project or self.busy:
            return
        game = self.choose_game()
        if not game:
            return
        value = QFileDialog.getExistingDirectory(self,self.tr('復元する翻訳 MOD のバックアップ','Choose translation MOD backup'),str(game.mods))
        if value and QMessageBox.question(self,self.tr('翻訳 MOD の復元','Restore translation MOD'),self.tr('現在の翻訳 MOD をバックアップして、この内容に戻します。','Back up the installed translation and restore this package?'),QMessageBox.Ok|QMessageBox.Cancel,QMessageBox.Cancel)==QMessageBox.Ok:
            try:
                from .installation import restore_installation
                result = restore_installation(Path(value),game)
                self.info_dialog(self.tr('復元完了','Restored'),str(result.destination))
            except Exception as exc:
                self.error(exc)

    def dependencies_dialog(self):
        if not self.project or not self.generate():
            return
        game = self.choose_game()
        if game:
            from .installation import available_mod_paths,diagnose_load_order
            from .platforms import user_data_directory
            # This path is inspected only; real ModsConfig is never changed.
            config = self.mods_config_file() or user_data_directory(game.platform)/'Config/ModsConfig.xml'
            issues = diagnose_load_order(self.output_folder(),available_mod_paths(game),config if config.exists() else None)
            self.info_dialog(self.tr('必要 MOD と読み込み順','Dependencies and load order'),'\n'.join(d.message for d in issues) or self.tr('見つかる依存 MOD と読み込み順に問題はありません。','No dependency or load-order problems were found.'))

    def launch_test_dialog(self):
        if not self.project or self.busy or not self.generate():
            return
        game = self.choose_game()
        if not game:
            return
        from .installation import available_mod_paths,read_mod_metadata
        paths = available_mod_paths(game)
        available = {}
        for path in paths:
            try:
                available[read_mod_metadata(path).package_id] = path
            except (OSError,ValueError):
                pass
        wanted,missing = {},[]
        def collect(path):
            item = read_mod_metadata(path)
            if item.package_id in wanted or item.package_id.startswith('ludeon.'):
                return
            wanted[item.package_id] = path
            for dependency in item.dependencies:
                if dependency.package_id.startswith('ludeon.'):
                    continue
                if dependency.package_id in available:
                    collect(available[dependency.package_id])
                else:
                    missing.append(dependency.display_name)
        collect(Path(self.project.source))
        if missing:
            self.error(self.tr('必要 MOD が不足しています: ','Missing source dependencies: ')+', '.join(missing))
            return
        explanation = self.tr('ゲーム本体と必要 MOD をプロジェクト内へコピーします。通常のセーブ・設定は使わず、約2分で終了します。十分な空き容量が必要です。起動ログの成功だけでは訳の画面表示を確認したことにはなりません。','Copy the game and required MODs into this project. Use isolated saves/settings and stop after about two minutes. Free disk space is required. Startup/log success does not prove translation display.')
        if QMessageBox.question(self,self.tr('隔離ゲームテスト','Isolated game test'),explanation,QMessageBox.Ok|QMessageBox.Cancel,QMessageBox.Cancel)!=QMessageBox.Ok:
            return
        import uuid
        destination = self.project_path.parent/'game-tests'/uuid.uuid4().hex[:10]
        self.busy = True
        self.set_project_controls(False)
        self.table.setEnabled(False)
        self.japanese.setReadOnly(True)
        self.scan_progress.setRange(0,0)
        self.scan_progress.show()
        self.cancel_scan_button.setText(self.tr('ゲームテストを中止','Cancel game test'))
        self.cancel_scan_button.show()
        self.game_thread = QThread(self)
        self.game_worker = GameTestWorker(game,self.output_folder(),destination,list(wanted.values()),list(wanted),self.project.language)
        self.game_worker.moveToThread(self.game_thread)
        self.game_thread.started.connect(self.game_worker.run)
        self.game_worker.stage.connect(self.statusBar().showMessage)
        self.game_worker.finished.connect(self.game_thread.quit,Qt.DirectConnection)
        self.game_worker.finished.connect(self.receive_game_test,Qt.QueuedConnection)
        self.game_worker.finished.connect(self.game_worker.deleteLater)
        self.game_thread.start()

    @Slot(object,str)
    def receive_game_test(self,result,error):
        self.game_thread.wait()
        self.game_thread.deleteLater()
        self.busy = False
        self.table.setEnabled(True)
        self.japanese.setReadOnly(False)
        self.set_project_controls(True)
        self.scan_progress.hide()
        self.cancel_scan_button.hide()
        self.game_worker = None
        if error:
            self.error(error)
        else:
            self.info_dialog(self.tr('ゲームテスト結果','Game test results'),json.dumps(asdict(result),ensure_ascii=False,indent=2))

    def preferences_dialog(self):
        from .dialogs import PreferencesDialog
        dialog = PreferencesDialog(self)
        try:
            if dialog.exec()==QDialog.Accepted:
                self.apply_preferences(dialog.collect())
        finally:
            dialog.deleteLater()

    def apply_preferences(self,changes):
        """Store edited settings and make the running editor follow them."""
        language = changes.pop('ui_language',None)
        theme = changes.pop('theme_mode',None)
        size = changes.pop('font_size',None)
        from .settings import normalize
        previous_language = self.settings.data['ui_language']
        candidate = json.loads(json.dumps(self.settings.data))
        candidate.update({k:v for k,v in changes.items() if k in candidate})
        self.settings.data.update(normalize(candidate))
        self.autosave.setInterval((self.settings.data['autosave_seconds'] or 60)*1000)
        if not self.settings.data['autosave_seconds']:
            self.autosave.stop()
        elif self.dirty and not self.autosave.isActive():
            self.autosave.start()
        self.apply_user_folders()
        if theme is not None:
            self.set_theme_mode(theme,persist=False)
        if size is not None:
            self.set_editor_font(size,persist=False)
        if language is not None and language!=previous_language:
            self.set_gui_language(language)
        else:
            self.save_preferences()

    def export_settings_file(self):
        name,_ = QFileDialog.getSaveFileName(self,self.tr('設定を書き出す','Export settings'),'rimworld-translator-settings.json','JSON (*.json)')
        if not name:
            return False
        try:
            self.settings.export_to(Path(name))
        except OSError as exc:
            self.error(exc)
            return False
        self.statusBar().showMessage(self.tr('設定を書き出しました（最近のプロジェクトと日別カウントは含みません）。','Settings exported (recent projects and daily counts are left out).'),8000)
        return True

    def import_settings_file(self):
        name,_ = QFileDialog.getOpenFileName(self,self.tr('設定を取り込む','Import settings'),'','JSON (*.json)')
        if not name:
            return False
        try:
            self.settings.import_from(Path(name))
        except (OSError,ValueError) as exc:
            self.error(self.tr(f'設定を取り込めませんでした: {exc}',f'Could not import settings: {exc}'))
            return False
        self.apply_preferences({})
        self.set_theme_mode(self.settings.data['theme_mode'],persist=False)
        self.set_editor_font(self.settings.data['font_size'],persist=False)
        from .settings import resolve_ui_language
        if resolve_ui_language(self.settings.data['ui_language'])!=self.ui_language:
            self.set_gui_language(self.settings.data['ui_language'])
        self.statusBar().showMessage(self.tr('設定を取り込みました。','Settings imported.'),8000)
        return True

    def set_output_folder(self,folder):
        """Save this project's output folder (empty restores the default); an overlapping folder is refused."""
        if not self.project or self.busy:
            return False
        from .output_paths import check_output_folder,protected_folders,OutputLocationError
        previous = self.project.output_folder
        if folder:
            try:
                check_output_folder(folder,project_path=self.project_path,
                                    protected=protected_folders(self.settings.data,self.discovered_games(),self.project.source))
            except OutputLocationError as exc:
                self.error(exc.text(self.ui_language))
                return False
        self.project.output_folder = folder
        try:
            self.project.save(self.project_path)
        except (OSError,ValueError) as exc:
            self.project.output_folder = previous
            self.error(exc)
            return False
        from .output_paths import shown_output
        shown = shown_output(self.project_path,self.project)
        self.location.setText(self.tr(f'{self.project.name}  ·  出力先: {shown}',f'{self.project.name} · Output: {shown}'))
        return True

    def output_folder_dialog(self):
        if not self.project or self.busy:
            return
        from .output_paths import shown_output
        current = shown_output(self.project_path,self.project)
        box = QMessageBox(self)
        box.setWindowTitle(self.tr('出力先フォルダー','Output folder'))
        box.setText(self.tr('翻訳 MOD の書き出し先です。','Where the translation MOD is written.'))
        box.setInformativeText(f'{current}\n\n'+self.tr('元 MOD・Steam Workshop・ゲームの Data・設定で追加した MOD フォルダーの中は選べません。',
                                                          'Source MOD, Steam Workshop, the game Data folder and MOD folders added in Preferences are refused.'))
        choose = box.addButton(self.tr('フォルダーを選ぶ','Choose folder'),QMessageBox.AcceptRole)
        reset = box.addButton(self.tr('既定に戻す','Use default'),QMessageBox.ActionRole)
        box.addButton(QMessageBox.Cancel)
        box.exec()
        if box.clickedButton() is choose:
            folder = QFileDialog.getExistingDirectory(self,self.tr('出力先フォルダーを選ぶ','Choose output folder'),str(current.parent if current.parent.is_dir() else Path.home()))
            if folder:
                self.set_output_folder(folder)
        elif box.clickedButton() is reset:
            self.set_output_folder('')

    def check_updates_dialog(self):
        from .updates import check_for_update
        settings = self.settings.data.copy()
        # Network checks never block the GUI event loop.
        def check():
            result = check_for_update(settings['release_repository'] or None,enabled=settings['check_updates'])
            self.update_finished.emit(result)
        threading.Thread(target=check,daemon=True).start()

    @Slot(object)
    def show_update_result(self,result):
        self.info_dialog(self.tr('アップデート','Updates'),result.message+'\n'+(result.release_url or ''))

    def diagnostic_text(self):
        """Environment and settings for a problem report: no translation text, no paths, no names."""
        from .settings import settings_summary
        from .version import __version__
        import platform
        output = ('default' if not (self.project and self.project.output_folder) else 'set')
        return (f'RimWorld Translation Editor {__version__}\n{platform.platform()}\nGUI: {self.ui_language}\n'
                f'Entries: {len(self.model.entries)}\nLanguage: {self.project.language if self.project else "none"}\n'
                f'output_folder: {output}\n\nSettings\n{settings_summary(self.settings.data)}\n')

    def copy_diagnostic_info(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.diagnostic_text())
        self.statusBar().showMessage(self.tr('問題報告用の環境情報をコピーしました（翻訳本文・元パス・翻訳者名は含みません）。','Copied diagnostic information without translation text, paths or the translator name.'),10000)
