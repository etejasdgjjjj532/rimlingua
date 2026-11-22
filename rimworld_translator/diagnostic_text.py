"""Plain-language presentation of extraction diagnostics.

The backend keeps its English developer messages and ``code`` values (tests and logs rely on them). Everything
the user reads goes through :func:`explain`, which returns a short title, one line saying what to do, and the
original text as *technical details* to be folded away in the UI.

One table drives it: ``code -> (regex, ja title, en title, ja action, en action)``. The optional regex pulls
named parameters (``{n}`` and friends) out of the English message so the title can name the file, MOD or class.
"""
import re
from dataclasses import dataclass

_NOTHING = '対応不要です。', 'Nothing to do.'
_MANUAL = 'この効果は自動では判断できません。必要なら手作業で確認してください。', 'This cannot be judged automatically. Check it by hand if it matters.'
_ADD_MODS = ('必要な MOD を入れてからもう一度スキャンしてください。', 'Install the MODs it needs, then scan again.')
_LOAD = ('MOD 側の読み込み設定の問題のことが多く、翻訳には通常影響しません。', 'Usually a problem in the MOD\'s own load settings; it normally does not affect translation.')
_OTHER = ('ゲームの内部用で、翻訳しなくて大丈夫です。', 'Internal to the game; you do not need to translate it.')
_VERIFY = ('ゲームで実際に表示されると確認できるまで、翻訳項目にはしません。', 'It is not made a translation row until you confirm the game shows it.')
_WORDINFO = ('ゲーム独自の形式なので通常の翻訳項目にはなりません。', 'A game-specific format, so it does not become a normal translation row.')
_DLL = ('DLL は実行していません。必要ならMOD作者の案内や手作業で確認してください。', 'The DLL was not run. Check the author\'s notes or look by hand if needed.')
_AFTER = r'(?:.*: )?(?P<n>[^:]+)$'

# code: (regex over the English message or None, ja title, en title, (ja action, en action))
TABLE = {
    'unknown-condition': (r'(?:Unknown load condition|Unexamined condition) (?P<n>[^;:]+)',
                          '読み込み条件「{n}」の意味が分かりませんでした', 'Did not understand the load condition "{n}"',
                          ('その条件の付いた部分は対象から外しています。必要なら MOD 作者の意図を確認してください。',
                           'The part with that condition was left out. Check what the author meant if it matters.')),
    'conditional-context': (r'resolve (?P<n>[^:]+):', '有効な MOD を選ばないと「{n}」の条件を判定できません', 'Cannot judge "{n}" until you choose the active MODs',
                            ('有効な MOD の一覧を選んで、もう一度スキャンしてください。', 'Choose the active MOD list and scan again.')),
    'conditional-assumed': (None, '有効な MOD の一覧が不明なので、入っている拡張などを有効とみなしました', 'The active MOD list is unknown, so installed expansions were assumed active',
                            ('正確にしたいときは有効な MOD を選んでスキャンし直してください。', 'To be exact, choose the active MODs and rescan.')),
    'load-path': (r'folder: (?P<n>.+)$', '読み込みフォルダーの指定が使えません: {n}', 'A load folder setting cannot be used: {n}', _LOAD),
    'missing-folder': (r'missing: (?P<n>.+)$', 'LoadFolders.xml が指すフォルダーがありません: {n}', 'A folder named in LoadFolders.xml does not exist: {n}', _LOAD),
    'scan-reused': (None, '前回から変更がないため、前回のスキャン結果をそのまま使いました', 'Nothing changed since the last scan, so its result was reused',
                    ('やり直したいときは、ファイルやスキャンの条件を変えてからもう一度スキャンしてください。', 'To re-extract, change a file or the scan settings and scan again.')),
    'version-fallback': (None, 'LoadFolders.xml にこのゲーム版の指定がないため、標準のフォルダーを読みました', 'LoadFolders.xml has nothing for this game version, so the default folders were read',
                         ('この版の訳が足りなければ、他の版の指定も確認してください。', 'If this version looks incomplete, check the other versions too.')),
    'loadfolders': (None, 'LoadFolders.xml を読み取れませんでした', 'Could not read LoadFolders.xml',
                    ('ファイルが壊れていないか確認してください。', 'Check that the file is not damaged.')),
    'about': (None, 'About.xml を読み取れませんでした', 'Could not read About.xml', ('MOD の About/About.xml を確認してください。', 'Check the MOD\'s About/About.xml.')),
    'xml': (r'^(?P<n>[^:]+):', 'XML ファイルを読み取れませんでした: {n}', 'Could not read an XML file: {n}',
            ('その MOD ファイルが壊れていないか確認してください。', 'Check that the MOD file is not damaged.')),
    'xml-root': (_AFTER, 'ルート要素が Defs ではありません: {n}', 'The top element is not Defs: {n}', _NOTHING),
    'patch-success': (None, 'パッチの動作モードが分かりませんでした', 'Did not understand a patch\'s success mode', _MANUAL),
    'patch-value': (None, 'パッチに必要な内容（値・操作）が足りません', 'A patch is missing a value or operation', _MANUAL),
    'patch-xpath': (None, 'パッチの検索指定（XPath）が使えません', 'A patch\'s XPath cannot be used', _MANUAL),
    'patch-context': (None, 'パッチの対象がスキャン範囲に見つかりません', 'A patch\'s target is not in the scanned files', _ADD_MODS),
    'patch-unsupported': (None, 'このアプリが扱えない種類のパッチがあります', 'A kind of patch this app does not handle', _MANUAL),
    'patch-order': (None, 'パッチの挿入順の指定が分かりませんでした', 'Did not understand a patch\'s insert order', _MANUAL),
    'patch-root': (None, 'パッチはルート要素を置換・削除できません', 'A patch tried to replace or remove the root element', _MANUAL),
    'inheritance': (r'inheritance (?P<n>[^:]+):', '継承元の定義「{n}」が見つかりません', 'The parent definition "{n}" was not found',
                    ('その定義を持つ前提 MOD を入れてスキャンし直すと解決することがあります。', 'Installing the prerequisite MOD that defines it and rescanning often fixes this.')),
    'invalid-key': (_AFTER, '使えないキーのため飛ばしました: {n}', 'Skipped a key that cannot be used: {n}', _NOTHING),
    'non-localizable-field': (r'excluded: (?P<n>[^:]+):', 'ゲーム内部用の項目なので除外しました: {n}', 'Left out because it is internal to the game: {n}', _OTHER),
    'internal-value': (r'extracted: (?P<n>.+?) = ', '内部用の値に見えるため、翻訳項目にしていません: {n}', 'Looks like an internal value, so it is not a translation row: {n}',
                       ('ゲームで実際に表示される文章だと確認できたときだけ、手動でキーを追加してください。', 'Add a key by hand only after you confirm the game really shows it.')),
    'duplicate-identical': (r'once: (?P<n>.+?) \(', '同じキーが重複していますが、英文が同じなので1つにまとめました: {n}', 'The same key appears twice with the same English, so it was kept once: {n}', _NOTHING),
    'duplicate': (r'blocked: (?P<n>.+?) \(', '同じキーが重複していて英文が違うため、この項目は出力しません: {n}', 'The same key appears twice with different English, so this row is not exported: {n}',
                  ('どちらがゲームで使われるか元 MOD の重複を確認してから、スキャンし直してください。', 'Check which definition the game uses, then rescan.')),
    'unnamed': (_AFTER, '名前のない定義（または抽象定義）を飛ばしました: {n}', 'Skipped a definition with no name (or an abstract one): {n}', _NOTHING),
    'unknown-field': (r'schema: (?:.+?): (?P<n>[^:]+)$', '未検証の候補: {n}', 'Unverified candidate: {n}',
                      ('元ファイルを見て、ゲームで表示される文章か確認してください。確認できるまで翻訳項目にはしません。',
                       'Look at the source file and check the game shows this text. It stays out of the translation rows until confirmed.')),
    'list-skipped': (_AFTER, 'リスト形式の項目を飛ばしました: {n}', 'Skipped a list item: {n}', _NOTHING),
    'unresolved-class': (r'Class (?P<c>.+?) not found; reading (?P<n>.+) as (?P<b>.+)$', 'クラス「{c}」の定義が見つからないため、{b} として読みました',
                         'Class "{c}" was not found, so it was read as {b}',
                         ('そのクラス独自の項目は確認できません。必要な MOD や DLL を入れてスキャンし直してください。', 'Fields only that class defines cannot be checked. Install the MOD or DLL and rescan.')),
    'keyed-root': (None, 'Keyed ファイルの形式が違います（LanguageData ではありません）', 'A Keyed file has the wrong layout (not LanguageData)', _NOTHING),
    'nested-keyed': (r'skipped: (?:.+?): (?P<n>[^:]+)$', '入れ子になった Keyed 項目を飛ばしました: {n}', 'Skipped a nested Keyed entry: {n}', _NOTHING),
    'legacy-catalog': (r'folder: (?P<n>[^;]+);', '旧形式のカタログで、Def の種類をファイル名から推測しました: {n}', 'An old-style catalog; the Def type was guessed from the file name: {n}',
                       ('推測が合っているか、翻訳項目を見て確認してください。', 'Check the guess by looking at the translation rows.')),
    'strings-unsupported': (_AFTER, '対応していない形式のテキスト資料を除外しました: {n}', 'Left out a text resource in an unsupported format: {n}', _WORDINFO),
    'strings-read': (r'^(?P<n>[^:]+):', 'Strings ファイルを読み取れませんでした: {n}', 'Could not read a Strings file: {n}', ('ファイルが壊れていないか確認してください。', 'Check that the file is not damaged.')),
    'wordinfo-unsupported': (_AFTER, 'WordInfo 資料は対応していないため除外しました: {n}', 'Left out a WordInfo resource this app does not support: {n}', _WORDINFO),
    'wordinfo-gender-unsupported': (_AFTER, 'WordInfo の性別資料は対応していないため除外しました: {n}', 'Left out WordInfo gender data, which is not supported: {n}', _WORDINFO),
    'wordinfo-lut-unverified': (_AFTER, 'WordInfo の対応表らしいファイルは意味が未確認のため除外しました: {n}', 'A file that may be a WordInfo lookup table was left out because its meaning is unverified: {n}', _WORDINFO),
    'dll-text': (r'^(?P<n>[^:]+):', 'この DLL はゲーム中に文章や定義を作る可能性があります: {n}', 'This DLL may create text or definitions while the game runs: {n}',
                 ('DLL 内の文章は自動では拾えません。MOD 作者の案内や Keyed を確認してください。', 'Text inside a DLL is not picked up automatically. Check the author\'s notes or the Keyed files.')),
    'dll-translate-candidate': (r"key (?P<n>'[^']*'|\"[^\"]*\")", 'DLL の中に翻訳キーらしき文字列がありました（未検証）: {n}', 'Found something that looks like a translation key inside a DLL (unverified): {n}', _VERIFY),
    'dll-il-unverified': (r'unavailable: (?P<n>[^:]+):', 'DLL の中身を調べられませんでした: {n}', 'Could not inspect inside a DLL: {n}', _DLL),
    'metadata': (r'^(?P<n>[^:]+): metadata', 'DLL の型情報を読み取れませんでした: {n}', 'Could not read a DLL\'s type information: {n}',
                 ('型を確認できない項目は未検証のまま残ります。', 'Fields that need that type stay unverified.')),
    'warnings-omitted': (r'^(?P<n>\d+) additional', '表示しきれない診断がほかに {n} 件あります', '{n} more diagnostics are not shown',
                         ('元の MOD で気になる箇所があれば直接確認してください。', 'Look at the source MOD directly if something seems off.')),
    'missing-dependency': (r'not installed: (?P<n>.+?); ', '前提 MOD が入っていません: {n}', 'Prerequisite MODs are not installed: {n}',
                           ('リストの MOD を入れるか購読してから、もう一度スキャンしてください。', 'Install or subscribe to the listed MODs, then scan again.')),
    'dependency-version-unverified': (r'Prerequisite (?P<n>.+?) does not', '前提 MOD「{n}」がこのゲーム版に対応しているか分かりません', 'It is not known that the prerequisite "{n}" supports this game version',
                                      ('書き出す前に、その MOD が対応しているか確認してください。', 'Check that MOD supports this version before exporting.')),
    'dependency-load-after-unused': (None, '読み込み順だけに使う MOD は、項目の確認には使っていません', 'MODs listed only for load order were not used to check fields',
                                     ('それらの MOD だけが定義する項目は未検証のままです。', 'Fields only those MODs define stay unverified.')),
    'dependency-unreadable': (r'read: (?P<n>.+)\.$', '読み取れない MOD フォルダーがあります: {n}', 'Some MOD folders could not be read: {n}',
                              ('フォルダーのパスを短くするか権限を確認して、もう一度スキャンしてください。', 'Shorten the folder path or check permissions, then scan again.')),
    'game-folder-rejected': (r'Game folder (?P<n>.+?) says', 'このゲームフォルダーは使えませんでした: {n}', 'This game folder could not be used: {n}',
                             ('そのゲーム版をコピーし直すか、ゲームの一覧から外してください。', 'Copy that game version again or remove the folder from the game list.')),
    'game-version-context-unverified': (None, 'この版に合うゲーム本体が見つからないため、型の確認は未検証です', 'No matching game for this version was found, so field types are unverified',
                                        ('この版のゲームを登録してから、もう一度スキャンしてください。', 'Add that game version, then scan again.')),
    'invalid-package': (r'ID: (?P<n>.+)$', 'packageId の形式が正しくありません: {n}', 'A packageId is not in a valid format: {n}', _NOTHING),
    'condition-file-limit': (None, '条件の調査が多すぎて途中で打ち切りました', 'Condition checking stopped early because there were too many files', _NOTHING),
    'condition-xml': (None, '条件の調査中に XML を読めませんでした', 'Could not read an XML file while checking conditions', _NOTHING),
    'findmod-context': (None, 'FindMod の MOD 名から packageId を特定できません', 'Cannot tell which packageId a FindMod name refers to', _ADD_MODS),
    'findmod-ambiguous-name': (None, 'FindMod の MOD 名が複数の packageId に当てはまります', 'A FindMod name matches more than one packageId', _MANUAL),
    'scenario-limit': (None, '有効な MOD の組み合わせが多すぎて、一部は調べていません', 'There are too many MOD combinations, so some were not examined', _NOTHING),
    'dependency-context-unverified': (None, '前提 MOD や読み込み順の確認は、まだ検証されていません', 'Prerequisite MODs and load order have not been verified', _NOTHING),
}

# Raw warnings that carry no code (project.warnings, schema warnings): recognised by their text.
_CODELESS = [(re.compile('additional distinct warnings omitted'), 'warnings-omitted'),
             (re.compile(': metadata unavailable:'), 'metadata')]
_JAPANESE = re.compile('[ぁ-んァ-ン一-龥]')
_GENERIC = ('確認が必要な診断があります', 'A diagnostic needs a look',
            ('詳しい内容は「技術的な詳細」を開いて確認してください。', 'Open "Technical details" for the full text.'))
TECHNICAL_LABEL = ('技術的な詳細', 'Technical details')
_COMPILED = {code: re.compile(item[0]) if item[0] else None for code, item in TABLE.items()}


@dataclass(frozen=True)
class PlainDiagnostic:
    code: str
    title: str
    action: str
    technical: str


class _Params(dict):
    def __missing__(self, key):
        return '…'


def known_codes():
    return tuple(TABLE)


def _text(message, code, suggestion):
    lines = [f'code: {code}'] if code else []
    return '\n'.join(lines + [str(part) for part in (message, suggestion) if part])


def explain(diagnostic, language='ja') -> PlainDiagnostic:
    """The plain title, one-line next step and folded technical text for one diagnostic dict."""
    ja = language == 'ja'
    message = str(diagnostic.get('message') or '')
    suggestion = str(diagnostic.get('suggestion') or '')
    code = diagnostic.get('code') or next((c for pattern, c in _CODELESS if pattern.search(message)), '')
    technical = _text(message, code, suggestion)
    if code in TABLE:
        regex = _COMPILED[code]
        found = regex.search(message) if regex else None
        params = _Params({k: v for k, v in (found.groupdict() if found else {}).items() if v})
        _pattern, title_ja, title_en, (action_ja, action_en) = TABLE[code]
        return PlainDiagnostic(code, (title_ja if ja else title_en).format_map(params),
                               action_ja if ja else action_en, technical)
    if _JAPANESE.search(message):
        # Already plain (QA findings and the like): show as written.
        return PlainDiagnostic(code, message, suggestion, '')
    title, title_en, (action_ja, action_en) = _GENERIC
    return PlainDiagnostic(code, title if ja else title_en, action_ja if ja else action_en, technical)


def technical_label(language='ja'):
    return TECHNICAL_LABEL[0] if language == 'ja' else TECHNICAL_LABEL[1]
