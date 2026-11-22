"""Qt Widgets desktop editor. Source scanning runs outside the GUI thread."""
from collections import Counter
import copy
from datetime import date
from pathlib import Path
import sys
import re
import tarfile
import threading

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QEvent, QAbstractTableModel, QUrl, QModelIndex, QObject, QSortFilterProxyModel, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QBrush, QColor, QDesktopServices, QFont, QKeySequence, QPixmap
from PySide6.QtWidgets import QVBoxLayout, QProgressBar, QApplication, QBoxLayout, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QTableView, QVBoxLayout, QWidget

from .cheer import daily_cheer, progress_cheer, today_line
from .core import Entry, KEY, Project, export_mod, export_shared, export_versions_test, placeholder_warning, scan_mod, safe_xml, writable_destination
from .field_semantics import entry_nonlocalizable_reason
from .qa import grammar_rule_prefix, qa_entry, qa_project
from .row_filters import def_type as row_def_type, row_statuses
from .history import snapshot
from .languages import discover_languages, LANGUAGES
from .i18n import install_qt_translator
from .dialogs import select_languages, select_workshop_mod, flag_icon
from .preview import find_source_preview
from .layout import ElidedLabel, select_untranslated, setup_editor_ui
from .editor_panel import EditorPanelMixin, note_marker, reason_lines
from .gui_tools import ToolsMixin
from .output_paths import shown_output
from .settings import SettingsStore, resolve_ui_language
from .workflow import translation_memory
from .i18n import text as ui_text

WORKSHOP = Path.home() / '.local/share/Steam/steamapps/workshop/content/294100'
STATUS = {'untranslated': '未訳', 'translated': '翻訳済み', 'changed': '原文変更', 'needs-review': '要確認', 'stale': '削除・旧項目'}


class EntryModel(QAbstractTableModel):
    edited = Signal()
    newly_translated = Signal()
    headers = ['状態', 'キー', '英語', '日本語']
    note_header = '印'
    def __init__(self):
        super().__init__()
        self.entries = []
        self.row_for_id = {}
        self._haystacks = []
        self.project = None
        self.ui_language = 'ja'
        self.headers = ['状態', 'キー', '英語', '日本語']
        self.status_colors = {}
    def status_dot(self, color):
        if not color:
            return None
        cache = self.__dict__.setdefault('_dots', {})
        if color not in cache:
            from PySide6.QtGui import QPainter, QPixmap
            pixmap = QPixmap(10, 10)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color))
            painter.drawEllipse(1, 1, 8, 8)
            painter.end()
            cache[color] = pixmap
        return cache[color]
    def replace(self, entries):
        self.beginResetModel()
        self.entries = entries
        self.row_for_id = {e.id:i for i,e in enumerate(entries)}
        self._haystacks = [None] * len(entries)
        self.endResetModel()
    def haystack(self, row):
        """Lower-cased search text of one row, built on first use; rebuilt when its translation changed."""
        entry = self.entries[row]
        found = self._haystacks[row] if row < len(self._haystacks) else None
        if found is None or found[0] != entry.japanese:
            found = (entry.japanese, '\n'.join((entry.key, entry.english, entry.japanese, entry.source_file)).casefold())
            if row < len(self._haystacks):
                self._haystacks[row] = found
        return found[1]
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.entries)
    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 5
    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.headers[section] if section < len(self.headers) else ui_text(self.note_header, self.ui_language, 'Flag')
        if role == Qt.ToolTipRole and orientation == Qt.Horizontal and section == 4:
            return ui_text('メモと印',self.ui_language,'Notes and flags')
    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid(): return None
        entry = self.entries[index.row()]
        if index.column() == 4:
            if role == Qt.DisplayRole:
                return ('⊘' if entry.excluded else '') + note_marker(self.project, entry.id)
            if role == Qt.ToolTipRole and ((self.project and entry.id in self.project.notes) or entry.excluded):
                from .notes import FLAG_LABELS, get_note
                from .editor_panel import FLAG_ENGLISH
                note = get_note(self.project, entry.id) if self.project and entry.id in self.project.notes else None
                parts = [ui_text('手動で除外中（出力されません）', self.ui_language, 'Manually excluded (not exported)')] if entry.excluded else []
                if note is not None:
                    parts += [ui_text(FLAG_LABELS.get(note.flag,''), self.ui_language, FLAG_ENGLISH.get(note.flag,'')), note.text]
                return '\n'.join(part for part in parts if part)
            if role == Qt.TextAlignmentRole:
                return int(Qt.AlignCenter)
            return None
        if role in (Qt.DisplayRole, Qt.EditRole):
            status = ui_text(STATUS[entry.status],self.ui_language)
            if entry_nonlocalizable_reason(entry):
                status = ui_text('内部データ', self.ui_language, 'Internal data')
            elif entry.excluded:
                status = ui_text('除外',self.ui_language,'Excluded')
            elif entry.approved:
                status = ui_text('承認済み',self.ui_language,'Approved')
            elif entry.reviewed:
                status = ui_text('確認済み',self.ui_language,'Reviewed')
            return [status, entry.key, entry.english, entry.japanese][index.column()]
        if role == Qt.ForegroundRole and index.column() == 0 and self.status_colors:
            key = ('internal' if entry_nonlocalizable_reason(entry) else
                   'excluded' if entry.excluded else entry.status)
            color = self.status_colors.get(key)
            return QBrush(QColor(color)) if color else None
        if role == Qt.DecorationRole and index.column() == 0 and self.status_colors:
            # A coloured dot beside the status text, so state is not carried by text colour alone.
            key = ('internal' if entry_nonlocalizable_reason(entry) else
                   'excluded' if entry.excluded else entry.status)
            return self.status_dot(self.status_colors.get(key))
        if role == Qt.FontRole and index.column() == 0 and entry.status in ('needs-review','changed'):
            font = QFont()
            font.setBold(True)
            return font
        if role == Qt.ToolTipRole:
            reasons = ('\nReasons: ' + ', '.join(entry.reasons)) if entry.reasons else ''
            return f'{entry.kind}/{entry.group}\n{entry.source_file}\nConfidence: {entry.confidence}{reasons}\n'+ '\n'.join(entry.evidence) + '\n'+placeholder_warning(entry)
    def flags(self, index):
        flags = super().flags(index)
        if not index.isValid():
            return flags
        entry = self.entries[index.row()]
        editable = index.column() == 3 and not entry_nonlocalizable_reason(entry)
        return flags | Qt.ItemIsEditable if editable else flags
    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid() or index.column() != 3 or role != Qt.EditRole: return False
        entry = self.entries[index.row()]
        if entry_nonlocalizable_reason(entry): return False
        if entry.japanese == value: return False
        was_empty = not entry.japanese.strip()
        if self.project:
            self.project.set_translation(entry.id,str(value))
        else:
            entry.japanese = str(value)
        if was_empty and entry.japanese.strip():
            self.newly_translated.emit()
        self.dataChanged.emit(self.index(index.row(), 0), self.index(index.row(), 3))
        self.edited.emit()
        return True


from .navigator import build as build_tree, current_scope, group_stats, in_scope, kind_name, refresh_counts as refresh_tree_counts


class EntryFilter(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.query = ''
        self.status = ''
        self.source_file = ''
        self.scope = ()
        self.attention = False
        self.def_type = ''
        self.file = ''
        self.flag = ''
        self.assignee = ''
    def filterAcceptsRow(self, row, parent):
        model = self.sourceModel()
        entry = model.entries[row]
        if self.scope and not in_scope(entry, self.scope):
            return False
        if self.attention and entry.status not in ('changed','needs-review'):
            return False
        if self.def_type and row_def_type(entry) != self.def_type:
            return False
        if self.file and entry.source_file != self.file:
            return False
        if self.assignee:
            project = model.project
            if (project.assignments.get(entry.source_file, '') if project else '') != self.assignee:
                return False
        if self.flag:
            project = self.sourceModel().project
            found = ((project.notes.get(entry.id) or {}).get('flag','') if project else '')
            if (self.flag=='*' and not found) or (self.flag!='*' and found!=self.flag):
                return False
        special = {'reviewed':entry.reviewed,'approved':entry.approved,'new':entry.is_new,'excluded':entry.excluded}
        if self.status=='qa-error':
            project = self.sourceModel().project
            matched = 'qa-error' in row_statuses(entry,project.glossary if project else None)
        else:
            matched = special.get(self.status,entry.status==self.status) if self.status else True
        return matched and (not self.source_file or self.source_file in entry.source_file.casefold()) and (not self.query or self.query in model.haystack(row))


def claims_version(game, version):
    return bool(re.fullmatch(r'\d+\.\d+(?:\.\d+)*', game.version or '')) and '.'.join(game.version.split('.')[:2]) == version


def matching_installation(games, version):
    """The installation whose major.minor version is the requested one, Steam first, or None.

    A folder without its Assembly-CSharp.dll, or whose DLL names another version, is broken or mixed and is never used.
    """
    candidates = sorted((g for g in games if claims_version(g, version)), key=lambda g: g.distribution != 'Steam')
    return next((g for g in candidates if not refusal(g, version)), None)


def refusal(game, version):
    """Why ``game`` cannot serve ``version``, or '' when it can."""
    from .game_library import contradicts, game_dll, identify_game
    if game_dll(game.root) is None:
        return 'it has no Assembly-CSharp.dll'
    identity = identify_game(game.root)
    if contradicts(identity, version):
        return f'its Assembly-CSharp.dll is {", ".join(identity.dll_versions)}'
    return ''


def rejected_game_diagnostics(games, version):
    """One diagnostic per folder claiming ``version`` that cannot serve it."""
    found = []
    for game in games:
        reason = refusal(game, version) if claims_version(game, version) else ''
        if reason:
            message = f'Game folder {game.root} says {version} but {reason}; it is broken or mixed and was not used.'
            found.append({'code': 'game-folder-rejected', 'message': message, 'source_file': '', 'entry_id': '',
                          'suggestion': 'Copy that game version again, or remove the folder from the game list.'})
    return found


def add_scan_diagnostics(scan, diagnostics):
    for diagnostic in diagnostics:
        scan.warnings.append(diagnostic['message'])
        scan.warning_count += 1
        scan.diagnostics.append(diagnostic)


def scan_schema(source, version, active_mods, game, context_paths=(), cache_dir=None, cancel=None, games=(), cache_root=''):
    """Field metadata for one scan: the matching game's assembly, else a table read from another installed game, plus MOD DLLs.

    Assemblies are read as metadata only and never executed. The table is built from the user's own installation
    and cached outside the project; nothing of the game is shipped with this editor.
    """
    from .extraction import content_files, resolve_load_folders
    from .game_library import contradicts, game_dll, identify_game
    from .platforms import app_cache_directory
    from .schema import game_table_schema, schema_from_assemblies
    paths = [p for p in [game_dll(game.root)] if p] if game else []
    base = None
    if not paths:
        # A broken or mixed folder must not lend its types either.
        sound = [g.root for g in games if not contradicts(identity := identify_game(g.root), identity.version)]
        base = game_table_schema(app_cache_directory(override=cache_root) / 'game-table', sound)
    for folder in (source, *context_paths):
        paths += content_files(resolve_load_folders(folder, version, active_mods), 'Assemblies', '.dll')
    return schema_from_assemblies(paths, cache_dir, cancel=cancel, base=base)


class Scanner(QObject):
    finished = Signal(object, str)
    progress = Signal(int,int,int,str)
    def __init__(self, source, options=None, inspect_metadata=False, game_paths=(), mod_settings=None):
        super().__init__()
        self.source = source
        # Folder settings only (workshop_folder, mods_folder, external_mod_folders); read-only prerequisite lookup.
        self.mod_settings = dict(mod_settings or {})
        self.options = options or {}
        self.inspect_metadata = inspect_metadata
        self.game_paths = game_paths
        self.cancel = threading.Event()
    def user_mod_folders(self, games):
        """MOD folders inside the user's Workshop, Mods and added folders; found by reading, never written."""
        from .platforms import mod_folders, mod_roots
        return mod_folders(mod_roots(self.mod_settings, games).all())

    def run(self):
        try:
            from .extraction import ScanCancelled
            from .platforms import discover_installations
            from .scan_context import dependency_context, report_dependency_gaps
            if self.cancel.is_set():
                raise ScanCancelled()
            games = discover_installations(custom_paths=self.game_paths)
            requested_version = self.options.get('game_version', '1.6')
            game = matching_installation(games, requested_version)
            dependencies = dependency_context(game, games, self.source, requested_version, self.options.get('active_mods'),
                                              self.user_mod_folders(games), cancel=self.cancel.is_set)
            self.options.setdefault('context_sources', list(dependencies.sources))
            scan_options = dict(self.options)
            if scan_options.get('active_mods') is not None:
                # Installed prerequisites are loaded by the game, so MayRequire on them holds; the saved profile is unchanged.
                scan_options['active_mods'] = list(dict.fromkeys([*scan_options['active_mods'], *dependencies.active_ids]))
            else:
                # Unknown profile: installed expansions and found prerequisites count as loaded, everything else as absent.
                scan_options['assumed_active'] = list(dependencies.assumed_active)
            schema = None
            if self.inspect_metadata:
                self.progress.emit(0,0,0,'Inspecting C# field metadata…')
                cache = self.options.get('cache_path')
                folder_mods = scan_options.get('active_mods')
                schema = scan_schema(self.source, requested_version,
                                     folder_mods if folder_mods is not None else scan_options['assumed_active'], game,
                                     self.options.get('context_sources', ()),
                                     Path(cache).parent/'schema' if cache else None, self.cancel.is_set, games,
                                     self.mod_settings.get('cache_directory',''))
            result = scan_mod(self.source,**scan_options,schema=schema,progress=self.progress.emit,cancel=self.cancel.is_set)
            from .extraction import mark_official
            from .official_translations import official_field_patterns
            # Fields the game's own translators translate: an independent reason, shown per entry.
            mark_official(result.entries, official_field_patterns(game.root if game else None, 'Japanese'))
            if 'active_mods' in result.stats:
                # The project keeps the user's own profile; prerequisites were added for this scan only.
                result.stats['active_mods'] = self.options.get('active_mods')
            report_dependency_gaps(result, dependencies, schema)
            add_scan_diagnostics(result, rejected_game_diagnostics(games, requested_version))
            result.stats['game_context'] = {'version': requested_version,
                                           'root': str(game.root) if game else None,
                                           'installed_version': game.version if game else None}
            if game is None:
                builtin_version = schema.builtin_version if schema is not None else ''
                message = (f'No verified RimWorld {requested_version} installation is available. '
                           + (f'Game field types come from RimWorld {builtin_version}, read from the game installed here; '
                              'game XML was not borrowed from another version; '
                              if builtin_version else 'Game XML/type context was not borrowed from another version; ')
                           + 'static extraction remains unverified.')
                result.stats['game_context']['builtin_schema'] = builtin_version or None
                result.warnings.append(message)
                result.warning_count += 1
                result.diagnostics.append({'code': 'game-version-context-unverified',
                                           'message': message, 'source_file': '', 'entry_id': '',
                                           'suggestion': 'Provide a matching game installation for this version.'})
            self.finished.emit(result,'')
        except ScanCancelled:
            self.finished.emit(None,'cancelled')
        except Exception as exc:
            self.finished.emit(None,str(exc) or type(exc).__name__)


class DeclaredVersionScanner(Scanner):
    """Sequential scans of every declared version, each with its own type information.

    A version with a matching installation reads that game's assembly. Any other version uses the field table
    read from an installed game of another version (marked unverified); no game XML is reused for it.
    """
    def run(self):
        from .extraction import ScanCancelled
        from .multiversion import declared_versions, scan_declared_versions
        from .platforms import discover_installations
        from .scan_context import dependency_context, report_dependency_gaps
        try:
            contexts, dependencies = {}, {}
            games = discover_installations(custom_paths=self.game_paths)
            cache = self.options.get('cache_path')
            for version in declared_versions(self.source):
                if self.cancel.is_set():
                    raise ScanCancelled()
                self.progress.emit(0, 0, 0, version)
                game = matching_installation(games, version)
                # Game XML comes only from the installation of this same version; prerequisites from any MOD folder.
                # The active-MOD profile belongs to the installed game only, so other versions use prerequisites alone.
                dependencies[version] = dependency_context(game, games, self.source, version, None,
                                                          self.user_mod_folders(games), cancel=self.cancel.is_set)
                sources = list(dependencies[version].sources)
                assumed = list(dependencies[version].assumed_active)
                contexts[version] = {'context_sources': sources, 'assumed_active': assumed}
                if self.inspect_metadata:
                    contexts[version]['schema'] = scan_schema(
                        self.source, version, assumed, game, sources,
                        Path(cache).parent/'schema' if cache else None, self.cancel.is_set, games,
                        self.mod_settings.get('cache_directory',''))
            result = scan_declared_versions(
                self.source, contexts=contexts, cancel=self.cancel.is_set,
                progress=lambda version, done, total: self.progress.emit(done, total, 0, version))
            from .extraction import mark_official
            from .official_translations import official_field_patterns
            for version, scan in result.scans.items():
                game = matching_installation(games, version)
                mark_official(scan.entries, official_field_patterns(game.root if game else None, 'Japanese'))
                builtin_version = getattr(contexts.get(version, {}).get('schema'), 'builtin_version', '')
                if builtin_version:
                    message = (f'No verified RimWorld {version} installation is available. Game field types come from '
                               f'RimWorld {builtin_version}, read from the game installed here; static extraction remains unverified.')
                    scan.warnings.append(message)
                    scan.warning_count += 1
                    scan.diagnostics.append({'code': 'game-version-context-unverified', 'message': message,
                                             'source_file': '', 'entry_id': '',
                                             'suggestion': 'Provide a matching game installation for this version.'})
                    scan.stats['game_context'] = {'version': version, 'root': None, 'installed_version': None,
                                                  'builtin_schema': builtin_version}
                report_dependency_gaps(scan, dependencies[version], contexts[version].get('schema'))
                add_scan_diagnostics(scan, rejected_game_diagnostics(games, version))
            self.finished.emit(result, '')
        except ScanCancelled:
            self.finished.emit(None, 'cancelled')
        except Exception as exc:
            self.finished.emit(None, str(exc) or type(exc).__name__)


class Window(EditorPanelMixin,ToolsMixin,QMainWindow):
    update_finished = Signal(object)
    def __init__(self, settings_path=None):
        super().__init__()
        self.project = None
        self.project_path = None
        self.current = None
        self.dirty = False
        self.busy = False
        self.trial_output_report = None
        self._cheer_pct = 0
        self._cheer_armed = False
        self.settings = SettingsStore(settings_path)
        self.ui_language = resolve_ui_language(self.settings.data['ui_language'])
        setup_editor_ui(self, STATUS)
        # Version controls share the language row; the rarely used actions sit in one menu button.
        version_row = self.language_row
        version_row.addSpacing(18)
        version_label = QLabel(self.tr('編集するゲーム版', 'Game version to edit'))
        version_label.setObjectName('muted')
        version_row.addWidget(version_label)
        self.version_selector = QComboBox()
        self.version_selector.setObjectName('editingVersion')
        self.version_selector.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.version_selector.setMinimumContentsLength(5)
        self.version_selector.setToolTip(self.tr('走査済みの版を個別に編集します。訳や承認は版ごとに保持します。',
                                                'Edit scanned versions independently. Translations and approvals belong to each version.'))
        self.version_selector.setEnabled(False)
        version_row.addWidget(self.version_selector)
        self.share_translation_button = QPushButton(self.tr('この訳を別版へ共有', 'Share this translation'))
        self.share_translation_button.setObjectName('shareTranslation')
        self.share_translation_button.setEnabled(False)
        self.share_translation_button.clicked.connect(self.share_translation_dialog)
        version_row.addWidget(self.share_translation_button)
        self.scan_declared_button = QPushButton(self.tr('宣言版を確認・追加', 'Check and add declared versions'))
        self.scan_declared_button.setObjectName('scanDeclaredVersions')
        self.scan_declared_button.setEnabled(False)
        self.scan_declared_button.clicked.connect(self.scan_declared_versions_dialog)
        version_row.addWidget(self.scan_declared_button)
        self.test_export_button = QPushButton(self.tr('宣言版を試験出力', 'Export declared versions for testing'))
        self.test_export_button.setObjectName('testExportVersions')
        self.test_export_button.setEnabled(False)
        self.test_export_button.clicked.connect(self.generate_versions_test)
        version_row.addWidget(self.test_export_button)
        from PySide6.QtWidgets import QMenu
        actions = ((self.share_translation_button,),(self.scan_declared_button,),(self.test_export_button,))
        self.version_menu = QMenu(self)
        self.version_menu_actions = []
        for (button,) in actions:
            button.setVisible(False)
            action = self.version_menu.addAction(button.text())
            action.triggered.connect(lambda _checked=False,b=button:b.click())
            self.version_menu_actions.append((action,button))
        self.version_menu.aboutToShow.connect(lambda:[a.setEnabled(b.isEnabled()) for a,b in self.version_menu_actions])
        self.version_menu_button = QPushButton(self.tr('版の操作','Versions'))
        self.version_menu_button.setObjectName('versionMenu')
        self.version_menu_button.setMenu(self.version_menu)
        self.version_menu_button.setToolTip(self.tr('他の版への共有、宣言版の追加、試験出力','Share to other versions, add declared versions, test export'))
        version_row.addWidget(self.version_menu_button)
        version_row.addStretch()
        self.version_context_status = ElidedLabel()
        self.version_context_status.setObjectName('versionContextStatus')
        self.version_context_status.setTextFormat(Qt.PlainText)
        self.editor_content.layout().insertWidget(3, self.version_context_status)
        self.reopen_trial_report_action = QAction(self.tr('前回の試験出力結果', 'Last trial output result'), self)
        self.reopen_trial_report_action.setObjectName('reopenTrialOutputReport')
        self.reopen_trial_report_action.setEnabled(False)
        self.reopen_trial_report_action.triggered.connect(self.reopen_trial_output_report)
        self.version_selector.currentIndexChanged.connect(self.version_changed)
        self.model = EntryModel()
        self.proxy = EntryFilter()
        self.proxy.setSourceModel(self.model)
        self.proxy.setDynamicSortFilter(False)
        self.table.setModel(self.proxy)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        for col, width in enumerate([112, 200]):
            self.table.setColumnWidth(col, width)
        # Source and translation share the remaining width, so neither heading is cut off.
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.setColumnWidth(4, 36)
        self.autosave = QTimer(self)
        self.autosave.setSingleShot(True)
        self.autosave.setInterval(self.settings.data['autosave_seconds']*1000 or 60000)
        self.autosave.timeout.connect(self.auto_save)
        self.table.selectionModel().currentChanged.connect(self.select_entry)
        self.model.edited.connect(self.on_edit)
        self.model.dataChanged.connect(self.sync_detail)
        self.language_selector.currentIndexChanged.connect(self.language_changed)
        self.setup_tools()
        self.editor_scroll.viewport().installEventFilter(self)
        self.entry_tree.currentItemChanged.connect(self.tree_scope_changed)
        self.workspace_tabs.currentChanged.connect(self.set_workspace)
        self.empty_state = QWidget(self.table.viewport())
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setAlignment(Qt.AlignCenter)
        self.empty_title = QLabel()
        self.empty_title.setObjectName('h2')
        self.empty_title.setAlignment(Qt.AlignCenter)
        self.empty_hint = QLabel()
        self.empty_hint.setObjectName('muted')
        self.empty_hint.setAlignment(Qt.AlignCenter)
        self.empty_hint.setWordWrap(True)
        self.empty_action = QPushButton()
        empty_layout.addWidget(self.empty_title)
        empty_layout.addWidget(self.empty_hint)
        empty_layout.addWidget(self.empty_action,0,Qt.AlignCenter)
        self.empty_state.hide()
        self.table.viewport().installEventFilter(self)
        self.suggestions = []
        self.install_shortcuts()
        self.init_editor_panel()
        self.model.newly_translated.connect(self.bump_today)
        self.cheer_label = QLabel()
        self.cheer_label.setObjectName('done')
        self.cheer_label.setTextFormat(Qt.PlainText)
        self.cheer_label.hide()
        self.statusBar().addPermanentWidget(self.cheer_label)
        self.cheer_timer = QTimer(self)
        self.cheer_timer.setSingleShot(True)
        self.cheer_timer.setInterval(7000)
        self.cheer_timer.timeout.connect(self.clear_cheer)
        self.focus_mode = False
        self._focus_restore = ''
        self.set_tree_visible(self.settings.data['show_tree'],persist=False)
        self.apply_user_folders()
        self.update_finished.connect(self.show_update_result)
        self.refresh_counts()

    def start_autosave(self):
        """Arm the autosave timer unless the user turned autosave off in Preferences."""
        if self.settings.data['autosave_seconds']:
            self.autosave.start()

    def user_mod_roots(self):
        """The Workshop, Mods and added MOD folders (the user's where set, otherwise detected); read-only."""
        from .platforms import mod_roots
        return mod_roots(self.settings.data, self.discovered_games())

    def apply_user_folders(self):
        """Tell the write guard which of the user's folders are read-only MOD folders."""
        from .core import set_protected_folders
        data = self.settings.data
        set_protected_folders([data['workshop_folder'], *data['external_mod_folders']])

    def mods_config_file(self):
        """The ModsConfig.xml to read: the user's setting, else the native or Proton profile; None when none exists."""
        from .platforms import find_mods_config
        return find_mods_config(self.settings.data['mods_config_path'])

    def accept_source_folder(self, source):
        """True when ``source`` looks like a MOD; otherwise explains and returns False before anything is scanned."""
        from .platforms import is_mod_folder, mod_folders
        if is_mod_folder(source):
            return True
        inside = mod_folders([Path(source)])
        if inside:
            names = ', '.join(p.name for p in inside[:3]) + ('…' if len(inside)>3 else '')
            self.error(self.tr(f'これは MOD を集めたフォルダーです（{names} など）。翻訳したい MOD のフォルダーそのものを選んでください。',
                               f'This folder holds several MODs ({names}). Choose the folder of the one MOD to translate.'))
        else:
            self.error(self.tr('このフォルダーは MOD ではありません（About/About.xml も Defs・Languages もありません）。MOD のフォルダーを選んでください。',
                               'This folder is not a MOD: it has no About/About.xml and no Defs or Languages folder. Choose a MOD folder.'))
        return False

    def apply_project_defaults(self, project):
        """A new project starts with the translator name and license from Preferences, when set."""
        for key, setting in (('author','default_translator'),('license','default_license')):
            if self.settings.data[setting]:
                project.metadata.setdefault(key, self.settings.data[setting])

    def set_project_controls(self, active: bool):
        self.workspace_tabs.setEnabled(active)
        for button in (self.save_button, self.export_button, self.next_untranslated, self.focus_button,
                       self.save_side, self.rescan_side, self.manual_side,
                       self.warnings_side, self.git_side, self.output_side, self.manage_languages,
                       self.language_selector):
            button.setEnabled(active)
        for action in getattr(self,'project_tool_actions',[]):
            action.setEnabled(active)
        self.test_export_button.setEnabled(active and bool(self.project) and bool(self.project.version_profiles))
        self.reopen_trial_report_action.setEnabled(active and self.trial_output_report is not None)
        self.version_selector.setEnabled(active and self.version_selector.count() > 1)
        self.share_translation_button.setEnabled(active and self.version_selector.count() > 1)
        # About.xml may gain versions after every saved profile was scanned.
        self.scan_declared_button.setEnabled(active and bool(self.project))

    def error(self, text):
        if isinstance(text, Exception):
            text = self.error_text(text)
        box = QMessageBox(self)
        box.setWindowTitle(self.tr('処理できませんでした','Unable to complete the action'))
        box.setTextFormat(Qt.PlainText)
        box.setText(str(text))
        value = str(text)
        if any(token in value.lower() for token in ('permission','read-only','access','書き込み')):
            box.setInformativeText(self.tr('書き込み可能なプロジェクトフォルダーを選び、保存先の権限を確認してください。','Choose a writable project folder and check its permissions.'))
        elif 'placeholder' in value.lower() or 'プレースホルダー' in value:
            box.setInformativeText(self.tr('原文の {0} や名前付きトークンを訳にそのまま残してください。診断から該当項目へ移動できます。','Preserve source placeholders such as {0}. Open diagnostics to locate the entry.'))
        else:
            box.setInformativeText(self.tr('診断で元ファイルと該当項目を確認してください。保存済みデータは履歴から戻せます。','Check diagnostics for the source file and entry. Saved work can be restored from history.'))
        box.setIcon(QMessageBox.Warning)
        box.exec()

    def confirm_switch(self):
        if self.busy: return False
        if not self.dirty: return True
        answer = QMessageBox.question(self, '未保存の変更', '変更を保存しますか？', QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if answer == QMessageBox.Cancel: return False
        return self.save() if answer == QMessageBox.Save else True

    def new_project(self):
        if not self.confirm_switch(): return
        from .platforms import discover_installations
        workshop_roots = [p for p in self.user_mod_roots().all() if p.is_dir()]
        choices = [self.tr('Steam Workshopから選ぶ'),self.tr('PC内のフォルダーから選ぶ')]
        choice,ok = QInputDialog.getItem(self,self.tr('翻訳するMODを選ぶ'),self.tr('元MODをどこから読み込みますか？'),choices,0,False)
        if not ok:
            return
        if choice==choices[0]:
            source = select_workshop_mod(self,workshop_roots)
            if source is None:
                return
        else:
            folder = QFileDialog.getExistingDirectory(self,self.tr('元 MOD のフォルダーを選ぶ','Choose source MOD folder'),str(workshop_roots[0] if workshop_roots else Path.home()))
            if not folder:
                return
            source = Path(folder)
        if not self.accept_source_folder(source):
            return
        chosen_languages = select_languages(self, self.settings.data['default_languages'])
        if chosen_languages is None: return
        self.pending_languages = chosen_languages
        context = self.choose_scan_context(source)
        if context is None:
            return
        name = source.name
        about = source / 'About/About.xml'
        if about.is_file():
            try:
                name = safe_xml(about).findtext('name') or name
            except Exception:
                pass
        safe_name = re.sub(r'[^\w\- ]+', '', name, flags=re.UNICODE).strip().replace(' ', '-')[:52] or source.name
        base = Path.home() / 'Documents' / 'RimWorldTranslations'
        suffix = '-JP' if chosen_languages == ['Japanese'] else '-Translations'
        proposed = base / f'{safe_name}{suffix}'
        i = 2
        while proposed.exists():
            proposed = base / f'{safe_name}{suffix}-{i}'
            i += 1
        ask = QMessageBox(self)
        ask.setWindowTitle(self.tr('翻訳データの保存先', 'Where to save the translation data'))
        ask.setText(self.tr('翻訳プロジェクトを次の場所に作成します。', 'The translation project will be created here.'))
        ask.setInformativeText(str(proposed) + '\n\n' + self.tr('元MODは変更しません。', 'The source MOD is not modified.'))
        recommended = ask.addButton(self.tr('この場所で作成', 'Create here'), QMessageBox.AcceptRole)
        custom = ask.addButton(self.tr('別の場所を選ぶ', 'Choose another folder'), QMessageBox.ActionRole)
        ask.addButton(QMessageBox.Cancel)
        ask.exec()
        if ask.clickedButton() == recommended:
            workspace = proposed
        elif ask.clickedButton() == custom:
            folder = QFileDialog.getExistingDirectory(
                self, self.tr('翻訳プロジェクト用の空フォルダーを選ぶ', 'Choose an empty folder for the translation project'),
                str(base if base.is_dir() else Path.home())
            )
            if not folder: return
            workspace = Path(folder)
        else:
            return
        try:
            workspace = writable_destination(workspace, source)
            if workspace.exists():
                if any(workspace.iterdir()):
                    raise ValueError('保存先は空のフォルダーにしてください。')
            else:
                workspace.mkdir(parents=True, exist_ok=False)
        except Exception as exc:
            self.error(exc)
            return
        self.start_scan(source, workspace / 'project.json',context=context)

    def pick_workshop_mod(self, choices):
        """Show a searchable list and a large preview before choosing a mod."""
        from PySide6.QtWidgets import QDialogButtonBox, QVBoxLayout, QHBoxLayout
        dialog = QDialog(self)
        dialog.setWindowTitle('Steam WorkshopのMODを選ぶ')
        dialog.resize(780, 560)
        layout = QVBoxLayout(dialog)
        heading = QLabel('翻訳したいMODを選んでください。画像と名前で確認できます。')
        heading.setWordWrap(True)
        layout.addWidget(heading)
        query = QLineEdit()
        query.setPlaceholderText('MOD名やWorkshop IDで検索…')
        layout.addWidget(query)
        row = QHBoxLayout()
        listing = QListWidget()
        listing.addItems(list(choices))
        row.addWidget(listing, 3)
        thumbnail = QLabel('サムネイルなし')
        thumbnail.setFixedSize(240, 170)
        thumbnail.setAlignment(Qt.AlignCenter)
        thumbnail.setObjectName('modThumbnail')
        row.addWidget(thumbnail, 2)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('このMODを翻訳')
        buttons.button(QDialogButtonBox.Cancel).setText('キャンセル')
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        def update_thumb():
            selected = listing.currentItem()
            src = choices.get(selected.text()) if selected else None
            preview = find_source_preview(src) if src else None
            if preview:
                pix = QPixmap(str(preview))
                if not pix.isNull():
                    thumbnail.setPixmap(pix.scaled(230, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                    return
            thumbnail.setPixmap(QPixmap())
            thumbnail.setText('サムネイルなし')
        def filter_list(text):
            for idx in range(listing.count()):
                item = listing.item(idx)
                item.setHidden(text.casefold() not in item.text().casefold())
        query.textChanged.connect(filter_list)
        listing.currentItemChanged.connect(update_thumb)
        listing.itemDoubleClicked.connect(lambda _item: dialog.accept())
        if listing.count(): listing.setCurrentRow(0)
        if dialog.exec() != QDialog.Accepted or listing.currentItem() is None:
            return None
        return choices.get(listing.currentItem().text())

    def manage_languages_dialog(self):
        if not self.project or self.busy:
            return
        chosen = select_languages(self, self.project.languages)
        if chosen is None or chosen == self.project.languages:
            return
        if self.project.language not in chosen:
            self.project.switch_language(chosen[0])
        self.project.languages = chosen
        self.populate()
        self.on_edit()
        self.guidance.setText(f'翻訳対象: {len(chosen)} 言語。書き出すと選択中の言語だけが含まれます。')

    def language_changed(self, _index):
        if not self.project or self.busy:
            return
        language = self.language_selector.currentData()
        if not language or language == self.project.language:
            return
        self.project.switch_language(language)
        self.populate()
        self.on_edit()
        self.guidance.setText(f'翻訳先を {language} に切り替えました。ほかの言語の訳も保持しています。')

    def version_changed(self, _index):
        if not self.project or self.busy:
            return
        version = self.version_selector.currentData()
        if not version or version == self.project.game_version:
            return
        current = self.current.id if self.current else None
        self.edit_detail()
        self.project.switch_version(version)
        # Batch history stores entry IDs, which may recur in another version.
        self.undo_batches.clear()
        self.redo_batches.clear()
        self.populate()
        row = self.model.row_for_id.get(current)
        if row is not None:
            index = self.proxy.mapFromSource(self.model.index(row, 0))
            if index.isValid():
                self.table.setCurrentIndex(index)
                self.table.scrollTo(index)
        self.on_edit()
        self.guidance.setText(self.tr(f'編集する版を {version} に切り替えました。訳と承認は版ごとに保持しています。',
                                     f'Editing version {version}. Translations and approvals remain independent.'))

    def share_translation_dialog(self):
        if not self.project or not self.current or self.busy:
            return
        self.edit_detail()
        entry = self.current
        versions = self.project.translation_share_versions(entry.id)
        if not versions:
            QMessageBox.information(self, self.tr('訳の共有', 'Share translation'), self.tr(
                '同一キー・同一原文の未訳版がありません。既存訳や要確認項目は変更しません。',
                'No empty versions have the same key and source text. Existing translations and entries needing review are preserved.'))
            return
        dialog = QDialog(self)
        dialog.setObjectName('translationSharing')
        dialog.setWindowTitle(self.tr('共有する版を選択', 'Choose versions to share with'))
        layout = QVBoxLayout(dialog)
        details = QPlainTextEdit(self.tr(
            f'共有元: {self.project.game_version} / {self.project.language}\nキー: {entry.key}\n原文: {entry.english}\n訳文: {entry.japanese}\n\n選んだ版へ訳文だけをコピーします。承認・確認は各版で行ってください。',
            f'From: {self.project.game_version} / {self.project.language}\nKey: {entry.key}\nSource: {entry.english}\nTranslation: {entry.japanese}\n\nCopy text only to selected versions. Review and approve each version separately.'))
        details.setReadOnly(True)
        details.setMaximumHeight(220)
        layout.addWidget(details)
        choices = QListWidget()
        for version in versions:
            item = QListWidgetItem(version, choices)
            item.setData(Qt.UserRole, version)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
        layout.addWidget(choices)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        choices.itemChanged.connect(lambda _item: buttons.button(QDialogButtonBox.Ok).setEnabled(
            any(choices.item(i).checkState() == Qt.Checked for i in range(choices.count()))))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        selected = [choices.item(i).data(Qt.UserRole) for i in range(choices.count())
                    if choices.item(i).checkState() == Qt.Checked]
        try:
            self.project.share_translation(entry.id, selected)
        except ValueError as exc:
            self.error(exc)
            return
        self.on_edit()
        self.guidance.setText(self.tr(f'訳文を {", ".join(selected)} に共有しました。各版で確認してください。',
                                     f'Translation shared with {", ".join(selected)}. Review each version separately.'))

    def open_project(self):
        if not self.confirm_switch(): return
        name, _ = QFileDialog.getOpenFileName(self, '翻訳プロジェクトを開く', '', 'Translation project (project.json);;JSON (*.json)')
        if name: self.load_project(Path(name))

    def load_project(self, path):
        try:
            project = Project.load(path)
            writable_destination(path.parent, Path(project.source))
            self.autosave.stop()
            self.project, self.project_path, self.dirty = project, path, False
            self.undo_batches.clear()
            self.redo_batches.clear()
            self._cheer_armed = False
            self.clear_cheer()  # a note about the previous project does not belong to this one
            self.populate()
            if getattr(self,'_progress_animation',None) is not None:
                self._progress_animation.stop()
            self.progress.setValue(self._cheer_pct)  # a different project's progress, not a step forward: no slide
            try:
                self.settings.remember_project(path)
            except OSError:
                pass
            self.rebuild_menus()
            self.close_trial_output_report()
            self.statusBar().showMessage(self.tr('プロジェクトを開きました。翻訳を編集できます。','Project opened. You can edit translations.'), 8000)
        except Exception as exc: self.error(exc)

    def scan_declared_versions_dialog(self):
        if not self.project or self.busy:
            return
        answer = QMessageBox.question(self, self.tr('宣言版の走査', 'Scan declared versions'), self.tr(
            '元MODの全宣言版を順番に静的走査し、未走査版だけを追加します。既存版の訳と解析結果は保持します。\n'
            'ゲーム本体が見つからない版は、組み込みの項目表（RimWorldの型と項目名）で解析します。前提MOD・ゲーム動作は未検証です。XMLは出力しません。続けますか？',
            'Scan all declared versions sequentially and add only unscanned versions. Existing translations and scan results are preserved.\n'
            'Versions without a matching game installation use the built-in RimWorld field table; dependencies and game behavior remain unverified. No XML is exported. Continue?'),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer == QMessageBox.Yes:
            self.start_scan(Path(self.project.source), context={
                'game_version': self.project.game_version, 'active_mods': None}, declared_versions=True)

    def start_scan(self, source, new_path=None, context=None, declared_versions=False):
        if self.busy: return
        from .scan_context import default_context,validate_context
        if context is None:
            if self.project and new_path is None:
                context = {'game_version':self.project.game_version,
                           'active_mods':self.project.active_mods if self.project.active_mods_known or self.project.active_mods else None}
            else:
                from .platforms import discover_installations
                games = discover_installations(custom_paths=self.settings.data['game_paths'])
                context = default_context(source,games[0] if games else None,self.mods_config_file())
        context = validate_context(context['game_version'],context.get('active_mods'))
        self.busy = True
        self.autosave.stop()
        for button in self.actions: button.setEnabled(False)
        self.table.setEnabled(False)
        self.japanese.setReadOnly(True)
        self.statusBar().showMessage('XML を読み取り中…')
        self.pending_scan = (source, new_path)
        self.pending_declared_scan = declared_versions
        self.thread = QThread(self)
        cache_parent = new_path.parent if new_path else self.project_path.parent
        options = {'cache_path':cache_parent/'.cache/xml-index.sqlite',**context}
        worker_class = DeclaredVersionScanner if declared_versions else Scanner
        from .game_library import known_game_paths
        # Only scanners read library games; installing and live tests keep to the explicit game folders.
        self.worker = worker_class(source,options,self.settings.data['inspect_metadata'],known_game_paths(self.settings.data),
                                  self.settings.data)
        self.worker.progress.connect(self.scan_progress_changed,Qt.QueuedConnection)
        self.scan_progress.setRange(0,0)
        self.scan_progress.show()
        self.cancel_scan_button.setText(self.tr('スキャンを中止','Cancel scan'))
        self.cancel_scan_button.show()
        self.set_project_controls(False)
        self.guidance.setText(self.tr('元ファイルを読み込み中。中止しても現在の翻訳は保持します。','Scanning source files. Cancelling preserves current translations.'))
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit, Qt.DirectConnection)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.finished.connect(self.receive_scan, Qt.QueuedConnection)
        self.thread.start()

    def cancel_scan(self):
        if getattr(self,'game_worker',None) is not None:
            self.game_worker.cancel.set()
        elif self.busy and getattr(self,'worker',None) is not None:
            self.worker.cancel.set()
        self.statusBar().showMessage(self.tr('中止しています。現在のデータは保持します。','Cancelling. The current project will be preserved.'))

    @Slot(int,int,int,str)
    def scan_progress_changed(self,count,total,entries,source_file):
        self.scan_progress.setRange(0,total or 0)
        self.scan_progress.setValue(count)
        self.statusBar().showMessage(self.tr(f'スキャン {count}/{total} · 候補 {entries} · {source_file}',f'Scan {count}/{total} · {entries} candidates · {source_file}'))

    @Slot(object, str)
    def receive_scan(self, result, error):
        # The worker has completed; wait only for its event loop to exit.
        self.thread.wait()
        self.thread.deleteLater()
        # Cancellation remains valid until the GUI accepts the queued result.
        if self.worker.cancel.is_set():
            result, error = None, 'cancelled'
        source, new_path = self.pending_scan
        if self.pending_declared_scan:
            self.declared_scan_finished(result, error, review=True)
        else:
            self.scan_finished(source, new_path, result, error)

    def choose_declared_versions(self, result, available):
        """Approve individual successful additions without deciding Q17."""
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr('走査結果を取り込む', 'Import scan results'))
        layout = QVBoxLayout(dialog)
        label = QLabel(self.tr(
            '追加する版を選んでください。既存の訳・承認は保持します。\n'
            '未走査・失敗した版は未完了のままです。正式出力の条件は変わりません。',
            'Select versions to add. Existing translations and approvals are preserved.\n'
            'Failed/unscanned versions stay incomplete. Formal export rules do not change.'))
        label.setWordWrap(True)
        label.setTextFormat(Qt.PlainText)
        layout.addWidget(label)
        choices = QListWidget()
        choices.setObjectName('declaredVersionChoices')
        for version in available:
            item = QListWidgetItem(version)
            item.setData(Qt.UserRole, version)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            choices.addItem(item)
        layout.addWidget(choices)
        if result.failures:
            failures = QPlainTextEdit()
            failures.setReadOnly(True)
            failures.setPlainText('\n'.join(f'{v}: {message}' for v, message in result.failures.items()))
            failures.setMaximumHeight(120)
            layout.addWidget(failures)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.resize(480, 320)
        if dialog.exec() != QDialog.Accepted:
            return None
        return [choices.item(i).data(Qt.UserRole) for i in range(choices.count())
                if choices.item(i).checkState() == Qt.Checked]

    def declared_scan_finished(self, result, error, *, review=False, selected_versions=None):
        self.busy = False
        self.worker = None
        self.scan_progress.hide()
        self.cancel_scan_button.hide()
        for button in self.actions:
            button.setEnabled(True)
        self.table.setEnabled(True)
        self.japanese.setReadOnly(bool(self.current and entry_nonlocalizable_reason(self.current)))
        self.set_project_controls(bool(self.project))
        # A cancelled or rejected scan must not strand edits queued before it.
        if self.dirty:
            self.start_autosave()
        if error == 'cancelled':
            self.statusBar().showMessage(self.tr('走査を中止しました。現在の翻訳は保持しています。',
                                                'Scan cancelled. Current translations are preserved.'))
            return
        try:
            if error:
                raise ValueError(error)
            from .multiversion import VersionScans
            if not isinstance(result, VersionScans):
                raise ValueError('Invalid declared-version scan result')
            declared = set(result.declared_versions)
            if (not declared or any(not re.fullmatch(r'\d+\.\d+', v) for v in declared)
                    or not set(self.project.versions) <= declared):
                raise ValueError('Declared versions removed or invalid; existing history is preserved')
            if (set(result.scans) & set(result.failures)
                    or set(result.scans) | set(result.failures) != declared):
                raise ValueError('Scan results are incomplete or contradictory; existing project is preserved')
            for version, scan in result.scans.items():
                if (scan.package_id != self.project.original_package_id
                        or scan.stats.get('active_version') != version
                        or set(scan.versions) != declared):
                    raise ValueError('Scan source or version does not match the project')
            existing = set(self.project.version_profiles or {self.project.game_version: None})
            available = sorted(set(result.scans) - existing,
                               key=lambda v: tuple(map(int, v.split('.'))))
            needs_review = bool(result.failures or declared != set(self.project.versions))
            if selected_versions is None:
                if needs_review and review and available:
                    self.autosave.stop()
                    try:
                        selected_versions = self.choose_declared_versions(result, available)
                    finally:
                        if self.dirty:
                            self.start_autosave()
                    if selected_versions is None:
                        return
                elif needs_review:
                    raise ValueError('Partial results or new declarations require explicit import selection')
                else:
                    selected_versions = available
            if (not isinstance(selected_versions, list)
                    or any(not isinstance(v, str) for v in selected_versions)
                    or len(set(selected_versions)) != len(selected_versions)
                    or not set(selected_versions) <= set(available)):
                raise ValueError('Select only successful, unscanned versions')
            if not selected_versions:
                self.statusBar().showMessage(self.tr('追加する版はありません。現在の翻訳は保持しています。',
                                                     'No versions added. Current translations are preserved.'))
                return
            updated = copy.deepcopy(self.project)
            current_version = updated.game_version
            # Prefer the model's explicit extension API when a selected scan is
            # a new declaration. If only older successes were selected, retain
            # new declarations as unscanned; the trial exporter still blocks them.
            new_versions = [v for v in selected_versions if v not in updated.versions]
            if new_versions:
                first = new_versions[0]
                updated.add_version_scan(first, result.scans[first], extend_declared_versions=True)
            else:
                updated.versions = sorted(declared, key=lambda v: tuple(map(int, v.split('.'))))
            for version in selected_versions:
                if not new_versions or version != new_versions[0]:
                    updated.add_version_scan(version, result.scans[version])
            updated.switch_version(current_version)
        except (ValueError, OSError) as exc:
            self.error(str(exc))
            return
        self.project = updated
        self.dirty = True
        self.undo_batches.clear()
        self.redo_batches.clear()
        self.populate()
        self.on_edit()
        if not self.save(export=False):
            return
        self.set_project_controls(True)
        self.guidance.setText(self.tr('宣言版の走査結果を追加しました。追加版の前提MOD・型情報・ゲーム動作は未検証です。',
                                     'Declared version scans added. Dependencies, types and game behavior of added versions are unverified.'))

    def scan_finished(self, source, new_path, result, error):
        self.busy = False
        self.worker = None
        self.scan_progress.hide()
        self.cancel_scan_button.hide()
        for button in self.actions: button.setEnabled(True)
        self.table.setEnabled(True)
        self.japanese.setReadOnly(bool(self.current and entry_nonlocalizable_reason(self.current)))
        self.set_project_controls(bool(self.project))
        # Restore pending edits even when the scan is cancelled or rejected.
        if self.dirty:
            self.start_autosave()
        if error=='cancelled':
            self.statusBar().showMessage(self.tr('スキャンを中止しました。既存の翻訳はそのままです。','Scan cancelled. Existing translations are unchanged.'),8000)
            return
        if error:
            self.error(error)
            return
        migrated = 0
        if new_path:
            self.project = Project.create(source, result, getattr(self, 'pending_languages', ['Japanese']))
            self.apply_project_defaults(self.project)
            self.project_path = new_path
            self.close_trial_output_report()
        else:
            try:
                migrated = self.project.rescan(result)
            except ValueError as exc:
                self.error(str(exc))
                return
            self.project.game_version = result.stats.get('active_version',self.project.game_version)
            self.project.active_mods = result.stats.get('active_mods') or []
            self.project.active_mods_known = result.stats.get('active_mods') is not None
        self.undo_batches.clear()
        self.redo_batches.clear()
        self.dirty = True
        self.populate()
        self.on_edit()
        # Immediate installable skeleton, including zero translated entries.
        if new_path:
            if not self.generate():
                return
        else:
            if not self.save():
                return
        message = f'スキャン完了: {len(result.entries)} 件 / 警告 {len(result.warnings)} 件'
        if migrated:
            message += self.tr(f' / {migrated} 件のキーを公式訳と同じ名前方式に移行しました',
                               f' / {migrated} keys moved to the handle names the game uses')
        self.statusBar().showMessage(message, 10000)

    def rescan(self):
        if self.project and not self.busy: self.start_scan(Path(self.project.source))

    def populate(self):
        try:
            self._populate()
        finally:
            self.refilter_hold = False

    def _populate(self):
        self.current = None
        self._prerequisite_translations = None  # looked up again once per scan or opened project
        profile = self.project.version_profiles.get(self.project.game_version, {})
        coverage = profile.get('coverage', {})
        context = (self.tr(f'{len(self.project.active_mods)}件', f'{len(self.project.active_mods)} selected')
                   if self.project.active_mods_known else self.tr('未指定', 'unspecified'))
        source_status = (self.tr('原文検証記録あり', 'Source verification recorded')
                         if coverage.get('source_verified') else self.tr('原文未検証', 'Source unverified'))
        game_status = (self.tr('ゲーム検証記録あり', 'Game verification recorded')
                       if coverage.get('game_tested') else self.tr('ゲーム未検証', 'Game unverified'))
        self.version_context_status.setText(self.tr(
            f'{self.project.game_version} · 前提構成: {context} · {source_status} · {game_status}',
            f'{self.project.game_version} · Dependency context: {context} · {source_status} · {game_status}'))
        dependencies = (', '.join(self.project.active_mods) or self.tr('なし（明示指定）', 'none (explicitly selected)')
                        if self.project.active_mods_known else self.tr('未指定（依存条件を未検証）', 'unspecified (dependency conditions unverified)'))
        self.version_context_status.setToolTip(self.tr(
            f'この版の前提構成: {dependencies}\n走査済みでも抽出の完全性やゲーム対応を保証しません。',
            f'Dependency context for this version: {dependencies}\nA completed scan does not guarantee complete extraction or game compatibility.'))
        self.version_selector.blockSignals(True)
        self.version_selector.clear()
        versions = self.project.version_profiles or {self.project.game_version: None}
        for version in sorted(versions, key=lambda value: tuple(int(part) for part in value.split('.'))):
            self.version_selector.addItem(version, version)
        self.version_selector.setCurrentIndex(self.version_selector.findData(self.project.game_version))
        self.version_selector.blockSignals(False)
        self.model.project = self.project
        self.model.ui_language = self.ui_language
        self.model.replace(self.project.entries)
        self.refilter_hold = True  # filter parameters change several times while opening; filter the rows once at the end
        self.refresh_filter_options()
        self.filter_changed()
        output_folder = shown_output(self.project_path, self.project)
        self.location.setText(self.tr(f'{self.project.name}  ·  出力先: {output_folder}',f'{self.project.name} · Output: {output_folder}'))
        self.location.setToolTip(self.tr(f'元MOD: {self.project.source}\n編集データ: {self.project_path}',
                                         f'Source MOD: {self.project.source}\nWorking data: {self.project_path}'))
        self.sidebar_project.setText(self.project.name)
        self.sidebar_project.setToolTip(str(self.project_path))
        thumbnail = find_source_preview(Path(self.project.source))
        if thumbnail:
            pix = QPixmap(str(thumbnail))
            if not pix.isNull():
                self.mod_thumbnail.setPixmap(pix.scaled(105, 62, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.mod_thumbnail.setPixmap(QPixmap())
                self.mod_thumbnail.setText('MOD')
        else:
            self.mod_thumbnail.setPixmap(QPixmap())
            self.mod_thumbnail.setText('MOD')
        available = discover_languages()
        self.language_selector.blockSignals(True)
        self.language_selector.clear()
        for code in self.project.languages:
            label = available.get(code, code)
            self.language_selector.addItem(flag_icon(code), label, code)
        self.language_selector.setCurrentIndex(self.language_selector.findData(self.project.language))
        self.language_selector.blockSignals(False)
        localized_language = LANGUAGES[self.project.language][0].split('  (')[0]
        self.model.headers = [self.tr('状態','State'),self.tr('キー','Key'),self.tr('英語','English'),self.tr(f'{localized_language}訳',f'Translation / {self.project.language}')]
        self.model.headerDataChanged.emit(Qt.Horizontal, 3, 3)
        self.translation_label.setText(self.tr(f'翻訳  /  {localized_language} をここに入力',f'Translation / {self.project.language}'))
        self.setWindowTitle(f'{self.project.name} | ' + self.tr('RimWorld 翻訳ワークスペース', 'RimWorld Translation Workspace'))
        self.views.setCurrentWidget(self.editor_page)
        self.set_project_controls(True)
        self.english.clear()
        self.japanese.clear()
        self.rebuild_tree()
        self.refilter_hold = False
        self.refilter()
        self.refresh_counts()
        if self.proxy.rowCount(): self.table.setCurrentIndex(self.proxy.index(0, 0))

    # ---- workspace tabs, focus mode, progress and export pages ----
    def show_suggestions(self,entry,unsafe):
        """Earlier translations of exactly the same English, then official ones, offered in the empty translation box (Ctrl+Shift+1..3)."""
        self.suggestions = []
        placeholder = self.tr('ここに日本語訳を書いてください…','Write the translation here…')
        if self.project and not unsafe and not entry.japanese.strip():
            try:
                found = translation_memory(self.project,entry.id,self.project.language)
            except ValueError:
                found = []
            own = [item.translation for item in found[:3]]
            own += [text for text in self.suggestion_sources(entry)[1] if text not in own]
            official = [text for text in self.official_suggestions(entry) if text not in own]
            self.suggestions = (own+official)[:3]
            short = lambda text:text if len(text)<=24 else text[:23]+'…'
            listed = lambda texts,start:'   '.join(f'[{number}] {short(text)}' for number,text in enumerate(texts,start))
            own_shown,official_shown = self.suggestions[:len(own)],self.suggestions[len(own):]
            if own_shown:
                placeholder += '\n'+self.tr(f'同じ原文の訳: {listed(own_shown,1)}',f'Same source elsewhere: {listed(own_shown,1)}')
            if official_shown:
                text = listed(official_shown,len(own_shown)+1)
                placeholder += '\n'+self.tr(f'公式訳: {text}',f'Official translation: {text}')
            if self.suggestions:
                placeholder += '   '+self.tr('(Ctrl+Shift+数字で挿入)','(insert with Ctrl+Shift+number)')
        self.japanese.setPlaceholderText(placeholder)

    def official_suggestions(self,entry):
        """Translations from the installed game's own language packs; read-only, never applied automatically."""
        from .official_translations import official_index
        language = self.project.language
        if getattr(self,'_official',(None,None))[0]!=language:
            from .platforms import discover_installations
            try:
                games = discover_installations(custom_paths=self.settings.data['game_paths'])
                index = official_index(games[0].root if games else None,language)
            except (OSError,ValueError,tarfile.TarError):
                index = official_index(None,language)
            self._official = (language,index)
        return self._official[1].suggest(entry)

    def insert_suggestion(self,number):
        if self.current and not self.japanese.isReadOnly() and number<len(getattr(self,'suggestions',[])):
            self.japanese.setPlainText(self.suggestions[number])
            self.japanese.setFocus()

    def clear_filters(self):
        self.search.clear()
        self.status_filter.setCurrentIndex(0)
        if hasattr(self,'source_filter'):
            self.source_filter.clear()
        self.reset_extra_filters()
        select_tree_root = self.entry_tree.topLevelItem(0)
        if select_tree_root is not None:
            self.entry_tree.setCurrentItem(select_tree_root)
        self.filter_changed()

    def update_empty_state(self):
        """A table with no rows says why, and offers the one useful next step (GNOME/KDE placeholder pattern)."""
        state = getattr(self,'empty_state',None)
        if state is None:
            return
        if not self.project or self.proxy.rowCount()>0:
            state.hide()
            return
        filtered = bool(self.search.text() or self.status_filter.currentData() or self.proxy.scope or self.proxy.source_file or self.extra_filters_active())
        action = None
        if self.focus_mode:
            title,hint = self.tr('未訳はゼロ','Nothing left to translate'),self.tr('ここまで全部訳した。保存して書き出そう。','Everything is translated. Save and export.')
            action = (self.tr('集中モードを終了','Leave focus mode'),lambda:self.set_focus_mode(False))
        elif self.proxy.attention:
            title,hint = self.tr('確認が必要な項目はありません','Nothing needs review'),self.tr('原文が変わった項目や、要確認の項目はありません。','No changed or flagged entries.')
        elif filtered:
            title,hint = self.tr('条件に合う項目がありません','No entries match'),self.tr('検索語や絞り込みを変えてみてください。','Try a different search or filter.')
            action = (self.tr('絞り込みを解除','Clear filters'),self.clear_filters)
        else:
            title,hint = self.tr('翻訳できる項目が見つかりませんでした','No translatable entries were found'),self.tr('「抽出できなかった項目」から、手動で追加できます。','You can add keys by hand from the sidebar.')
        self.empty_title.setText(title)
        self.empty_hint.setText(hint)
        handler = getattr(self,'_empty_handler',None)
        if handler is not None:
            self.empty_action.clicked.disconnect(handler)
            self._empty_handler = None
        self.empty_action.setVisible(action is not None)
        if action:
            self.empty_action.setText(action[0])
            self._empty_handler = lambda _checked=False,f=action[1]:f()
            self.empty_action.clicked.connect(self._empty_handler)
        state.setGeometry(self.table.viewport().rect())
        state.show()
        state.raise_()

    def set_workspace(self,index):
        if self.focus_mode and index!=0:
            self.set_focus_mode(False)
        self.translate_page.setVisible(index in (0,1))
        self.progress_page.setVisible(index==2)
        self.export_page.setVisible(index==3)
        self.proxy.attention = index==1
        self.refilter()
        if self.project:
            self.refresh_counts()
        if index==1 and self.proxy.rowCount():
            self.table.setCurrentIndex(self.proxy.index(0,0))
        if index==2:
            self.refresh_progress_page()
        if index==3:
            self.refresh_export_page()

    def bump_today(self):
        counts = self.settings.data['daily_counts']
        today = date.today().isoformat()
        counts[today] = counts.get(today,0)+1
        for old in sorted(counts)[:-30]:
            del counts[old]
        self._cheer_armed = True
        self.show_cheer(daily_cheer(counts[today],self.ui_language=='en'))

    def glide_progress(self,percentage):
        """Slide the sidebar bar to its new value (a short ease), so a translation visibly moves it.

        Skipped while the window is hidden or the user asked for less motion: the bar then jumps."""
        animation = getattr(self,'_progress_animation',None)
        if animation is None:
            animation = self._progress_animation = QPropertyAnimation(self.progress,b'value',self)
            animation.setDuration(260)
            animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.stop()
        if not self.isVisible() or self.settings.data['reduce_motion'] or abs(self.progress.value()-percentage)<1:
            self.progress.setValue(percentage)
            return
        animation.setStartValue(self.progress.value())
        animation.setEndValue(percentage)
        animation.start()

    def show_cheer(self,text):
        """A short note beside the status message; it fades by itself and never needs a click."""
        if not text:
            return
        self.cheer_label.setText(text)
        self.cheer_label.show()
        self.cheer_timer.start()

    def clear_cheer(self):
        self.cheer_timer.stop()
        self.cheer_label.setText('')
        self.cheer_label.hide()

    def set_reduce_motion(self,reduce):
        self.settings.data['reduce_motion'] = bool(reduce)
        if hasattr(self,'reduce_motion_action'):
            self.reduce_motion_action.setChecked(bool(reduce))
        self.save_preferences()

    def refresh_progress_page(self):
        if not self.project:
            return
        rows,remaining,total = group_stats(self.model.entries)
        done = total-remaining
        self.progress_big.setText(f'{round(100*done/total) if total else 0}%')
        self.progress_summary.setText(self.tr(
            f'翻訳済み {done} / {total} 項目  ·  残り {remaining} 項目 ({self.project.language})',
            f'{done} of {total} translated  ·  {remaining} left ({self.project.language})'))
        from .progress import progress as project_progress
        detail = project_progress(self.project,self.project.language)
        self.progress_summary.setText(self.progress_summary.text()+'\n'+self.tr(
            f'名前・説明 {detail.p0_translated} / {detail.p0_total} ({detail.p0_percent:g}%)  ·  確認済み {detail.reviewed}  ·  承認済み {detail.approved}  ·  要確認 {detail.needs_review}',
            f'Names and descriptions {detail.p0_translated} / {detail.p0_total} ({detail.p0_percent:g}%)  ·  reviewed {detail.reviewed}  ·  approved {detail.approved}  ·  needs review {detail.needs_review}'))
        today = self.settings.data['daily_counts'].get(date.today().isoformat(),0)
        almost = [row for row in rows if 0<row[2]]
        nearest = min(almost,key=lambda row:(row[2],row[1])) if almost else None
        goal = ''
        if nearest and nearest[2]<=max(10,nearest[3]//4):
            goal = self.tr(f'  ·  あと {nearest[2]} 件で {nearest[1]} が完了',f'  ·  {nearest[2]} more to finish {nearest[1]}')
        self.progress_today.setText(today_line(today,self.ui_language=='en')+goal)
        layout = self.progress_rows
        while layout.count()>1:
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for kind,group,left,count in rows:
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0,0,0,0)
            name = QLabel(f'{group}  ({kind_name(kind,self.ui_language=="en")})')
            name.setToolTip(kind)
            name.setMinimumWidth(260)
            bar = QProgressBar()
            bar.setRange(0,max(1,count))
            bar.setValue(count-left)
            bar.setFormat(f'{count-left} / {count}')
            # Thin bar; the numbers sit beside it, since text on a filled bar is hard to read.
            bar.setTextVisible(False)
            bar.setFixedHeight(8)
            done_text = f'{count-left} / {count}'
            note = QLabel(done_text + '   ' + self.tr('完了' if left==0 else f'残り {left}','done' if left==0 else f'{left} left'))
            note.setObjectName('muted' if left else 'done')
            note.setMinimumWidth(130)
            line.setSpacing(16)
            line.addWidget(name)
            line.addWidget(bar,1)
            line.addWidget(note)
            layout.insertWidget(layout.count()-1,row)

    def refresh_export_page(self):
        if not self.project:
            return
        issues = qa_project(self.project)
        errors = sum(1 for issue in issues if issue.severity=='error')
        warnings = len(issues)-errors
        state = self.tr('未保存の変更があります。' if self.dirty else '保存済みです。','Unsaved changes.' if self.dirty else 'Saved.')
        verdict = self.tr('書き出しをブロックするエラーはありません。' if not errors else f'エラー {errors} 件を直すまで、書き出しは止まります。',
                          'Nothing blocks export.' if not errors else f'{errors} error(s) block export until fixed.')
        self.export_summary.setText(self.tr(f'{state}  QA: エラー {errors} 件 / 警告 {warnings} 件。{verdict}',f'{state}  QA: {errors} error(s), {warnings} warning(s). {verdict}'))

    def set_focus_mode(self,on):
        on = bool(on) and self.project is not None
        if on==self.focus_mode:
            return
        self.focus_mode = on
        if on:
            self.workspace_tabs.setCurrentIndex(0)
            self._focus_restore = self.status_filter.currentData() or ''
            index = self.status_filter.findData('untranslated')
            if index>=0:
                self.status_filter.setCurrentIndex(index)
        for widget in (self.table_splitter,self.chip_bar,self.filter_bar,self.search,self.status_filter,self.next_untranslated,self.focus_button):
            widget.setVisible(not on)
        if hasattr(self,'source_filter'):
            self.source_filter.setVisible(not on)
        self.focus_bar.setVisible(on)
        if not on:
            index = self.status_filter.findData(self._focus_restore)
            self.status_filter.setCurrentIndex(max(0,index))
        self.filter_changed()
        if on:
            if self.proxy.rowCount():
                self.table.setCurrentIndex(self.proxy.index(0,0))
            self.japanese.setFocus()
            self.update_focus_label()

    def update_focus_label(self):
        if not self.focus_mode:
            return
        left = self.proxy.rowCount()
        key = self.current.key if self.current else ''
        self.focus_label.setText(self.tr(f'未訳 残り {left} 件  ·  {key}',f'{left} left  ·  {key}'))

    def step_entry(self,delta):
        """Move to the next or previous entry of the current list without leaving the keyboard."""
        count = self.proxy.rowCount()
        if not count:
            return
        row = self.table.currentIndex().row() if self.table.currentIndex().isValid() else 0
        self.table.setCurrentIndex(self.proxy.index(max(0,min(count-1,row+delta)),0))
        self.japanese.setFocus()

    def focus_step(self,delta):
        self.step_entry(delta)
        self.update_focus_label()

    def install_shortcuts(self):
        from PySide6.QtGui import QShortcut
        self._shortcuts = []
        def bind(keys,callback):
            shortcut = QShortcut(QKeySequence(keys),self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)
        for number in range(4):
            bind(f'Ctrl+{number+1}',lambda n=number:self.workspace_tabs.isEnabled() and self.workspace_tabs.setCurrentIndex(n))
        bind('Alt+Down',lambda:self.step_entry(1))
        bind('Alt+Up',lambda:self.step_entry(-1))
        bind('Ctrl+L',lambda:(self.search.setFocus(),self.search.selectAll()))
        bind('F3',lambda:self.project and select_untranslated(self))
        bind('F1',self.shortcut_help)
        for number in range(3):
            bind(f'Ctrl+Shift+{number+1}',lambda n=number:self.insert_suggestion(n))

    def shortcut_help(self):
        rows = (('Ctrl+S','保存して書き出す','Save and export'),('Ctrl+Return','確認済みにする(集中モードでは次の未訳へ)','Mark reviewed (next untranslated in focus mode)'),
                ('Alt+↓ / Alt+↑','次の項目 / 前の項目','Next / previous entry'),('F3','次の未訳へ','Next untranslated'),
                ('Ctrl+Shift+F','集中モード(Esc で終了)','Focus mode (Esc to leave)'),('Ctrl+L','検索欄へ移動','Go to search'),
                ('Ctrl+1 〜 4','翻訳 / 確認 / 進捗 / 書き出し のタブ','Translate / Review / Progress / Export tabs'),
                ('Ctrl+Shift+1〜3','同じ原文の過去の訳・公式訳を挿入','Insert an earlier or official translation of the same source'),('Ctrl+T','分類ツリーの表示切り替え','Toggle classification tree'),('Ctrl+Shift+D','ライト / ダークの切り替え','Toggle light/dark'),
                ('Ctrl+J / Ctrl+Shift+J','次の未訳 / 次の要確認へ(絞り込みはそのまま)','Next untranslated / next needs-review (filters unchanged)'),
                ('Ctrl+Shift+Enter','確認済みにして次の未訳・要確認へ','Mark reviewed and go to the next row needing work'),('Ctrl+K','「後で見直す」の印を付ける / 外す','Toggle the "review later" flag'),
                ('Ctrl+Z / Ctrl+Y','入力中の取り消し / やり直し','Undo / redo while typing'),('F1','この一覧','This list'))
        body = '\n'.join(f'{keys:<16}{self.tr(jp,en)}' for keys,jp,en in rows)
        self.info_dialog(self.tr('キーボードショートカット','Keyboard shortcuts'),body)

    def focus_advance(self):
        """After an entry is confirmed: the untranslated list shrank, so the next one is at the top."""
        if self.proxy.rowCount():
            self.table.setCurrentIndex(self.proxy.index(0,0))
            self.japanese.setFocus()
        self.update_focus_label()

    def rebuild_tree(self):
        if self.project is None:
            return
        build_tree(self.entry_tree,self.model.entries,self.tr('すべて','All'))
        self.proxy.scope = current_scope(self.entry_tree) if self.entry_tree.isVisible() or not self.entry_tree.isHidden() else ()
        self.refilter()

    def refilter(self):
        """Run the row filter now, or once when the surrounding batch of changes ends."""
        if getattr(self, 'refilter_hold', False):
            return
        self.proxy.invalidate()

    def tree_scope_changed(self,*_):
        self.proxy.scope = current_scope(self.entry_tree)
        self.refilter()
        if getattr(self, 'refilter_hold', False):
            return
        self.refresh_counts()
        if self.proxy.rowCount():
            self.table.setCurrentIndex(self.proxy.index(0,0))
        else:
            self.current = None
            self.sync_detail()

    def schedule_tree_counts(self):
        timer = getattr(self,'_tree_timer',None)
        if timer is None:
            timer = self._tree_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(500)
            timer.timeout.connect(lambda:refresh_tree_counts(self.entry_tree,self.model.entries))
        timer.start()

    def set_tree_visible(self,visible,persist=True):
        self.settings.data['show_tree'] = bool(visible)
        self.entry_tree.setVisible(bool(visible))
        self.proxy.scope = current_scope(self.entry_tree) if visible else ()
        self.refilter()
        if hasattr(self,'tree_action'):
            self.tree_action.setChecked(bool(visible))
        if self.project:
            self.refresh_counts()
        if persist:
            self.save_preferences()

    LARGE_PROJECT_ROWS = 5000

    def search_typed(self, *_):
        """Typing in the search box: filter now, or once typing pauses when a large project makes each pass noticeable."""
        if len(self.model.entries) <= self.LARGE_PROJECT_ROWS:
            self.filter_changed()
            return
        timer = getattr(self, '_search_timer', None)
        if timer is None:
            timer = self._search_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(200)
            timer.timeout.connect(self.filter_changed)
        timer.start()

    def filter_changed(self, *_):
        timer = getattr(self, '_search_timer', None)
        if timer is not None:
            timer.stop()
        self.proxy.query = self.search.text().casefold()
        self.proxy.status = self.status_filter.currentData()
        self.proxy.source_file = self.source_filter.text().casefold() if hasattr(self,'source_filter') else ''
        self.sync_extra_filters()
        self.refilter()
        if not getattr(self, 'refilter_hold', False):
            # A filter changes what is shown, not the project totals, so the 50k-row totals pass is skipped.
            self.refresh_view_counts()

    def refresh_counts(self):
        counts = Counter(e.status for e in self.model.entries)
        eligible = [e for e in self.model.entries if not e.blocked and not e.stale and not e.excluded and not entry_nonlocalizable_reason(e)]
        translated = sum(bool(e.japanese.strip()) for e in eligible)
        total = len(eligible)
        percentage = round(100 * translated / total) if total else 0
        if translated < total:
            percentage = min(percentage, 99)  # 199 of 200 rounds to 100; only a finished project shows it
        self.glide_progress(percentage)
        before,self._cheer_pct = self._cheer_pct,percentage
        if self._cheer_armed:  # only a translation the user just made earns a note, not a rescan or a filter change
            self._cheer_armed = False
            self.show_cheer(progress_cheer(before,percentage,self.ui_language=='en'))
        self.progress_text.setText(self.tr(f'{translated} / {total} 項目を翻訳済み ({self.project.language if self.project else "Japanese"})',f'{translated} / {total} translated ({self.project.language if self.project else "Japanese"})'))
        self.refresh_p0(eligible)
        for key, chip in self.status_chips.items():
            label = ui_text(chip.property('chipLabel'), self.ui_language)
            chip.setText(f'{label}  {counts[key] if key else len(self.model.entries)}')
        self.refresh_view_counts()

    def refresh_view_counts(self):
        """The parts of the counters that depend on the active filter only."""
        self.counts.setText(self.tr(f'表示 {self.proxy.rowCount()} / 全 {len(self.model.entries)}',
                                    f'Showing {self.proxy.rowCount()} of {len(self.model.entries)}'))
        self.clear_filters_button.setVisible(bool(
            self.search.text() or self.status_filter.currentData() or self.proxy.scope or self.proxy.source_file or self.extra_filters_active()))
        self.update_empty_state()

    def select_entry(self, index, _previous=QModelIndex()):
        mapped = self.proxy.mapToSource(index)
        self.current = self.model.entries[mapped.row()] if mapped.isValid() else None
        self.sync_detail()

    def sync_detail(self, *_):
        if not self.current:
            self.english.clear()
            self.japanese.blockSignals(True)
            self.japanese.clear()
            self.japanese.blockSignals(False)
            self.key_label.setText('項目を選択してください')
            self.notice.clear()
            self.notice_details.clear()
            self.notice_toggle.setVisible(False)
            self.notice_details.setVisible(False)
            self.sync_panel()
            return
        entry = self.current
        self.key_label.setText(f'{entry.kind}/{entry.group} : {entry.key}   [{ui_text(STATUS[entry.status], self.ui_language)}]  ·  {entry.source_file}')
        self.english.setPlainText(entry.english)
        unsafe_reason = entry_nonlocalizable_reason(entry)
        self.japanese.setReadOnly(self.busy or bool(unsafe_reason))
        self.show_suggestions(entry,bool(unsafe_reason))
        if self.japanese.toPlainText() != entry.japanese:
            self.japanese.blockSignals(True)
            self.japanese.setPlainText(entry.japanese)
            self.japanese.blockSignals(False)
        # What the translator needs is plain; how the entry was found goes in the folded technical details.
        notices = [placeholder_warning(entry)]
        details = [f'confidence: {entry.confidence}',*reason_lines(entry,self.tr),*entry.evidence]
        if entry.confidence=='heuristic' and not entry.classification:
            notices.append(self.tr('ゲームのデータ定義で確認できていない項目です。訳した文章がゲームで表示されるか確かめてください。',
                                   'Not confirmed against the game data. Check that the translated text really appears in game.'))
        prefix = grammar_rule_prefix(entry)
        if prefix:
            notices.append(self.tr(f'「{prefix}」は変更せず、右側のみ翻訳してください。',
                                   f'Keep “{prefix}” unchanged; translate only the right-hand side.'))
        if unsafe_reason:
            notices.append(self.tr('ゲームの内部データなので、編集も出力もできません。保存済みの訳は残ります。',
                                   'Internal game data cannot be edited or exported. Saved translations are kept.'))
            details.append(unsafe_reason)
        errors = [issue for issue in qa_entry(entry, glossary=self.project.glossary) if issue.severity == 'error']
        if errors:
            notices.append(self.tr('QA エラー: 試験出力から除外され、正式出力は拒否されます。',
                                   'QA error: omitted from trial output; formal output is blocked.'))
            notices.extend(issue.message for issue in errors)
        if entry.excluded:
            notices.append(self.tr('手動で除外中。この項目は出力されません。','Manually excluded from exports.'))
        if entry.previous_english: notices.append(self.tr('変更前: ', 'Before the change: ') + entry.previous_english)
        if entry.blocked: notices.append(self.tr('重複キー: 出力対象外。元の重複・バージョン構成を確認してください。',
                                   'Duplicate key: not exported. Check the duplicate or version layout in the source.'))
        if entry.stale: notices.append(self.tr('元から削除された項目: 訳は保持しますが出力対象外です。',
                                   'Removed from the source: the translation is kept but not exported.'))
        self.notice.setPlainText('\n'.join(n for n in notices if n))
        details = [line for line in details if line]
        self.notice_details.setPlainText('\n'.join(details))
        self.notice_toggle.setVisible(bool(details))
        self.notice_details.setVisible(bool(details) and self.notice_toggle.isChecked())
        self.sync_panel()

    def edit_detail(self):
        if not self.current or self.busy: return
        row = self.model.row_for_id[self.current.id]
        self.model.setData(self.model.index(row, 3), self.japanese.toPlainText())

    def schedule_counts(self):
        """Recount at once for ordinary projects; coalesce keystrokes when a recount costs tens of milliseconds."""
        if len(self.model.entries) <= 5000:
            self.refresh_counts()
            return
        timer = getattr(self, '_counts_timer', None)
        if timer is None:
            timer = self._counts_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(200)
            timer.timeout.connect(self.refresh_counts)
        timer.start()

    def on_edit(self):
        self.dirty = True
        self.start_autosave()
        self.schedule_counts()
        self.schedule_tree_counts()
        self.sync_detail()
        if self.project and self.project.version_profiles:
            self.guidance.setText(self.tr(
                '未保存の変更があります。保存後、「翻訳MODを書き出す」で準備できた版を正式出力、「宣言版を試験出力」で試験出力できます。',
                'Unsaved changes. Save, then use Export translation MOD (ready versions) or trial export.'))
        else:
            self.guidance.setText(self.tr('未保存の変更があります。保存するとゲーム用 XML も自動更新します。','Unsaved changes. Saving also updates the game XML.'))
        self.statusBar().showMessage('未保存の変更  ·  編集を止めて60秒後に自動保存します。')

    def mark_reviewed(self,approved=False):
        """Mark the current row reviewed; returns True when it was. A refusal is shown beside the editor and as a message."""
        if not self.current or self.busy: return False
        if entry_nonlocalizable_reason(self.current):
            message = self.tr('内部データは承認しても編集・出力できません。',
                              'Internal data cannot be edited or exported, even if approved.')
            self.show_review_message(message)
            self.error(message)
            return False
        if self.current.blocked or self.current.stale:
            message = self.tr('重複または旧項目は確認済みにしても出力できません。','Duplicate or removed rows cannot be exported even when reviewed.')
            self.show_review_message(message)
            self.error(message)
            return False
        try:
            self.project.mark_reviewed(self.current.id,approved=approved)
        except ValueError as exc:
            self.show_review_message(exc)
            self.error(exc)
            return False
        self.sync_detail()
        row = self.model.row_for_id[self.current.id]
        self.model.dataChanged.emit(self.model.index(row,0),self.model.index(row,3))
        self.on_edit()
        self.filter_changed()
        if self.focus_mode:
            self.focus_advance()
        return True

    def save(self,*_checked,export=True):
        if not self.project or self.busy: return False
        try:
            self.project.save(self.project_path)
            self.dirty = False
            self.autosave.stop()
        except Exception as exc:
            self.error(exc)
            return False
        self.remember_translations()
        if self.settings.data['recent_projects'][:1]!=[str(self.project_path.resolve())]:
            try:
                self.settings.remember_project(self.project_path)
                self.rebuild_menus()
            except OSError:
                # Preference errors must not prevent saving translation work.
                pass
        try:
            self.last_export_error = ''
            if export and not self.project.version_profiles:
                try:
                    export_mod(self.project,self.output_folder())
                except (ValueError,OSError) as exc:
                    self.last_export_error = self.error_text(exc)
            made = snapshot(self.project_path, keep=self.settings.data['backup_generations'] or None)
            if self.last_export_error:
                self.guidance.setText(self.tr('作業データは保存済み。XML 更新には診断の修正が必要です: ','Project saved. Fix diagnostics before updating game XML: ')+self.last_export_error)
            elif not export:
                self.guidance.setText(self.tr('作業データは保存済み。ゲーム用 XML は更新していません。','Project saved. Game XML was not updated.'))
            elif self.project.version_profiles:
                self.guidance.setText(self.tr(
                    '作業データは保存済み。「翻訳MODを書き出す」で準備できた版を正式出力、「宣言版を試験出力」で全宣言版を試験出力できます。',
                    'Project saved. Use Export translation MOD for ready versions, or trial export for all declared versions.'))
            else:
                self.guidance.setText(self.tr('保存済み。ゲーム用 XML も更新しました。','Saved. Game XML is also up to date.'))
            self.statusBar().showMessage('保存済み  ·  ' + ('Gitにもバックアップ済み' if made else 'Git差分なし'), 8000)
        except Exception as exc:
            self.error(f'JSON は保存済みですが Git 記録に失敗しました: {exc}')
        self.filter_changed()
        return True

    def auto_save(self):
        if self.dirty and not self.busy and not self.save():
            self.guidance.setText(self.tr(
                '自動保存に失敗しました。未保存の変更を保持しています。保存先を確認し、「保存」で再試行してください。',
                'Autosave failed. Unsaved changes are preserved. Check the destination and use Save to retry.'))
            self.statusBar().showMessage(self.tr(
                '未保存の変更があります。保存先を確認し、保存を再試行してください。',
                'Unsaved changes. Check the destination and retry saving.'))

    def checkpoint(self):
        self.save()

    def open_export_folder(self):
        if not self.project_path:
            return
        if not self.project:
            return
        output = shown_output(self.project_path, self.project)
        if not output.is_dir():
            self.error(self.tr('まだ試験出力がありません。「宣言版を試験出力」を押してください。', 'No trial output exists. Use Export declared versions for testing.') if self.project and self.project.version_profiles else 'まだ翻訳MODが生成されていません。「翻訳MODを書き出す」を押してください。')
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(output))):
            self.error(f'フォルダーを開けませんでした。ファイルマネージャーで開いてください:\n{output}')

    def generate_versions_test(self):
        if not self.project or self.busy or not self.project.version_profiles:
            return False
        try:
            output = self.output_folder(trial=True)
        except ValueError as exc:
            self.error(exc)
            return False
        answer = QMessageBox.question(self, self.tr('宣言版の試験出力', 'Trial output for declared versions'), self.tr(
            f'全宣言版を試験出力します。正式出力ではありません（Q17保留）。\n'
            f'型情報・ゲーム動作は未検証です。危険な訳や不完全なStringsファイルは除外されます。\n'
            f'作業データを保存してから出力します。出力先: {output}\n続けますか？',
            f'Export all declared versions for testing. This is not a formal release (Q17 pending).\n'
            f'Type information and game behavior are unverified. Unsafe translations and incomplete Strings files are omitted.\n'
            f'Project data will be saved first. Destination: {output}\nContinue?'),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes or not self.save(export=False):
            return False
        try:
            warnings = export_versions_test(self.project, output)
        except (ValueError, OSError) as exc:
            message = self.tr(
                f'作業データは保存済み。試験出力は更新できませんでした。保存先と診断を確認して再試行してください: {output}',
                f'Project saved. Trial output could not be updated. Check the destination and diagnostics, then retry: {output}')
            self.guidance.setText(message)
            self.statusBar().showMessage(message)
            self.error(exc)
            return False
        self.guidance.setText(self.tr(
            f'宣言版を試験出力しました。正式出力ではありません（Q17保留）。未検証・要確認 {len(warnings)} 件。出力先: {output}',
            f'Trial output created; not a formal release (Q17 pending). Unverified/review notices: {len(warnings)}. Destination: {output}'))
        self.statusBar().showMessage(self.guidance.text())
        self.show_trial_output_report(output, warnings)
        return True

    def close_trial_output_report(self):
        if self.trial_output_report is not None:
            self.trial_output_report.close()
            self.trial_output_report.deleteLater()
            self.trial_output_report = None
        self.reopen_trial_report_action.setEnabled(False)

    def reopen_trial_output_report(self):
        if not self.busy and self.trial_output_report is not None:
            self.trial_output_report.show()
            self.trial_output_report.raise_()
            self.trial_output_report.activateWindow()

    def show_trial_output_report(self, output, warnings, summary=None, title=None):
        """Keep output notices separate from the project's extraction diagnostics."""
        self.close_trial_output_report()
        dialog = QDialog(self)
        dialog.setObjectName('trialOutputReport')
        dialog.setWindowTitle(title or self.tr('試験出力結果・警告', 'Trial output result and notices'))
        available = self.screen().availableGeometry()
        dialog.resize(min(820, max(1, available.width() - 40)),
                      min(500, max(1, available.height() - 40)))
        layout = QVBoxLayout(dialog)
        summary = summary or self.tr(
            f'宣言版の試験出力結果です。正式出力ではありません（Q17保留）。型情報・ゲーム動作は未検証です。\n'
            f'出力先: {output}\n出力時の警告・要確認: {len(warnings)} 件（全件）\n'
            'この結果は出力成功時点の記録です。その後の編集や失敗した再出力は反映しません。\n'
            '抽出・翻訳の診断は「抽出できなかった項目」から別途確認してください。',
            f'Trial output result; not a formal release (Q17 pending). Type information and game behavior are unverified.\n'
            f'Destination: {output}\nOutput notices: {len(warnings)} (all)\n'
            'This records a successful output. Later edits and failed retries are not reflected here.\n'
            'Review extraction and translation diagnostics separately via Extraction diagnostics.')
        report_text = summary + '\n\n' + '\n\n'.join(
            f'{index}. {warning}' for index, warning in enumerate(warnings, 1))
        notices = QPlainTextEdit()
        notices.setObjectName('trialOutputNotices')
        notices.setReadOnly(True)
        notices.setPlainText(report_text)
        layout.addWidget(notices)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        copy_button = buttons.addButton(self.tr('全件をコピー', 'Copy all'), QDialogButtonBox.ActionRole)
        copy_button.setObjectName('copyTrialOutputNotices')
        copy_button.clicked.connect(lambda: QApplication.clipboard().setText(report_text))
        buttons.rejected.connect(dialog.close)
        layout.addWidget(buttons)
        self.trial_output_report = dialog
        self.reopen_trial_report_action.setEnabled(not self.busy)
        dialog.show()

    def generate_versions(self):
        """Formal multi-version output: finished versions only (Q17 A)."""
        try:
            output = self.output_folder()
        except ValueError as exc:
            self.error(exc)
            return False
        if not self.save(export=False):
            return False
        try:
            result = export_shared(self.project, output)
        except (ValueError, OSError) as exc:
            message = self.tr(
                '作業データは保存済み。正式出力できる版がないため、翻訳MODは更新していません。理由を確認してください。',
                'Project saved. No version is ready for formal output, so the translation MOD was not updated. Check the reasons.')
            self.guidance.setText(message)
            self.statusBar().showMessage(message)
            self.error(exc)
            return False
        exported = ', '.join(result.exported)
        held = ', '.join(sorted(result.held, key=lambda value: tuple(int(part) for part in value.split('.')))) or self.tr('なし', 'none')
        message = self.tr(
            f'翻訳MODを正式出力しました。出力した版: {exported} / 保留した版: {held}。出力先: {output}',
            f'Translation MOD exported. Versions: {exported} / Held: {held}. Destination: {output}')
        self.guidance.setText(message)
        self.statusBar().showMessage(message, 15000)
        reasons = '\n'.join(f'  {version}: {reason}' for version, reason in result.held.items())
        summary = self.tr(
            f'正式出力の結果です。準備できた版の訳を、全バージョンが読む共通の1セットにまとめました。保留した版は含めていません。\n'
            f'出力した版: {exported}\n保留した版: {held}\n' + (f'保留理由:\n{reasons}\n' if reasons else '')
            + f'出力先: {output}\n未訳の項目は出力していません（ゲームでは原文が表示されます）。\n'
            f'型情報・ゲーム内表示は別途確認が必要です。警告・要確認: {len(result.warnings)} 件',
            f'Formal output result. The ready versions were merged into one set that every game version reads; held versions are not included.\n'
            f'Exported: {exported}\nHeld: {held}\n' + (f'Reasons:\n{reasons}\n' if reasons else '')
            + f'Destination: {output}\nUntranslated entries are omitted (the game shows source text).\n'
            f'Type information and in-game display need separate checks. Notices: {len(result.warnings)}')
        self.show_trial_output_report(output, result.warnings, summary=summary,
                                      title=self.tr('正式出力結果', 'Formal output result'))
        return True

    def generate(self):
        if not self.project or self.busy: return False
        if self.project.version_profiles:
            return self.generate_versions()
        try:
            output = self.output_folder()
            warnings = export_mod(self.project, output)
            if not self.save(export=False): return False
            self.guidance.setText(self.tr(f'翻訳MODを生成しました。ゲーム用フォルダー: {output}',f'Translation MOD exported: {output}'))
            self.statusBar().showMessage(f'書き出し完了  ·  要確認 {len(warnings)} 件  ·  元MODは変更していません', 15000)
            return True
        except Exception as exc:
            self.error(exc)
            return False

    def add_entry(self):
        if not self.project or self.busy: return
        dialog = QDialog(self)
        dialog.setWindowTitle('手動キー追加（特殊項目はゲーム内で要確認）')
        form = QFormLayout(dialog)
        kind = QComboBox()
        kind.addItems(['DefInjected', 'Keyed'])
        group, key, english, japanese = QLineEdit('ThingDef'), QLineEdit(), QPlainTextEdit(), QPlainTextEdit()
        for label, widget in [('形式', kind), ('Def 型（Keyed では無視）', group), ('完全なキー（例 Gun.label）', key), ('英語', english), ('日本語', japanese)]: form.addRow(label, widget)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.Accepted: return
        category = 'Keyed' if kind.currentText() == 'Keyed' else group.text().strip()
        name = key.text().strip()
        identity = f'{kind.currentText()}:{category}:{name}'
        if not KEY.fullmatch(category) or not KEY.fullmatch(name) or any(e.id == identity for e in self.project.entries):
            self.error('キー / Def 型が不正、または既存キーと重複しています。')
            return
        self.project.entries.append(Entry(identity, kind.currentText(), category, name, english.toPlainText(), '(manual)', japanese.toPlainText(), review=True))
        self.populate()
        self.on_edit()

    def show_warnings(self):
        return ToolsMixin.show_warnings(self)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'sidebar'):
            compact = self.width()<1050
            self.sidebar.setVisible(not compact)
            self.mod_thumbnail.setVisible(not (compact or self.height() < 860))
            self.save_button.setVisible(not compact)
        if hasattr(self,'editor_eyebrow'):
            # On short screens (1366x768 laptops) the header would push the translation boxes below the fold,
            # so drop the decorative and secondary lines and let the table shrink.
            short = self.height() < 860
            self.editor_eyebrow.setVisible(not short)
            self.version_context_status.setVisible(not short)
            self.guidance.setVisible(not short)  # the status bar repeats its messages
            self.table.setMinimumHeight(90 if short else 150)
            self.editor_content.layout().setSpacing(5 if short else 10)
            self.editor_content.layout().setContentsMargins(22, 10 if short else 21, 22, 8 if short else 13)
        if hasattr(self,'side_tabs'):
            self.adapt_panel()
            self.fit_sidebar()
        if hasattr(self,'editor_pair_layout'):
            self.editor_pair_layout.setDirection(QBoxLayout.TopToBottom if self.width()<680 else QBoxLayout.LeftToRight)

    def eventFilter(self,watched,event):
        if event.type()==QEvent.Resize and watched is self.editor_scroll.viewport():
            self.fit_editor_height()
        if event.type()==QEvent.Resize and watched is self.table.viewport():
            self.empty_state.setGeometry(self.table.viewport().rect())
        return super().eventFilter(watched,event)

    def fit_editor_height(self):
        """Keep the editor page inside the window whenever its minimum fits; scroll only when it truly cannot."""
        content = self.editor_content
        content.setMaximumHeight(max(self.editor_scroll.viewport().height(),content.minimumSizeHint().height()))

    def showEvent(self,event):
        super().showEvent(event)
        if not getattr(self,'_screen_clamped',False) and QApplication.platformName()!='offscreen':
            self._screen_clamped = True
            screen = self.screen().availableGeometry()
            self.resize(min(self.width(),max(480,screen.width()-20)),min(self.height(),max(280,screen.height()-40)))

    def closeEvent(self, event):
        if self.busy:
            self.statusBar().showMessage('スキャンが完了してから閉じてください。')
            event.ignore()
        elif self.confirm_switch():
            self.autosave.stop()
            event.accept()
        else: event.ignore()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('RimWorld Translation Editor')
    font = app.font()
    font.setPointSize(11)
    app.setFont(font)
    window = Window()
    install_qt_translator(app, window.ui_language)
    if len(sys.argv) > 1: window.load_project(Path(sys.argv[1]))
    window.show()
    return app.exec()
