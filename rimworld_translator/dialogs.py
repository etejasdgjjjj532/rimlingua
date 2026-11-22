"""Visual selectors for RimWorld source MODs and one-or-more target languages."""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import Qt, QSize, QRectF, QTimer
from PySide6.QtGui import QIcon, QImageReader, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QCheckBox, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox,
    QTabWidget, QVBoxLayout, QWidget)

from .core import safe_xml
from .languages import LANGUAGES, validate_languages
from .platforms import app_cache_directory, clear_app_cache_report, detected_mods, detected_workshop, find_mods_config
from .preview import find_source_preview


def source_image(source: Path, width: int = 160, height: int = 95) -> QPixmap:
    path = find_source_preview(source)
    if path is not None:
        reader = QImageReader(str(path))
        reader.setScaledSize(QSize(width * 2, height * 2))
        pic = reader.read()
        if not pic.isNull():
            return QPixmap.fromImage(pic).scaled(
                width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    missing = QPixmap(width, height)
    missing.fill(Qt.darkGray)
    return missing


def flag_icon(language: str) -> QIcon:
    flag = LANGUAGES[language][1]
    path = Path(__file__).resolve().parent / "assets" / "flags" / f"{flag}.svg"
    art = QPixmap(44, 31)
    art.fill(Qt.transparent)
    painter = QPainter(art)
    try:
        renderer = QSvgRenderer(str(path))
        if renderer.isValid():
            renderer.render(painter, QRectF(0, 0, 44, 31))
    finally:
        painter.end()
    return QIcon(art)


def select_languages(parent, preselected=None) -> list[str] | None:
    """Returns None if cancelled, and never returns an empty list."""
    defaults = set(preselected if preselected is not None else ["Japanese"])
    dialog = QDialog(parent)
    dialog.setWindowTitle("翻訳先の言語を選ぶ")
    dialog.resize(460, 595)
    layout = QVBoxLayout(dialog)
    heading = QLabel("翻訳する言語を選んでください（複数選択可）")
    layout.addWidget(heading)
    hint = QLabel("最低1言語必要です。後から追加・変更もできます。")
    hint.setWordWrap(True)
    layout.addWidget(hint)
    listing = QListWidget()
    for lang, (label, flag) in LANGUAGES.items():
        item = QListWidgetItem(flag_icon(lang), label, listing)
        item.setData(Qt.UserRole, lang)
        item.setCheckState(Qt.Checked if lang in defaults else Qt.Unchecked)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
    layout.addWidget(listing, 1)
    quick_row = QHBoxLayout()
    select_all = QPushButton("29言語すべて選択" if len(LANGUAGES) == 29 else "すべて選択")
    japanese_only = QPushButton("日本語だけ")
    quick_row.addWidget(select_all)
    quick_row.addWidget(japanese_only)
    quick_row.addStretch()
    layout.addLayout(quick_row)
    select_all.clicked.connect(lambda: [listing.item(i).setCheckState(Qt.Checked)
                                       for i in range(listing.count())])
    japanese_only.clicked.connect(lambda: [listing.item(i).setCheckState(
        Qt.Checked if listing.item(i).data(Qt.UserRole) == 'Japanese' else Qt.Unchecked)
        for i in range(listing.count())])
    result = QLabel("")
    layout.addWidget(result)
    actions = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    okay = actions.button(QDialogButtonBox.Ok)
    okay.setText("この言語で進める")
    actions.rejected.connect(dialog.reject)
    actions.accepted.connect(dialog.accept)
    layout.addWidget(actions)

    def current_selection() -> list[str]:
        return [listing.item(i).data(Qt.UserRole) for i in range(listing.count())
                if listing.item(i).checkState() == Qt.Checked]

    def changed(*_):
        selection = current_selection()
        okay.setEnabled(bool(selection))
        result.setText(f"選択中：{len(selection)} 言語" if selection else "1言語以上チェックしてください")
    listing.itemChanged.connect(changed)
    changed()
    if dialog.exec() != QDialog.Accepted:
        return None
    return validate_languages(current_selection())


def select_workshop_mod(parent, workshop: Path | list[Path]) -> Path | None:
    """Index metadata in small event-loop batches and load only visible previews."""
    from .i18n import text
    language = getattr(parent,'ui_language','ja')
    tr = lambda jp,en=None:text(jp,language,en)
    settings = getattr(parent,'settings',None)
    favorites = set(settings.data['favorite_sources']) if settings else set()
    roots = [workshop] if isinstance(workshop,Path) else list(workshop)
    folders = sorted({p for root in roots if root.is_dir() for p in root.iterdir() if p.is_dir() and not p.is_symlink()},key=lambda p:(str(p.resolve()) not in favorites,p.name))
    if not folders:
        QMessageBox.warning(parent,tr('MODがありません','No MODs found'),tr('Steam WorkshopのMODが見つかりません。ローカルフォルダーから選べます。','No Workshop MODs found. Choose a local source folder instead.'))
        return None
    dialog = QDialog(parent)
    dialog.setWindowTitle(tr('Steam WorkshopからMODを選ぶ'))
    dialog.resize(760,620)
    layout = QVBoxLayout(dialog)
    title = QLabel(tr('翻訳したいMODを選んでください'))
    layout.addWidget(title)
    search = QLineEdit()
    search.setPlaceholderText(tr('MOD名またはWorkshop IDで検索'))
    search.setClearButtonEnabled(True)
    search.setAccessibleName(tr('元 MOD を名前・ID・作者で検索','Search MOD name, ID or author'))
    layout.addWidget(search)
    options = QHBoxLayout()
    favorite_only = QCheckBox(tr('お気に入りだけ','Favorites only'))
    favorite = QPushButton(tr('お気に入りを切り替え','Toggle favorite'))
    favorite.setObjectName('favoriteSource')
    favorite.setEnabled(False)
    options.addWidget(favorite_only)
    options.addWidget(favorite)
    options.addStretch()
    layout.addLayout(options)
    collection = QListWidget()
    collection.setViewMode(QListWidget.IconMode)
    collection.setMovement(QListWidget.Static)
    collection.setResizeMode(QListWidget.Adjust)
    collection.setWrapping(True)
    collection.setIconSize(QSize(140,85))
    collection.setGridSize(QSize(178,152))
    collection.setSpacing(4)
    collection.setUniformItemSizes(True)
    placeholder = QPixmap(140,85)
    placeholder.fill(Qt.darkGray)
    icon = QIcon(placeholder)
    for folder in folders:
        item = QListWidgetItem(icon,folder.name,collection)
        item.setData(Qt.UserRole,str(folder))
        item.setData(int(Qt.UserRole)+1,folder.name.casefold())
        item.setTextAlignment(Qt.AlignCenter)
    layout.addWidget(collection,1)
    progress = QLabel('')
    layout.addWidget(progress)
    chosen = QLabel(tr('選択したMODの元ファイルは変更されません。'))
    chosen.setWordWrap(True)
    layout.addWidget(chosen)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
    okay = buttons.button(QDialogButtonBox.Ok)
    okay.setText(tr('このMODを翻訳する'))
    okay.setEnabled(False)
    buttons.rejected.connect(dialog.reject)
    buttons.accepted.connect(dialog.accept)
    collection.itemDoubleClicked.connect(lambda _:dialog.accept())
    layout.addWidget(buttons)
    indexed = 0
    loaded_icons = set()

    def select():
        item = collection.currentItem()
        valid = item is not None and not item.isHidden()
        okay.setEnabled(valid)
        favorite.setEnabled(valid and settings is not None)
        if valid:
            chosen.setText(item.toolTip())

    def filtered(*_):
        needle = search.text().casefold()
        for index in range(collection.count()):
            item = collection.item(index)
            hidden = needle not in item.data(int(Qt.UserRole)+1)
            hidden = hidden or (favorite_only.isChecked() and item.data(Qt.UserRole) not in favorites)
            item.setHidden(hidden)
        select()
        load_visible_images()

    def toggle():
        item = collection.currentItem()
        if not item or not settings:
            return
        path = Path(item.data(Qt.UserRole))
        settings.toggle_favorite(path)
        favorites.clear()
        favorites.update(settings.data['favorite_sources'])
        filtered()

    def load_visible_images():
        # QImageReader scales before decoding; images never enter the source index.
        viewport = collection.viewport().rect()
        for index in range(min(indexed,collection.count())):
            item = collection.item(index)
            if index not in loaded_icons and not item.isHidden() and collection.visualItemRect(item).intersects(viewport):
                item.setIcon(QIcon(source_image(folders[index],140,85)))
                loaded_icons.add(index)

    def step():
        nonlocal indexed
        end = min(indexed+8,len(folders))
        for index in range(indexed,end):
            folder,item = folders[index],collection.item(index)
            name,author,package = folder.name,'',''
            try:
                metadata = safe_xml(folder/'About/About.xml')
                name = metadata.findtext('name') or name
                author = metadata.findtext('author') or ''
                package = metadata.findtext('packageId') or ''
            except (OSError,ValueError,Exception):
                pass
            item.setText(name[:44]+'\n'+folder.name)
            item.setData(int(Qt.UserRole)+1,'\n'.join((name,folder.name,author,package)).casefold())
            item.setToolTip(f'{name}\nID: {folder.name}\nAuthor: {author}\nPackage: {package}\n{folder}')
        indexed = end
        progress.setText(tr(f'{indexed}/{len(folders)} MOD の情報を読み込みました',f'Indexed {indexed}/{len(folders)} MODs'))
        filtered()
        if indexed==len(folders):
            timer.stop()

    timer = QTimer(dialog)
    timer.setInterval(0)
    timer.timeout.connect(step)
    search.textChanged.connect(filtered)
    favorite_only.toggled.connect(filtered)
    favorite.clicked.connect(toggle)
    collection.currentItemChanged.connect(lambda *_:select())
    collection.verticalScrollBar().valueChanged.connect(lambda *_:load_visible_images())
    step()
    if indexed<len(folders):
        timer.start()
    result = dialog.exec()
    timer.stop()
    item = collection.currentItem()
    return Path(item.data(Qt.UserRole)) if result==QDialog.Accepted and item and not item.isHidden() else None



class PreferencesDialog(QDialog):
    """Preferences in four tabs. ``collect()`` returns the edited values; the window applies them.

    Folder fields stay empty for auto-detection and show the detected folder greyed out as the placeholder.
    All MOD folders are only ever read.
    """
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        data = window.settings.data
        tr = self.tr_ = window.tr
        games = window.discovered_games()
        self.setWindowTitle(tr('設定', 'Preferences'))
        self.resize(640, 520)
        self.languages = list(data['default_languages'])
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.setObjectName('preferenceTabs')
        layout.addWidget(self.tabs)

        def page(title):
            widget = QWidget()
            outer = QVBoxLayout(widget)
            form = QFormLayout()
            form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            outer.addLayout(form)
            outer.addStretch(1)
            self.tabs.addTab(widget, title)
            return form

        def folder_row(edit, directory=True, file_filter=''):
            row = QHBoxLayout()
            row.addWidget(edit, 1)
            button = QPushButton(tr('選ぶ…', 'Browse…'))
            def browse():
                start = edit.text().strip() or edit.placeholderText()
                if directory:
                    chosen = QFileDialog.getExistingDirectory(self, tr('フォルダーを選ぶ', 'Choose folder'), start)
                else:
                    chosen, _ = QFileDialog.getOpenFileName(self, tr('ファイルを選ぶ', 'Choose file'), start, file_filter)
                if chosen:
                    edit.setText(chosen)
            button.clicked.connect(browse)
            row.addWidget(button)
            return row

        # General
        general = page(tr('一般', 'General'))
        self.language = QComboBox()
        self.language.addItem(tr('OS の言語に合わせる', 'Follow OS language'), 'system')
        self.language.addItem('日本語', 'ja')
        self.language.addItem('English', 'en')
        stored_language = getattr(getattr(window, 'settings', None), 'data', {}).get('ui_language', window.ui_language)
        self.language.setCurrentIndex(max(0, self.language.findData(stored_language)))
        self.theme = QComboBox()
        for value, jp, en in (('system', 'システムに合わせる', 'Follow system'), ('light', 'ライト', 'Light'), ('dark', 'ダーク', 'Dark')):
            self.theme.addItem(tr(jp, en), value)
        self.theme.setCurrentIndex(max(0, self.theme.findData(data['theme_mode'])))
        self.font_size = QSpinBox()
        self.font_size.setRange(8, 24)
        self.font_size.setValue(data['font_size'])
        self.autosave_spin = QSpinBox()
        self.autosave_spin.setRange(0, 3600)
        self.autosave_spin.setSuffix(tr(' 秒', ' s'))
        self.autosave_spin.setSpecialValueText(tr('自動保存しない', 'Autosave off'))
        self.autosave_spin.setValue(data['autosave_seconds'])
        self.autosave_spin.setToolTip(tr('編集してから自動保存するまでの時間（10〜3600 秒、0 で無効）。',
                                         'Time after an edit before autosaving (10-3600 seconds, 0 turns it off).'))
        self.repository = QLineEdit(data['release_repository'])
        self.repository.setPlaceholderText('owner/repository')
        self.updates = QCheckBox(tr('無料の GitHub 公開リリースを確認する', 'Check public GitHub releases'))
        self.updates.setChecked(data['check_updates'])
        general.addRow(tr('画面の言語', 'Interface language'), self.language)
        general.addRow(tr('配色', 'Theme'), self.theme)
        general.addRow(tr('文字サイズ', 'Font size'), self.font_size)
        general.addRow(tr('自動保存の間隔', 'Autosave interval'), self.autosave_spin)
        general.addRow(tr('配布リポジトリ（任意）', 'Release repository (optional)'), self.repository)
        general.addRow(self.updates)
        transfer = QHBoxLayout()
        self.export_button = QPushButton(tr('設定を書き出す…', 'Export settings…'))
        self.import_button = QPushButton(tr('設定を取り込む…', 'Import settings…'))
        self.export_button.clicked.connect(window.export_settings_file)
        self.import_button.clicked.connect(self._import)
        transfer.addWidget(self.export_button)
        transfer.addWidget(self.import_button)
        transfer.addStretch()
        general.addRow(tr('別の PC へ設定を移す', 'Move settings to another computer'), transfer)

        # Folders
        folders = page(tr('フォルダー', 'Folders'))
        hint = QLabel(tr('空欄なら自動検出します（検出した場所は薄く表示）。ここで指定した MOD フォルダーは読み取り専用で、'
                         '前提 MOD の探索と元 MOD の選択にだけ使い、書き込みません。',
                         'Leave a field empty to auto-detect it (the detected folder is shown greyed out). MOD folders are read-only: '
                         'used to find prerequisites and to choose the source MOD, never written.'))
        hint.setWordWrap(True)
        folders.addRow(hint)
        self.workshop_edit = QLineEdit(data['workshop_folder'])
        self.workshop_edit.setPlaceholderText(self._first(detected_workshop(games)))
        self.mods_edit = QLineEdit(data['mods_folder'])
        self.mods_edit.setPlaceholderText(self._first(detected_mods(games)))
        self.external_edit = QPlainTextEdit('\n'.join(data['external_mod_folders']))
        self.external_edit.setMaximumHeight(90)
        self.external_edit.setPlaceholderText(tr('1 行に 1 フォルダー', 'One folder per line'))
        add_external = QPushButton(tr('フォルダーを追加…', 'Add folder…'))
        def add_folder():
            chosen = QFileDialog.getExistingDirectory(self, tr('MOD を置いたフォルダーを選ぶ', 'Choose a folder that holds MODs'))
            if chosen:
                text = self.external_edit.toPlainText().rstrip('\n')
                self.external_edit.setPlainText((text + '\n' if text else '') + chosen)
        add_external.clicked.connect(add_folder)
        folders.addRow(tr('Steam Workshop フォルダー', 'Steam Workshop folder'), folder_row(self.workshop_edit))
        folders.addRow(tr('ゲームの Mods フォルダー', 'Game Mods folder'), folder_row(self.mods_edit))
        folders.addRow(tr('追加の MOD フォルダー', 'Extra MOD folders'), self.external_edit)
        folders.addRow('', add_external)
        self.mods_config_edit = QLineEdit(data['mods_config_path'])
        found = find_mods_config()
        self.mods_config_edit.setPlaceholderText(str(found) if found else self._first([]))
        folders.addRow(tr('ModsConfig.xml の場所', 'ModsConfig.xml location'),
                       folder_row(self.mods_config_edit, directory=False, file_filter='ModsConfig.xml (*.xml)'))

        # Extraction
        extraction = page(tr('抽出', 'Extraction'))
        self.paths = QPlainTextEdit('\n'.join(data['game_paths']))
        self.paths.setMaximumHeight(100)
        from .game_library import library_directory
        self.library = QLineEdit(data['game_library'])
        self.library.setPlaceholderText(str(library_directory()))
        open_library = QPushButton(tr('ライブラリを開く', 'Open library'))
        open_library.clicked.connect(self._show_library)
        self.schema = QCheckBox(tr('ゲームと MOD の C# フィールド情報を読み取る（DLL は実行しない）',
                                   'Inspect game/MOD C# field metadata without executing DLLs'))
        self.schema.setChecked(data['inspect_metadata'])
        self.cache_edit = QLineEdit(data['cache_directory'])
        self.cache_edit.setPlaceholderText(str(app_cache_directory()))
        clear = QPushButton(tr('キャッシュを消去…', 'Clear cache…'))
        clear.clicked.connect(self._clear_cache)
        library_row = QHBoxLayout()
        library_row.addWidget(self.library, 1)
        library_row.addWidget(open_library)
        cache_row = folder_row(self.cache_edit)
        cache_row.addWidget(clear)
        extraction.addRow(tr('ゲームの場所（1行に1フォルダー）', 'Game paths (one folder per line)'), self.paths)
        extraction.addRow(tr('ゲーム版ライブラリの場所（空欄で既定）', 'Game library folder (blank for default)'), library_row)
        extraction.addRow(self.schema)
        extraction.addRow(tr('キャッシュの場所', 'Cache location'), cache_row)

        # Output
        output = page(tr('出力', 'Output'))
        note = QLabel(tr('新しいプロジェクトの既定値です。出力先フォルダーはプロジェクトごとに「プロジェクト」メニューで設定します。',
                         'Defaults for new projects. The output folder is set per project in the Project menu.'))
        note.setWordWrap(True)
        output.addRow(note)
        self.translator_edit = QLineEdit(data['default_translator'])
        self.translator_edit.setPlaceholderText(tr('空欄なら About.xml に翻訳者名を書きません', 'Empty: no author is written to About.xml'))
        self.license_edit = QLineEdit(data['default_license'])
        self.language_label = QLabel()
        choose_languages = QPushButton(tr('選ぶ…', 'Choose…'))
        choose_languages.clicked.connect(self._choose_languages)
        language_row = QHBoxLayout()
        language_row.addWidget(self.language_label, 1)
        language_row.addWidget(choose_languages)
        self._show_languages()
        self.backup_spin = QSpinBox()
        self.backup_spin.setRange(0, 9999)
        self.backup_spin.setSpecialValueText(tr('すべて残す', 'Keep all'))
        self.backup_spin.setSuffix(tr(' 世代', ' generations'))
        self.backup_spin.setValue(data['backup_generations'])
        self.backup_spin.setToolTip(tr('保存のたびに作る履歴（バックアップ）を何世代残すか。古いものから消えます。0 ですべて残します。'
                                       'Git の履歴は書き換えません。',
                                       'How many saved checkpoints a project keeps; the oldest are deleted first. 0 keeps all. Git history is never rewritten.'))
        output.addRow(tr('翻訳者名の既定', 'Default translator name'), self.translator_edit)
        output.addRow(tr('バックアップの世代数', 'Backup generations'), self.backup_spin)
        output.addRow(tr('ライセンスの既定', 'Default license'), self.license_edit)
        output.addRow(tr('翻訳先言語の既定', 'Default target languages'), language_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _first(self, found):
        return str(found[0]) if found else self.tr_('（見つかりません）', '(not found)')

    def _show_languages(self):
        self.language_label.setText(', '.join(LANGUAGES[c][0] for c in self.languages))

    def _choose_languages(self):
        chosen = select_languages(self, self.languages)
        if chosen:
            self.languages = chosen
            self._show_languages()

    def _import(self):
        if self.window.import_settings_file():
            self.reject()

    def _show_library(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from .game_library import library_directory
        tr = self.tr_
        folder = library_directory(override=self.library.text().strip())
        # Opening never creates the folder; the user decides where game versions live.
        if not folder.is_dir():
            self.window.info_dialog(tr('ゲーム版ライブラリ', 'Game library'),
                                    tr(f'フォルダーがまだありません: {folder}', f'The folder does not exist yet: {folder}'))
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            self.window.info_dialog(tr('ゲーム版ライブラリ', 'Game library'),
                                    tr(f'フォルダーを開けませんでした。ファイルマネージャーで開いてください: {folder}',
                                       f'Could not open the folder; open it in a file manager: {folder}'))

    def _clear_cache(self):
        tr = self.tr_
        folder = app_cache_directory(override=self.cache_edit.text().strip())
        answer = QMessageBox.question(self, tr('キャッシュを消去', 'Clear cache'),
                                      tr(f'次の場所にあるエディターの作業キャッシュ（ゲームの型情報など）を消去します。必要になれば自動で作り直します。このエディターが作った印のあるフォルダーだけを消し、それ以外は残します。\n{folder}',
                                         f'This removes the editor\'s rebuildable cache (game field tables and similar) in:\n{folder}\nIt is rebuilt when needed. Only folders carrying this editor\'s marker are removed; anything else stays.'))
        if answer == QMessageBox.Yes:
            count, skipped = clear_app_cache_report(folder)
            note = tr(f'キャッシュを {count} 件消去しました。', f'Cleared {count} cache folders.')
            if skipped:
                names = ', '.join(skipped)
                note += tr(f' このエディターが作成した印のないフォルダーは消さずに残しました: {names}',
                           f' Left alone because they lack this editor\'s marker: {names}')
            self.window.statusBar().showMessage(note, 12000)

    def collect(self) -> dict:
        lines = lambda edit: [line.strip() for line in edit.toPlainText().splitlines() if line.strip()]
        seconds = self.autosave_spin.value()
        return {'ui_language': self.language.currentData(), 'theme_mode': self.theme.currentData(),
                'font_size': self.font_size.value(),
                'autosave_seconds': 0 if seconds == 0 else max(10, seconds),
                'release_repository': self.repository.text().strip(), 'check_updates': self.updates.isChecked(),
                'workshop_folder': self.workshop_edit.text().strip(), 'mods_folder': self.mods_edit.text().strip(),
                'external_mod_folders': lines(self.external_edit),
                'mods_config_path': self.mods_config_edit.text().strip(),
                'game_paths': lines(self.paths), 'game_library': self.library.text().strip(),
                'inspect_metadata': self.schema.isChecked(), 'cache_directory': self.cache_edit.text().strip(),
                'default_translator': self.translator_edit.text().strip(),
                'default_license': self.license_edit.text().strip(),
                'default_languages': list(self.languages), 'backup_generations': self.backup_spin.value()}
