"""Japanese and English editor labels, independent of target MOD languages."""
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QAbstractButton, QComboBox, QGroupBox, QLabel, QLineEdit, QPlainTextEdit,
                               QTabBar, QTreeWidget, QWidget)

LABELS = {
 '確認済み':'Reviewed','承認済み':'Approved','新しい項目':'New','除外した項目':'Excluded',
 'ガイドをスキップ':'Skip guide',
 '新しく翻訳する MOD を選ぶか、最近のプロジェクトを開いてください。':'Choose a source MOD or open a recent translation project.',
 '翻訳ワークスペース':'Translation workspace',
 'まだプロジェクトを開いていません':'No project open',
 'はじめる':'GET STARTED', '作業メニュー':'WORKSPACE',
 '＋  新しいMODを翻訳':'New translation', '続きから作業する':'Open project',
 'MODを選ぶと進捗が表示されます':'Choose a MOD to see progress',
 '保存する   Ctrl+S':'Save and export   Ctrl+S',
 '元MODの更新を確認':'Rescan source MOD', '翻訳キーを手動追加':'Add manual key',
 '抽出できなかった項目':'Diagnostics and QA', 'Gitにバックアップ':'Browse backups',
 '出力フォルダーを開く':'Open output folder',
 '翻訳後は「MODを書き出す」で\nゲーム用ファイルを更新します。':'Saving also updates the game files. Check diagnostics before installing.',
 'WELCOME  /  翻訳をはじめよう':'WELCOME / START TRANSLATING',
 'RimWorldのMODを、\n日本語で遊べるように。':'Translate your RimWorld MODs\ninto your chosen languages.',
 '元MODを選ぶだけで翻訳項目を自動抽出。\n原文を見ながら選んだ言語へ訳し、ゲーム用の翻訳MODを生成できます。':'Choose a source MOD, edit its text, and export a separate translation MOD.',
 'MODを選ぶ':'Choose a MOD',
 'Steam WorkshopのMODも、手元のフォルダーも選べます。':'Choose Steam Workshop content or a local folder.',
 '選んだ言語へ翻訳':'Translate in your languages',
 '原文と翻訳文を並べて編集。途中保存も自動です。':'Edit source and translation side by side. Your work is autosaved.',
 'ゲーム用に書き出す':'Export for the game',
 '元MODはそのまま。日本語化MODを別に生成します。':'Create a separate translation package for the original MOD.',
 '＋  新しい翻訳を始める':'Start a translation', '保存した翻訳を開く':'Open saved translation',
 'EDITOR  /  日本語化の作業画面':'EDITOR / TRANSLATION WORKSPACE',
 '翻訳する':'Translate', '元MODが選択されていません':'Choose a source MOD',
 '変更を保存':'Save and export', '翻訳MODを書き出す':'Export translation mod',
 '翻訳先の言語':'Target language', '言語を追加・変更':'Manage languages',
 '言語を切り替えても、ほかの言語で書いた訳は残ります。':'Changing the target language preserves all other translations.',
 '項目を選んで翻訳文を入力 → 保存 → 書き出し':'Select text, translate, then save to update the game files.',
 '検索：原文 / 翻訳文 / XMLキー':'Search source, translation or key',
 '翻訳項目を検索':'Search translation entries', 'すべての項目':'All entries',
 '未訳':'Untranslated', '翻訳済み':'Translated', '原文変更':'Source changed',
 '要確認':'Needs review', '削除・旧項目':'Removed', '未訳を探す':'Find untranslated',
 '項目を選んでください':'Select an entry', '項目を選択してください':'Select an entry',
 '原文  /  English':'Source / English', '英語原文':'English source',
 '翻訳  /  日本語をここに入力':'Translation / Enter text here', '日本語訳':'Translation',
 'ここに日本語訳を書いてください…':'Write your translation here…',
 'この項目を確認済みにする':'Mark reviewed',
 '状態':'State', 'キー':'Key', '英語':'English', '日本語':'Translation',
 '新規翻訳':'New translation', '続きから開く':'Open project',
 '保存':'Save', '書き出す':'Export', '再スキャン':'Rescan',
 '既存MODから日本語翻訳プロジェクトを作ります':'Create a separate translation project from a source MOD.',
 'スキャンを中止':'Cancel scan',
 '翻訳するMODを選ぶ':'Choose source MOD', '元MODをどこから読み込みますか？':'Where is the source MOD?',
 'Steam Workshopから選ぶ':'Choose from Steam Workshop', 'PC内のフォルダーから選ぶ':'Choose a local folder',
 '翻訳先の言語を選ぶ':'Choose target languages',
 '翻訳する言語を選んでください（複数選択可）':'Select one or more target languages',
 '最低1言語必要です。後から追加・変更もできます。':'Select at least one language. You can change this later.',
 '29言語すべて選択':'Select all 29 languages', 'すべて選択':'Select all',
 '日本語だけ':'Japanese only', 'この言語で進める':'Use these languages',
 'キャンセル':'Cancel', 'このMODを翻訳する':'Translate this MOD',
 'Steam WorkshopからMODを選ぶ':'Choose a Steam Workshop MOD',
 '翻訳したいMODを選んでください':'Choose a MOD to translate',
 'MOD名またはWorkshop IDで検索':'Search name, ID or author',
 '選択したMODの元ファイルは変更されません。':'The source MOD remains read-only.',
 '取り込み':'Import', '一括置換':'Batch replace', '用語集':'Glossary',
 '履歴と復元':'History and restore', 'ゲームへ導入':'Install to game',
 '元 MOD のプレビュー画像は元作者の著作物です。公開前に使用許諾・ライセンスを確認してください。':'Source preview artwork belongs to its creator. Check permission and licensing before publishing.',
 'RimWorld 翻訳ワークスペース':'RimWorld Translation Workspace',
 '訳':'Tr',
 '翻訳エディター':'Translation Editor',
 '進み具合':'PROGRESS',
 '保存する':'Save',
 'ようこそ':'WELCOME',
 '翻訳プロジェクト':'TRANSLATION PROJECT',
 'プロジェクト':'PROJECT',
 '作業データを保存します (Ctrl+S)':'Save the working data (Ctrl+S)',
 'ゲーム用の翻訳MODを生成します (Ctrl+E)':'Generate the translation MOD for the game (Ctrl+E)',
 '前へ':'Previous',
 '次へ':'Next',
 '集中モードを終了':'Leave focus mode',
 '集中モード':'Focus mode',
 'すべて':'All',
 '検索・状態・元ファイル・分類の絞り込みをすべて解除します':'Clear the search, state, source file and category filters',
 '×  絞り込みを解除':'×  Clear filters',
 'Def の種類(ThingDef など)で絞り込みます':'Filter by Def type (ThingDef etc.)',
 'Defの種類で絞り込む':'Filter by Def type',
 '元ファイルで絞り込みます':'Filter by source file',
 '元ファイルで絞り込む':'Filter by source file',
 'メモの印(後で見直す など)で絞り込みます':'Filter by note flag (Review later etc.)',
 'メモの印で絞り込む':'Filter by note flag',
 'すべての種類':'All Def types',
 'すべてのファイル':'All files',
 'すべての印':'All flags',
 '現在の行から次の未訳へ移動します (Ctrl+J)':'Jump to the next untranslated row (Ctrl+J)',
 '次の未訳':'Next untranslated',
 '次の要確認':'Next needs review',
 '現在の行から次の要確認へ移動します (Ctrl+Shift+J)':'Jump to the next row needing review (Ctrl+Shift+J)',
 'プレビュー':'Preview',
 '候補':'Suggestions',
 'メモ':'Notes',
 'あとで探せる印を付けます (Ctrl+K で「後で見直す」)':'Set a flag to find the row later (Ctrl+K: "Review later")',
 'この項目の印':'Flag for this row',
 'この項目のメモ':'Note for this row',
 'この項目のメモ(翻訳には出力されません)':'Note for this row (never exported)',
 '翻訳の候補':'Translation suggestions',
 '選んだ候補を訳文に入れます (ダブルクリック / Enter)':'Insert the chosen suggestion (double-click / Enter)',
 '入れる':'Insert',
 '選んだ用語の候補を用語集に登録します':'Add the chosen term to the glossary',
 '用語集へ':'To glossary',
 '同じ原文すべてに適用':'Apply to all identical sources',
 'この訳を、英語がまったく同じ他の項目にも入れます':'Also use this translation for every other row with identical English',
 '訳文のプレビュー':'Translation preview',
 '確認済みにできない理由':'Why it cannot be marked reviewed',
 '翻訳の注意点':'Translation notes',
 '抽出の技術的な詳細':'Technical extraction details',
 '技術的な詳細':'Technical details',
 '抽出の根拠など、開発者向けの情報を表示します':'Show developer-facing information such as the extraction evidence',
 '確認済みにする':'Mark reviewed',
 'この項目の訳を確認済みにします (Ctrl+Return)':'Mark this translation reviewed (Ctrl+Return)',
 '印':'Flag',
 '分類ツリー':'Category tree',
 '分類  未訳/全体':'Category  untranslated/total',
 '作業データとゲーム用 XML を更新します。':'Update the working data and the game XML.',
 '保存して書き出す':'Save and export',
 '抽出と翻訳の診断(QA の警告・エラー)を開きます。':'Open the extraction and translation diagnostics (QA warnings and errors).',
 '診断を確認':'Review diagnostics',
 '生成した翻訳 MOD をゲームの MOD フォルダーに入れます。':'Put the generated translation MOD into the game MOD folder.',
 'ゲームに導入・更新':'Install / update in game',
 '依存 MOD と読み込み順を確認します。':'Check dependency MODs and the load order.',
 '必要 MOD と読み込み順':'Required MODs and load order',
 'ゲームのコピーで起動して、翻訳が読み込まれるか確認します。':'Launch a copy of the game to check that the translation loads.',
 '隔離コピーでゲームをテスト':'Test in an isolated game copy',
 '前回の試験出力結果':'Last trial export result',
 '翻訳':'Translate',
 '確認':'Review',
 '進捗':'Progress',
 '書き出し':'Export',
 'すべての担当者':'All assignees',
 'ファイルの担当者で絞り込みます':'Filter by the translator a file is assigned to',
 '担当者で絞り込む':'Filter by assignee',
 '左へスクロール':'Scroll Left',
 '右へスクロール':'Scroll Right',
}


# Pairs seen through two-argument tr(ja, en); they let widgets built in one language be retranslated later.
_RUNTIME: dict[str, str] = {}
_RUNTIME_LIMIT = 5000


def _english(japanese):
    return LABELS.get(japanese) or _RUNTIME.get(japanese)


_PRODUCED: set[str] = set()  # English strings this module handed out; only those are ever mapped back to Japanese


def _japanese(english):
    if english not in _PRODUCED:
        return None
    for table in (LABELS, _RUNTIME):
        for key, value in table.items():
            if value == english:
                return key
    return None


def text(japanese, language='ja', english=None):
    if english is not None and japanese != english and len(_RUNTIME) < _RUNTIME_LIMIT:
        _RUNTIME.setdefault(japanese, english)
    if language == 'ja':
        return japanese
    result = english if english is not None else (_english(japanese) or japanese)
    if result != japanese and len(_PRODUCED) < _RUNTIME_LIMIT * 2:
        _PRODUCED.add(result)
    return result


def retranslate(value, language):
    """``value`` (Japanese or English, whichever it currently is) in ``language``; unknown text stays as it is."""
    if not value:
        return value
    if language == 'ja':
        return _japanese(value) or value
    return _english(value) or value


def _sync(widget, prop, getter, setter, language):
    """Retranslate one text property, remembering the last text this module wrote so that text the program
    changed itself afterwards (a status line, a count) is not overwritten with an older value."""
    current = getter()
    key, shown_key = '_translation_' + prop, '_translation_shown_' + prop
    original = getattr(widget, key, None)
    if original is None or current != getattr(widget, shown_key, original) and current != original:
        original = current
        setattr(widget, key, original)
    if not original:
        return
    target = retranslate(original, language)
    setattr(widget, shown_key, target)
    if target != current:
        setter(target)


def translate_static_ui(window):
    language = window.ui_language
    for widget in [window] + window.findChildren(QWidget):
        properties = [('toolTip', widget.toolTip, widget.setToolTip),
                      ('accessibleName', widget.accessibleName, widget.setAccessibleName)]
        if widget.isWindow():
            properties.append(('windowTitle', widget.windowTitle, widget.setWindowTitle))
        if isinstance(widget, (QLabel, QAbstractButton)):
            properties.append(('text', widget.text, widget.setText))
        elif isinstance(widget, QGroupBox):
            properties.append(('title', widget.title, widget.setTitle))
        elif isinstance(widget, (QLineEdit, QPlainTextEdit)):
            properties.append(('placeholderText', widget.placeholderText, widget.setPlaceholderText))
        for prop, getter, setter in properties:
            _sync(widget, prop, getter, setter, language)
        if isinstance(widget, QTabBar):
            for index in range(widget.count()):
                _sync(widget, f'tabText{index}', lambda i=index: widget.tabText(i),
                      lambda value, i=index: widget.setTabText(i, value), language)
                _sync(widget, f'tabToolTip{index}', lambda i=index: widget.tabToolTip(i),
                      lambda value, i=index: widget.setTabToolTip(i, value), language)
        if isinstance(widget, QTreeWidget):
            header = widget.headerItem()
            for column in range(widget.columnCount()):
                _sync(widget, f'header{column}', lambda c=column: header.text(c),
                      lambda value, c=column: header.setText(c, value), language)
        if isinstance(widget, QComboBox):
            for index in range(widget.count()):
                value = widget.itemText(index)
                target = retranslate(value, language)
                if target != value:
                    widget.setItemText(index, target)
    bar = window.menuBar() if hasattr(window, 'menuBar') else None
    pending = list(bar.actions()) if bar else []
    while pending:
        action = pending.pop()
        value = action.text()
        if retranslate(value, language) != value:
            action.setText(retranslate(value, language))
        if action.menu() is not None:
            pending.extend(action.menu().actions())


_QT_TRANSLATORS: list = []


def install_qt_translator(app, language):
    """Give Qt's own strings (standard buttons, file dialogs, context menus) the UI language.

    Qt ships its translations with PySide6; the editor installs the matching file for Japanese and removes it
    for English, replacing any previous one.
    """
    from PySide6.QtCore import QLibraryInfo, QTranslator
    while _QT_TRANSLATORS:
        app.removeTranslator(_QT_TRANSLATORS.pop())
    if language != 'ja':
        return False
    folder = QLibraryInfo.path(QLibraryInfo.TranslationsPath)
    installed = False
    for name in ('qtbase_ja',):
        translator = QTranslator(app)
        if translator.load(name, folder) and app.installTranslator(translator):
            _QT_TRANSLATORS.append(translator)
            installed = True
    return installed
