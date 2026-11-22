"""Polished, beginner-oriented layout for the standalone Qt translation editor.

Keep widgets lightweight so the interface works on older Intel integrated graphics.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from .theme import resolve_mode, stylesheet, system_prefers_dark
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPlainTextEdit, QProgressBar, QPushButton, QSizePolicy, QSplitter,
    QStackedWidget, QTabBar, QTableView, QTabWidget, QTextBrowser, QToolButton, QTreeWidget, QVBoxLayout, QWidget, QScrollArea,
    QListWidget, QCheckBox
)


class ElidedLabel(QLabel):
    """A one-line label that shortens its text with an ellipsis instead of wrapping.

    ``text()`` still returns the full text; the tooltip carries it too unless one was set.
    """
    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self.setWordWrap(False)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def minimumSizeHint(self):
        size = super().minimumSizeHint()
        size.setWidth(0)
        return size

    def sizeHint(self):
        size = super().sizeHint()
        size.setWidth(min(size.width(), 400))
        return size

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        rect = self.contentsRect()
        shown = self.fontMetrics().elidedText(self.text(), Qt.ElideMiddle, rect.width())
        painter.drawText(rect, int(self.alignment()), shown)

def tag(label, name):
    lbl = QLabel(label)
    lbl.setObjectName(name)
    lbl.setWordWrap(True)
    lbl.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Minimum)
    return lbl

def make_button(label, callback, kind=None, tooltip=None):
    b = QPushButton(label)
    if kind:
        b.setObjectName(kind)
    if tooltip:
        b.setToolTip(tooltip)
    b.clicked.connect(callback)
    b.setCursor(Qt.PointingHandCursor)
    b.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Fixed)
    return b

def step_card(number, title, detail):
    card = QFrame()
    card.setObjectName("stepCard")
    row = QHBoxLayout(card)
    row.setContentsMargins(15, 12, 15, 12)
    circle = tag(number, "stepNumber")
    circle.setFixedSize(30, 30)
    circle.setAlignment(Qt.AlignCenter)
    row.setSpacing(14)
    row.addWidget(circle)
    col = QVBoxLayout()
    col.setSpacing(4)
    col.addWidget(tag(title, "h2"))
    col.addWidget(tag(detail, "helpText"))
    row.addLayout(col, 1)
    return card

def setup_editor_ui(w, statuses):
    w.setWindowTitle("RimWorld 翻訳ワークスペース")
    w.resize(1240, 730)
    w.setMinimumSize(480, 280)
    w.setStyleSheet(stylesheet(resolve_mode('system', system_prefers_dark())))
    root = QWidget()
    root.setObjectName("appRoot")
    w.setCentralWidget(root)
    shell = QHBoxLayout(root)
    shell.setContentsMargins(0, 0, 0, 0)
    shell.setSpacing(0)

    sidebar = QFrame()
    sidebar.setObjectName("sidebar")
    sidebar.setFixedWidth(236)
    side = QVBoxLayout(sidebar)
    side.setContentsMargins(16, 20, 16, 16)
    side.setSpacing(6)
    brand_row = QHBoxLayout()
    brand_row.setSpacing(10)
    mark = tag("訳", "brandMark")
    mark.setFixedSize(32, 32)
    mark.setAlignment(Qt.AlignCenter)
    brand_row.addWidget(mark)
    brand_text = QVBoxLayout()
    brand_text.setSpacing(0)
    brand = tag("翻訳エディター", "brand")
    brand.setWordWrap(False)
    brand_text.addWidget(brand)
    brand_sub = tag("RimWorld MOD", "muted")
    brand_sub.setWordWrap(False)
    brand_text.addWidget(brand_sub)
    brand_row.addLayout(brand_text, 1)
    side.addLayout(brand_row)
    side.addSpacing(18)
    side.addWidget(tag("プロジェクト", "eyebrow"))
    w.sidebar_project = tag("まだプロジェクトを開いていません", "helpText")
    side.addWidget(w.sidebar_project)
    side.addSpacing(8)
    # Not a suggested-style button: each view keeps a single highlighted action (export, or the
    # welcome page's own start button).
    w.new_button = make_button("＋  新しいMODを翻訳", w.new_project, None,
                               "既存MODから日本語翻訳プロジェクトを作ります")
    w.open_button = make_button("続きから作業する", w.open_project)
    side.addWidget(w.new_button)
    side.addWidget(w.open_button)
    side.addSpacing(18)
    side.addWidget(tag("進み具合", "eyebrow"))
    w.progress_text = tag("MODを選ぶと進捗が表示されます", "helpText")
    side.addWidget(w.progress_text)
    w.progress = QProgressBar()
    w.progress.setRange(0, 100)
    w.progress.setValue(0)
    w.progress.setFormat("%p%")
    w.progress.setTextVisible(False)
    w.progress.setFixedHeight(6)
    side.addWidget(w.progress)
    # Names and descriptions are what players read first, so they get their own rate.
    w.p0_text = tag("名前・説明: -", "helpText")
    side.addWidget(w.p0_text)
    w.p0_bar = QProgressBar()
    w.p0_bar.setRange(0, 100)
    w.p0_bar.setValue(0)
    w.p0_bar.setTextVisible(False)
    w.p0_bar.setFixedHeight(6)
    side.addWidget(w.p0_bar)
    side.addSpacing(18)
    side.addWidget(tag("作業メニュー", "eyebrow"))
    w.save_side = make_button("保存する", w.save, "ghost", "Ctrl+S")
    w.rescan_side = make_button("元MODの更新を確認", w.rescan, "ghost")
    w.manual_side = make_button("翻訳キーを手動追加", w.add_entry, "ghost")
    w.warnings_side = make_button("抽出できなかった項目", w.show_warnings, "ghost")
    w.git_side = make_button("Gitにバックアップ", w.checkpoint, "ghost")
    w.output_side = make_button("出力フォルダーを開く", w.open_export_folder, "ghost")
    for b in (w.save_side, w.rescan_side, w.manual_side, w.warnings_side, w.git_side, w.output_side):
        side.addWidget(b)
    side.addStretch()
    side_scroll = QScrollArea()
    side_scroll.setWidgetResizable(True)
    side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    side_scroll.setObjectName('sidebarScroll')
    side_scroll.setFixedWidth(236)
    sidebar.setFixedWidth(220)
    side_scroll.setWidget(sidebar)
    w.sidebar = side_scroll
    shell.addWidget(side_scroll)

    w.views = QStackedWidget()
    shell.addWidget(w.views, 1)

    # First-launch landing page, not an empty data table.
    welcome = QWidget()
    welcome_root = QVBoxLayout(welcome)
    welcome_root.setContentsMargins(35, 20, 35, 20)
    welcome_root.addStretch()
    centered = QHBoxLayout()
    centered.addStretch()
    column_widget = QWidget()
    column_widget.setMaximumWidth(740)
    column = QVBoxLayout(column_widget)
    column.setSpacing(12)
    column.addWidget(tag("ようこそ", "eyebrow"))
    column.addWidget(tag("RimWorldのMODを、\n日本語で遊べるように。", "h1"))
    column.addWidget(tag(
        "元MODを選ぶだけで翻訳項目を自動抽出。\n原文を見ながら選んだ言語へ訳し、ゲーム用の翻訳MODを生成できます。", "helpText"
    ))
    column.addSpacing(10)
    column.addWidget(step_card("01", "MODを選ぶ",
                               "Steam WorkshopのMODも、手元のフォルダーも選べます。"))
    column.addWidget(step_card("02", "選んだ言語へ翻訳",
                               "原文と翻訳文を並べて編集。途中保存も自動です。"))
    column.addWidget(step_card("03", "ゲーム用に書き出す",
                               "元MODはそのまま。日本語化MODを別に生成します。"))
    column.addSpacing(12)
    welcome_actions = QHBoxLayout()
    welcome_actions.addWidget(make_button("＋  新しい翻訳を始める", w.new_project, "primary"))
    welcome_actions.addWidget(make_button("保存した翻訳を開く", w.open_project, "secondary"))
    welcome_actions.addStretch()
    column.addLayout(welcome_actions)
    centered.addWidget(column_widget, 1)
    centered.addStretch()
    welcome_root.addLayout(centered)
    welcome_root.addStretch()
    welcome_shell = QWidget()
    welcome_outer = QVBoxLayout(welcome_shell)
    welcome_outer.setContentsMargins(0,0,0,0)
    welcome_scroll = QScrollArea()
    welcome_scroll.setWidgetResizable(True)
    welcome_scroll.setWidget(welcome)
    welcome_outer.addWidget(welcome_scroll)
    w.welcome_page = welcome_shell
    w.views.addWidget(w.welcome_page)

    editor = QWidget()
    editor_scroll = QScrollArea()
    editor_scroll.setWidgetResizable(True)
    editor_scroll.setWidget(editor)
    w.editor_page = editor_scroll
    w.editor_scroll = editor_scroll
    w.editor_content = editor
    page = QVBoxLayout(editor)
    page.setContentsMargins(22, 21, 22, 13)
    page.setSpacing(10)
    w.editor_eyebrow = tag("翻訳プロジェクト", "eyebrow")
    page.addWidget(w.editor_eyebrow)
    heading_row = QHBoxLayout()
    w.mod_thumbnail = QLabel()
    w.mod_thumbnail.setObjectName('modThumbnail')
    w.mod_thumbnail.setFixedSize(110, 66)
    heading_row.setSpacing(12)
    w.mod_thumbnail.setAlignment(Qt.AlignCenter)
    w.mod_thumbnail.setText('MOD')
    heading_row.addWidget(w.mod_thumbnail)
    heading = QVBoxLayout()
    heading.setSpacing(4)
    heading.addWidget(tag("翻訳する", "h1"))
    w.location = ElidedLabel("元MODが選択されていません")
    w.location.setObjectName("muted")
    heading.addWidget(w.location)
    heading_row.addLayout(heading, 1)
    # Workspace tabs share the heading row, so they cost no vertical space on short screens.
    w.workspace_tabs = QTabBar()
    w.workspace_tabs.setObjectName('workspaceTabs')
    w.workspace_tabs.setExpanding(False)
    w.workspace_tabs.setDrawBase(False)
    w.workspace_tabs.setFocusPolicy(Qt.NoFocus)
    for label in ('翻訳', '確認', '進捗', '書き出し'):
        w.workspace_tabs.addTab(label)
    w.workspace_tabs.setEnabled(False)
    heading_row.addWidget(w.workspace_tabs, 0, Qt.AlignVCenter)
    w.save_button = make_button("変更を保存", w.save, "secondary", "作業データを保存します (Ctrl+S)")
    w.export_button = make_button("翻訳MODを書き出す", w.generate, "primary", "ゲーム用の翻訳MODを生成します (Ctrl+E)")
    heading_row.addWidget(w.save_button)
    heading_row.addWidget(w.export_button)
    page.addLayout(heading_row)
    # Language and game version share one framed bar; the main window appends the version controls.
    context_bar = QFrame()
    context_bar.setObjectName('toolbar')
    language_row = QHBoxLayout(context_bar)
    language_row.setContentsMargins(12, 4, 12, 4)
    language_row.setSpacing(8)
    language_label = tag('翻訳先の言語', 'muted')
    language_label.setWordWrap(False)
    language_row.addWidget(language_label)
    w.language_selector = QComboBox()
    w.language_selector.setMinimumWidth(200)
    w.language_selector.setToolTip('言語を切り替えても、ほかの言語で書いた訳は残ります。')
    language_row.addWidget(w.language_selector)
    w.manage_languages = make_button("言語を追加・変更", w.manage_languages_dialog, "secondary")
    language_row.addWidget(w.manage_languages)
    w.language_row = language_row
    w.context_bar = context_bar
    page.addWidget(context_bar)
    w.guidance = tag("項目を選んで翻訳文を入力 → 保存 → 書き出し", "helpText")
    page.addWidget(w.guidance)

    w.translate_page = QWidget()
    translate_layout = QVBoxLayout(w.translate_page)
    w.translate_layout = translate_layout
    translate_layout.setContentsMargins(0, 0, 0, 0)
    translate_layout.setSpacing(4)
    # Focus mode: only the entry being translated, with the few controls needed to keep moving.
    w.focus_bar = QWidget()
    focus_row = QHBoxLayout(w.focus_bar)
    focus_row.setContentsMargins(0, 0, 0, 0)
    w.focus_label = tag("", "muted")
    w.focus_label.setWordWrap(False)
    focus_row.addWidget(w.focus_label, 1)
    w.focus_prev = make_button("前へ", lambda: w.focus_step(-1), "secondary", "Alt+Left")
    w.focus_next = make_button("次へ", lambda: w.focus_step(1), "secondary", "Alt+Right")
    w.focus_exit = make_button("集中モードを終了", lambda: w.set_focus_mode(False), "secondary", "Esc")
    for button in (w.focus_prev, w.focus_next, w.focus_exit):
        focus_row.addWidget(button)
    w.focus_bar.hide()
    translate_layout.addWidget(w.focus_bar)
    search_row = QHBoxLayout()
    w.search_row = search_row
    w.search = QLineEdit()
    w.search.setPlaceholderText("検索：原文 / 翻訳文 / XMLキー")
    w.search.setClearButtonEnabled(True)
    w.search.setAccessibleName("翻訳項目を検索")
    w.status_filter = QComboBox()
    w.status_filter.addItem("すべての項目", "")
    for key, label in statuses.items():
        w.status_filter.addItem(label, key)
    w.status_filter.setMinimumWidth(145)
    search_row.addWidget(w.search, 1)
    search_row.addWidget(w.status_filter)
    w.next_untranslated = make_button("未訳を探す", lambda: select_untranslated(w), "secondary")
    search_row.addWidget(w.next_untranslated)
    w.focus_button = make_button("集中モード", lambda: w.set_focus_mode(True), "secondary", "Ctrl+Shift+F")
    search_row.addWidget(w.focus_button)
    translate_layout.addLayout(search_row)

    # Quick status filters: a short, fixed set with short labels reads better as chips than as a
    # dropdown. The dropdown stays for the longer list of advanced states, and both stay in sync.
    w.chip_bar = QWidget()
    chip_row = QHBoxLayout(w.chip_bar)
    chip_row.setContentsMargins(0, 0, 0, 0)
    chip_row.setSpacing(6)
    w.status_chips = {}
    for key, label in (("", "すべて"), *statuses.items()):
        chip = QPushButton(label)
        chip.setObjectName("chip")
        chip.setCheckable(True)
        chip.setCursor(Qt.PointingHandCursor)
        chip.setFocusPolicy(Qt.TabFocus)
        chip.setProperty("chipLabel", label)
        chip.clicked.connect(lambda _checked=False, k=key: select_status(w, k))
        w.status_chips[key] = chip
        chip_row.addWidget(chip)
    # Shown only while something narrows the list, so an active filter is never silent.
    w.clear_filters_button = QPushButton("×  絞り込みを解除")
    w.clear_filters_button.setObjectName("chipClear")
    w.clear_filters_button.setCursor(Qt.PointingHandCursor)
    w.clear_filters_button.setToolTip("検索・状態・元ファイル・分類の絞り込みをすべて解除します")
    w.clear_filters_button.clicked.connect(lambda: w.clear_filters())
    w.clear_filters_button.hide()
    chip_row.addWidget(w.clear_filters_button)
    chip_row.addStretch(1)
    w.counts = tag("", "counts")
    w.counts.setWordWrap(False)
    chip_row.addWidget(w.counts)
    w.status_filter.currentIndexChanged.connect(lambda _index=0: sync_status_chips(w))
    sync_status_chips(w)
    translate_layout.addWidget(w.chip_bar)
    build_filter_bar(w, translate_layout)
    w.model = None  # Set by caller to keep model and signals in the main module.
    w.proxy = None
    splitter = QSplitter(Qt.Vertical)
    w.editor_splitter = splitter
    w.table = QTableView()
    w.table.setSelectionBehavior(QTableView.SelectRows)
    w.table.setSelectionMode(QTableView.SingleSelection)
    w.table.setAlternatingRowColors(True)
    w.table.setWordWrap(False)
    w.table.verticalHeader().hide()
    w.table.verticalHeader().setDefaultSectionSize(32)
    w.table.setShowGrid(False)
    w.table.horizontalHeader().setHighlightSections(False)
    w.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    w.table.setMinimumHeight(150)
    # The splitter decides the table height; its own size hint must not push the page into scrolling.
    w.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
    # Classification tree (kind > Def type > Def) on the left, entry table on the right.
    w.entry_tree = QTreeWidget()
    w.entry_tree.setObjectName('entryTree')
    w.entry_tree.setHeaderLabel('分類  未訳/全体')
    w.entry_tree.setMinimumWidth(150)
    w.entry_tree.setAccessibleName('分類ツリー')
    w.entry_tree.setUniformRowHeights(True)
    w.entry_tree.setAnimated(False)
    w.entry_tree.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Ignored)
    w.table_splitter = QSplitter(Qt.Horizontal)
    w.table_splitter.addWidget(w.entry_tree)
    w.table_splitter.addWidget(w.table)
    w.table_splitter.setStretchFactor(0, 0)
    w.table_splitter.setStretchFactor(1, 1)
    w.table_splitter.setSizes([270, 860])
    w.table_splitter.setChildrenCollapsible(False)
    splitter.addWidget(w.table_splitter)
    detail = QFrame()
    detail.setObjectName("pane")
    details = QVBoxLayout(detail)
    details.setContentsMargins(16, 12, 16, 12)
    details.setSpacing(8)
    w.key_label = tag("項目を選んでください", "selectedKey")
    w.key_label.setMaximumHeight(26)
    w.key_label.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Preferred)
    details.addWidget(w.key_label)
    editors = QHBoxLayout()
    editors.setContentsMargins(0, 0, 0, 0)
    w.editor_pair_layout = editors
    editors.setSpacing(11)
    left = QVBoxLayout()
    left.setContentsMargins(0, 0, 0, 0)
    left.setSpacing(4)
    source_label = tag("原文  /  English", "eyebrow")
    source_label.setWordWrap(False)
    source_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    left.addWidget(source_label)
    w.english = QPlainTextEdit()
    w.english.setReadOnly(True)
    w.english.setMinimumHeight(60)
    w.english.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Ignored)
    w.english.setAccessibleName("英語原文")
    left.addWidget(w.english)
    editors.addLayout(left, 1)
    right = QVBoxLayout()
    right.setContentsMargins(0, 0, 0, 0)
    right.setSpacing(4)
    w.translation_label = tag("翻訳  /  日本語をここに入力", "eyebrow")
    w.translation_label.setWordWrap(False)
    w.translation_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    right.addWidget(w.translation_label)
    w.japanese = QPlainTextEdit()
    w.japanese.setMinimumHeight(60)
    w.japanese.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Ignored)
    w.japanese.setAccessibleName("日本語訳")
    w.japanese.setPlaceholderText("ここに日本語訳を書いてください…")
    right.addWidget(w.japanese)
    build_editor_aids(w, right)
    editors.addLayout(right, 1)
    build_side_tabs(w, editors)
    details.addLayout(editors, 1)
    # Why a review was refused; shown only then.
    w.review_message = tag("", "reviewError")
    w.review_message.setAccessibleName('確認済みにできない理由')
    w.review_message.hide()
    details.addWidget(w.review_message)
    review_row = QHBoxLayout()
    review_row.setContentsMargins(0, 0, 0, 0)
    review_row.setSpacing(8)
    w.notice = QPlainTextEdit()
    w.notice.setReadOnly(True)
    w.notice.setMinimumHeight(36)
    w.notice.setMaximumHeight(52)
    w.notice.setAccessibleName('翻訳の注意点')
    w.notice.setFocusPolicy(Qt.NoFocus)
    review_row.addWidget(w.notice, 1)
    # Extraction evidence is for developers; it stays folded away until asked for.
    w.notice_details = QPlainTextEdit()
    w.notice_details.setReadOnly(True)
    w.notice_details.setMinimumHeight(36)
    w.notice_details.setMaximumHeight(52)
    w.notice_details.setAccessibleName('抽出の技術的な詳細')
    w.notice_details.setFocusPolicy(Qt.NoFocus)
    w.notice_details.hide()
    review_row.addWidget(w.notice_details, 1)
    buttons = QVBoxLayout()
    buttons.setSpacing(4)
    w.notice_toggle = QPushButton("技術的な詳細")
    w.notice_toggle.setObjectName("secondary")
    w.notice_toggle.setCheckable(True)
    w.notice_toggle.setToolTip("抽出の根拠など、開発者向けの情報を表示します")
    w.notice_toggle.toggled.connect(w.notice_details.setVisible)
    buttons.addWidget(w.notice_toggle)
    w.reviewed = make_button("確認済みにする", w.mark_reviewed, "confirm", "この項目の訳を確認済みにします (Ctrl+Return)")
    buttons.addWidget(w.reviewed)
    review_row.addLayout(buttons)
    details.addLayout(review_row)
    # Header labels no longer soak up spare height, but keep a floor so the notice box can never overlap the editors.
    detail.setMinimumHeight(250)
    splitter.addWidget(detail)
    splitter.setStretchFactor(0, 5)
    splitter.setStretchFactor(1, 2)
    splitter.setSizes([290, 250])
    translate_layout.addWidget(splitter, 1)
    page.addWidget(w.translate_page, 1)
    build_extra_pages(w, page)
    w.views.addWidget(w.editor_page)
    w.views.setCurrentWidget(w.welcome_page)

    w.export_button.setEnabled(False)
    w.manage_languages.setEnabled(False)
    w.save_button.setEnabled(False)
    w.next_untranslated.setEnabled(False)
    w.focus_button.setEnabled(False)
    for b in (w.save_side, w.rescan_side, w.manual_side, w.warnings_side, w.git_side, w.output_side):
        b.setEnabled(False)
    # Keyboard shortcuts also work on welcome page.
    for title, callback, shortcut in (
        ("新規翻訳", w.new_project, "Ctrl+N"),
        ("続きから開く", w.open_project, "Ctrl+O"),
        ("保存", w.save, "Ctrl+S"),
        ("書き出す", w.generate, "Ctrl+E"),
        ("再スキャン", w.rescan, "Ctrl+R"),
    ):
        action = QAction(title, w)
        action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(callback)
        w.addAction(action)
    w.actions = [w.new_button, w.open_button, w.save_side, w.rescan_side,
                 w.manual_side, w.warnings_side, w.git_side, w.output_side, w.manage_languages, w.save_button,
                 w.export_button, w.next_untranslated, w.focus_button]
    w.search.textChanged.connect(w.search_typed)
    w.status_filter.currentIndexChanged.connect(w.filter_changed)
    w.japanese.textChanged.connect(w.edit_detail)
    w.statusBar().showMessage("準備完了  ·  新規プロジェクトから始めてください")


def build_extra_pages(w, page):
    """Progress and export pages; they sit under the heading row and replace the translate page while selected."""
    w.progress_page = QWidget()
    layout = QVBoxLayout(w.progress_page)
    layout.setContentsMargins(0, 8, 0, 0)
    layout.setSpacing(10)
    summary = QHBoxLayout()
    w.progress_big = tag("0%", "h1")
    w.progress_big.setWordWrap(False)
    summary.addWidget(w.progress_big)
    w.progress_summary = tag("", "helpText")
    summary.addWidget(w.progress_summary, 1)
    layout.addLayout(summary)
    w.progress_today = tag("", "muted")
    layout.addWidget(w.progress_today)
    w.progress_scroll = QScrollArea()
    w.progress_scroll.setWidgetResizable(True)
    w.progress_rows_host = QWidget()
    w.progress_rows = QVBoxLayout(w.progress_rows_host)
    w.progress_rows.setContentsMargins(0, 0, 0, 0)
    w.progress_rows.setSpacing(6)
    w.progress_rows.addStretch()
    w.progress_scroll.setWidget(w.progress_rows_host)
    layout.addWidget(w.progress_scroll, 1)
    w.progress_page.hide()
    page.addWidget(w.progress_page, 1)

    w.export_page = QWidget()
    layout = QVBoxLayout(w.export_page)
    layout.setContentsMargins(0, 8, 0, 0)
    layout.setSpacing(10)
    w.export_summary = tag("", "helpText")
    layout.addWidget(w.export_summary)
    w.export_buttons = QVBoxLayout()
    w.export_buttons.setSpacing(8)
    for label, hint, callback, kind in (
        ("保存して書き出す", "作業データとゲーム用 XML を更新します。", w.save, "secondary"),
        ("診断を確認", "抽出と翻訳の診断(QA の警告・エラー)を開きます。", w.show_warnings, "secondary"),
        ("ゲームに導入・更新", "生成した翻訳 MOD をゲームの MOD フォルダーに入れます。", w.install_dialog, "secondary"),
        ("必要 MOD と読み込み順", "依存 MOD と読み込み順を確認します。", w.dependencies_dialog, "secondary"),
        ("隔離コピーでゲームをテスト", "ゲームのコピーで起動して、翻訳が読み込まれるか確認します。", w.launch_test_dialog, "secondary"),
    ):
        # One card per step, numbered in the order a translator normally goes through them.
        card = QFrame()
        card.setObjectName("stepCard")
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(14)
        number = tag(str(w.export_buttons.count() + 1), "stepNumber")
        number.setFixedSize(30, 30)
        number.setAlignment(Qt.AlignCenter)
        row.addWidget(number)
        row.addWidget(tag(hint, "helpText"), 1)
        button = make_button(label, callback, kind)
        button.setMinimumWidth(230)
        row.addWidget(button)
        w.export_buttons.addWidget(card)
    layout.addLayout(w.export_buttons)
    layout.addStretch()
    w.export_page.hide()
    page.addWidget(w.export_page, 1)


def select_untranslated(w):
    if w.proxy is None:
        return
    index = w.status_filter.findData("untranslated")
    if index >= 0:
        w.status_filter.setCurrentIndex(index)
        w.filter_changed()
    if w.proxy.rowCount() > 0:
        w.table.setCurrentIndex(w.proxy.index(0, 0))
        w.japanese.setFocus()


def select_status(w, key):
    """A chip was pressed: drive the status dropdown, which owns the filter state."""
    index = w.status_filter.findData(key) if key else 0
    w.status_filter.setCurrentIndex(max(0, index))
    sync_status_chips(w)


def sync_status_chips(w):
    current = w.status_filter.currentData() or ""
    for key, chip in w.status_chips.items():
        chip.setChecked(key == current)


def small_combo(first, tooltip, minimum=110):
    combo = QComboBox()
    combo.addItem(first, "")
    combo.setToolTip(tooltip)
    combo.setMinimumWidth(minimum)
    combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(8)
    combo.setObjectName('compact')
    return combo


def build_filter_bar(w, layout):
    """Def type / file / flag filters and the two jump buttons, on one compact row under the status chips."""
    w.filter_bar = QWidget()
    row = QHBoxLayout(w.filter_bar)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    w.def_type_filter = small_combo("すべての種類", "Def の種類(ThingDef など)で絞り込みます")
    w.def_type_filter.setAccessibleName("Defの種類で絞り込む")
    w.file_filter = small_combo("すべてのファイル", "元ファイルで絞り込みます", 130)
    w.file_filter.setAccessibleName("元ファイルで絞り込む")
    w.flag_filter = small_combo("すべての印", "メモの印(後で見直す など)で絞り込みます")
    w.flag_filter.setAccessibleName("メモの印で絞り込む")
    w.assignee_filter = small_combo("すべての担当者", "ファイルの担当者で絞り込みます")
    w.assignee_filter.setAccessibleName("担当者で絞り込む")
    w.assignee_filter.hide()  # shown only while the project has assignments
    for combo in (w.def_type_filter, w.file_filter, w.flag_filter, w.assignee_filter):
        row.addWidget(combo, 1)
        combo.currentIndexChanged.connect(w.filter_changed)
    row.addStretch(0)
    w.jump_untranslated = make_button("次の未訳", lambda: w.jump_to_next("untranslated"), "secondary",
                                      "現在の行から次の未訳へ移動します (Ctrl+J)")
    w.jump_review = make_button("次の要確認", lambda: w.jump_to_next("needs-review"), "secondary",
                                "現在の行から次の要確認へ移動します (Ctrl+Shift+J)")
    for button in (w.jump_untranslated, w.jump_review):
        button.setObjectName("compactButton")
    row.addWidget(w.jump_untranslated)
    row.addWidget(w.jump_review)
    layout.addWidget(w.filter_bar)


def build_editor_aids(w, column):
    """Under the translation box: placeholder buttons, a width hint and advisory warnings."""
    w.token_scroll = QScrollArea()
    w.token_scroll.setObjectName("tokenScroll")
    w.token_scroll.setWidgetResizable(True)
    w.token_scroll.setFrameShape(QFrame.NoFrame)
    w.token_scroll.setFixedHeight(34)
    w.token_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    w.token_host = QWidget()
    w.token_row = QHBoxLayout(w.token_host)
    w.token_row.setContentsMargins(0, 0, 0, 0)
    w.token_row.setSpacing(4)
    w.token_scroll.setWidget(w.token_host)
    w.token_scroll.hide()
    w.token_buttons = []
    column.addWidget(w.token_scroll)
    w.hint_label = tag("", "muted")
    w.hint_label.hide()
    w.advice_label = tag("", "advice")
    w.advice_label.hide()
    column.addWidget(w.hint_label)
    column.addWidget(w.advice_label)


def build_side_tabs(w, editors):
    """Preview, suggestions and notes beside the two editors."""
    w.side_tabs = QTabWidget()
    w.side_tabs.setObjectName("sideTabs")
    w.side_tabs.setMinimumWidth(220)
    w.side_tabs.setMaximumWidth(340)
    w.side_tabs.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Ignored)
    w.preview_view = QTextBrowser()
    w.preview_view.setObjectName("richPreview")
    w.preview_view.setOpenLinks(False)
    w.preview_view.setAccessibleName("訳文のプレビュー")
    w.preview_view.setMinimumHeight(40)
    w.side_tabs.addTab(w.preview_view, "プレビュー")

    suggestions = QWidget()
    column = QVBoxLayout(suggestions)
    column.setContentsMargins(0, 4, 0, 0)
    column.setSpacing(4)
    w.suggest_list = QListWidget()
    w.suggest_list.setObjectName("suggestList")
    w.suggest_list.setWordWrap(True)
    w.suggest_list.setAccessibleName("翻訳の候補")
    w.suggest_list.setMinimumHeight(40)
    w.suggest_list.itemActivated.connect(lambda _item: w.insert_selected_suggestion())
    column.addWidget(w.suggest_list, 1)
    buttons = QHBoxLayout()
    buttons.setSpacing(4)
    w.insert_suggestion_button = make_button("入れる", lambda: w.insert_selected_suggestion(), "secondary",
                                             "選んだ候補を訳文に入れます (ダブルクリック / Enter)")
    w.register_term_button = make_button("用語集へ", lambda: w.register_selected_term(), "secondary",
                                         "選んだ用語の候補を用語集に登録します")
    w.apply_identical_button = make_button("同じ原文すべてに適用", lambda: w.apply_identical(), "secondary",
                                           "この訳を、英語がまったく同じ他の項目にも入れます")
    buttons.addWidget(w.insert_suggestion_button)
    buttons.addWidget(w.register_term_button)
    column.addLayout(buttons)
    column.addWidget(w.apply_identical_button)
    w.side_tabs.addTab(suggestions, "候補")

    notes = QWidget()
    column = QVBoxLayout(notes)
    column.setContentsMargins(0, 4, 0, 0)
    column.setSpacing(4)
    w.flag_combo = QComboBox()
    w.flag_combo.setAccessibleName("この項目の印")
    w.flag_combo.setToolTip("あとで探せる印を付けます (Ctrl+K で「後で見直す」)")
    column.addWidget(w.flag_combo)
    w.note_edit = QPlainTextEdit()
    w.note_edit.setObjectName("noteEdit")
    w.note_edit.setPlaceholderText("この項目のメモ(翻訳には出力されません)")
    w.note_edit.setAccessibleName("この項目のメモ")
    column.addWidget(w.note_edit, 1)
    w.side_tabs.addTab(notes, "メモ")
    editors.addWidget(w.side_tabs, 1)
