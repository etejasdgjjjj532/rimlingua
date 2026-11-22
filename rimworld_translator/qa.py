"""Conservative, actionable translation checks; semantic checks are warnings."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import re

from .core import Entry, Project, TOKENS
from .languages import validate_language
from .field_semantics import entry_nonlocalizable_reason


@dataclass(frozen=True)
class QaIssue:
    code: str
    severity: str
    message: str
    entry_id: str
    suggestion: str = ""


# Recognize rich text rather than treating arbitrary <words> as markup.
_PAIRED_TAGS = {"b", "i", "u", "s", "color", "size", "material", "sub", "sup", "link", "align", "font", "style", "noparse"}
_SINGLE_TAGS = {"br", "quad", "sprite", "space", "page"}
_REQUIRED_ATTRIBUTE = {"color", "size", "material", "link", "align", "font", "style"}
_TAG = re.compile(r"<\s*(/?)\s*([A-Za-z][A-Za-z0-9-]*)([^<>]*)>")
_TAG_START = re.compile(r"<\s*/?\s*([A-Za-z][A-Za-z0-9-]*)\b")
_ESCAPES = re.compile(r"\\(?:n|r|t|\\)")
_GRAMMAR_TOKENS = re.compile(r"\[[^\[\]\r\n]+\]")
# English inflection that Japanese does not mark: gender pronouns, articles and conditional wording.
# Leaving one out is a normal translation choice; adding one the source lacks, or dropping a name or number, is not.
_INFLECTION = re.compile(r"(?:_|^[\[{])(?:pronoun|possessive|objective|definite|indefinite)\b|\?", re.I)


def _droppable(token: str) -> bool:
    return _INFLECTION.search(token) is not None


def grammar_rule_prefix(entry: Entry) -> str:
    """Return the immutable source prefix for a DefInjected rulesStrings item."""
    if entry.kind != 'DefInjected' or 'rulesStrings' not in entry.key.split('.')[1:-1]:
        return ''
    left, separator, _ = entry.english.partition('->')
    return left + separator if separator else ''


def _markup(text: str) -> tuple[Counter, str]:
    stack = []
    openings = Counter()
    spans = []
    for match in _TAG.finditer(text):
        closing, name, attributes = match.groups()
        name = name.casefold()
        if name not in _PAIRED_TAGS | _SINGLE_TAGS:
            continue
        spans.append((match.start(), match.end()))
        attributes = attributes.strip()
        self_closing = attributes.endswith("/")
        attributes = attributes.removesuffix("/").strip()
        if closing:
            if attributes or name in _SINGLE_TAGS or not stack or stack[-1] != name:
                return openings, f"閉じタグ </{name}> の位置または対応が不正です"
            stack.pop()
            continue
        if name in _PAIRED_TAGS and self_closing:
            return openings, f"<{name}> は対応する閉じタグが必要です"
        if name in _REQUIRED_ATTRIBUTE and not attributes.startswith("="):
            return openings, f"<{name}> の属性値がありません"
        if attributes.startswith("="):
            value = attributes[1:].strip().strip("\"'")
            if not value:
                return openings, f"<{name}> の属性値がありません"
            attributes = "=" + value.casefold()
        else:
            attributes = re.sub(r"\s+", " ", attributes)
        openings[(name, attributes)] += 1
        if name in _PAIRED_TAGS and not self_closing:
            stack.append(name)
    for match in _TAG_START.finditer(text):
        name = match.group(1).casefold()
        if name in _PAIRED_TAGS | _SINGLE_TAGS and not any(start <= match.start() < end for start, end in spans):
            return openings, f"<{name}> のタグが途中で切れています"
    if stack:
        return openings, f"閉じタグ </{stack[-1]}> がありません"
    return openings, ""


def _term_present(text: str, term: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(term.casefold()) + r"(?!\w)", text.casefold()) is not None


def _target_term_present(text: str, term: str) -> bool:
    # CJK terminology commonly occurs without spaces between neighboring words.
    if any("\u2e80" <= character <= "\u9fff" or "\uac00" <= character <= "\ud7a3"
           or "\uf900" <= character <= "\ufaff" for character in term):
        return term.casefold() in text.casefold()
    return _term_present(text, term)


def qa_entry(entry: Entry, translation: str | None = None, glossary: dict[str, str] | None = None) -> list[QaIssue]:
    """Check one nonempty translation.

    Placeholder/tag errors can block export. Terminology, line breaks, whitespace
    and very short text are advisory heuristics, not proof of a mistranslation.
    Only recognized rich-text tags are interpreted; arbitrary angle text is valid.
    """
    translation = entry.japanese if translation is None else translation
    if not translation.strip():
        return []
    issues = []

    def add(code: str, severity: str, message: str, suggestion: str = "") -> None:
        issues.append(QaIssue(code, severity, message, entry.id, suggestion))

    unsafe_reason = entry_nonlocalizable_reason(entry)
    if unsafe_reason:
        add('nonlocalizable', 'error', '内部データのため翻訳出力できません: ' + unsafe_reason,
            '保存された原文・訳文・承認状態は保持しますが、編集と出力の対象にはできません')

    prefix = grammar_rule_prefix(entry)
    if prefix:
        if not translation.startswith(prefix):
            add('rules_prefix', 'error', f'文法ルールの {prefix} を原文どおり保持し、右側のみ翻訳してください',
                f'{prefix} は変更せず、右側のみ翻訳してください')
        expected_rules, actual_rules = Counter(_GRAMMAR_TOKENS.findall(entry.english)), Counter(_GRAMMAR_TOKENS.findall(translation))
        missing_rules = [t for t in (expected_rules - actual_rules).elements() if not _droppable(t)]
        if missing_rules or actual_rules - expected_rules:
            add('grammar_tokens', 'error', '文法ルールの [識別子] の種類または個数が一致しません',
                '原文の [PAWN_nameDef] 等の文法トークンをそのまま残してください')
        elif expected_rules != actual_rules:
            add('inflection_dropped', 'warning', '性別・冠詞などの文法トークンが訳文にありません(日本語では省略可)',
                ', '.join((expected_rules - actual_rules).elements()))

    if '{' in entry.english or '{' in translation:
        expected_tokens, actual_tokens = Counter(TOKENS.findall(entry.english)), Counter(TOKENS.findall(translation))
        if expected_tokens != actual_tokens:
            missing = [t for t in (expected_tokens - actual_tokens).elements() if not _droppable(t)]
            dropped = [t for t in (expected_tokens - actual_tokens).elements() if _droppable(t)]
            extra = list((actual_tokens - expected_tokens).elements())
            detail = []
            if missing:
                detail.append("不足: " + ", ".join(missing))
            if extra:
                detail.append("余分: " + ", ".join(extra))
            if missing or extra:
                add("placeholders", "error", "プレースホルダーの種類または個数が一致しません。" + " / ".join(detail), " ".join(missing))
            if dropped:
                add("inflection_dropped", "warning", "性別・冠詞などの置換トークンが訳文にありません(日本語では省略可): " + ", ".join(dropped))
    if '<' in entry.english or '<' in translation:
        source_tags, source_error = _markup(entry.english)
        target_tags, target_error = _markup(translation)
        if target_error:
            add("markup", "error", target_error, "元の英語と同じタグを対応する閉じタグとともに残してください")
        elif source_error:
            add("source_markup", "warning", "元の英語に不正なタグがあります: " + source_error)
        elif source_tags != target_tags:
            add("markup", "error", "元の英語と訳のタグ、属性値、または個数が一致しません", "元の英語のタグと属性値を残してください")
    if '\\' in entry.english or '\\' in translation:
        if Counter(_ESCAPES.findall(entry.english)) != Counter(_ESCAPES.findall(translation)):
            add("escapes", "warning", "\\n / \\r / \\t / \\\\ のエスケープ表記が一致しません", "意図した改行やタブの表記になっているか確認してください")
    if entry.english.replace("\r\n", "\n").count("\n") != translation.replace("\r\n", "\n").count("\n"):
        add("newlines", "warning", "実際の改行の数が元の英語と異なります", "ゲーム内での行分けを確認してください")
    source_edge = (entry.english[:len(entry.english) - len(entry.english.lstrip())], entry.english[len(entry.english.rstrip()):])
    target_edge = (translation[:len(translation) - len(translation.lstrip())], translation[len(translation.rstrip()):])
    if source_edge != target_edge:
        add("whitespace", "warning", "先頭または末尾の空白が元の英語と異なります", "不要な空白なら削除してください")
    if len(entry.english)>=80:
        source_visible = _TAG.sub("", TOKENS.sub("", entry.english)).strip()
        target_visible = _TAG.sub("", TOKENS.sub("", translation)).strip()
        if len(source_visible) >= 80 and len(target_visible) < max(4, len(source_visible) * 0.06):
            add("truncation", "warning", "長い英語に対して訳が極端に短くなっています", "文の途中で切れていないか確認してください")
    for source_term, expected in (glossary or {}).items():
        if source_term.strip() and expected.strip() and _term_present(entry.english, source_term) and not _target_term_present(translation, expected):
            add("glossary", "warning", f"用語集の訳語が見つかりません: {source_term} → {expected}", expected)
    return issues


def qa_project(project: Project, language: str | None = None) -> list[QaIssue]:
    """Run entry checks and surface equal-English/different-translation candidates."""
    language = language or project.language
    validate_language(language)
    if language not in project.languages:
        raise ValueError(f"プロジェクトで選択していない言語です: {language}")
    issues = []
    same_source: dict[str, list[tuple[Entry, str]]] = defaultdict(list)
    same_translation: dict[str, list[Entry]] = defaultdict(list)
    stored = project.translations.get(language, {})
    for entry in project.entries:
        translation = entry.japanese if language == project.language else stored.get(entry.id, "")
        if entry.stale or entry.blocked or not translation.strip():
            continue
        issues.extend(qa_entry(entry, translation, getattr(project, "glossary", {})))
        same_source[entry.english].append((entry, translation))
        same_translation[translation.strip()].append(entry)
    for candidates in same_source.values():
        if len({translation for _, translation in candidates}) > 1:
            for entry, _ in candidates:
                issues.append(QaIssue("inconsistent_translation", "warning", "同じ英語に異なる訳があります。文脈に応じた使い分けか確認してください。", entry.id))
    for candidates in same_translation.values():
        # Short labels often legitimately share a translation; limit this noisy
        # check to full sentences/descriptions with different source text.
        if len({entry.english for entry in candidates}) > 1 and all(len(entry.english.strip()) >= 40 for entry in candidates):
            for entry in candidates:
                issues.append(QaIssue("duplicate_translation", "warning", "異なる長い英語に同じ訳があります。コピーした訳が残っていないか確認してください。", entry.id))
    return issues


# --- Placeholder helper, length hints, style checks and the pre-export run ------------------------------------

_TOKEN_SCAN = re.compile(
    r"(?P<tag><\s*/?\s*(?:" + "|".join(sorted(_PAIRED_TAGS | _SINGLE_TAGS)) + r")\b[^<>]*>)"
    r"|(?P<brace>\{(?:\d+|[A-Za-z_]\w*)(?:[^{}]*)\})"
    r"|(?P<grammar>\[[^\[\]\r\n]+\])"
    r"|(?P<escape>\\(?:n|r|t|\\))", re.I)


def required_tokens(text: str) -> list[str]:
    """Placeholders, rich-text tags, grammar identifiers and \\n style escapes of ``text``, in source order.

    These are the parts a translator must carry over unchanged; the editor can offer them as insert buttons.
    """
    return [match.group(0) for match in _TOKEN_SCAN.finditer(text)]


def missing_tokens(entry: Entry, translation: str) -> list[str]:
    """Tokens of the English that the translation lacks (repeats counted); droppable inflection tokens are ignored."""
    gap = Counter(required_tokens(entry.english)) - Counter(required_tokens(translation))
    return [token for token in gap.elements() if not _droppable(token)]


def token_palette(entry: Entry, translation: str = "") -> list[tuple[str, int, int]]:
    """Insert-button model: (token, how many are still missing, how many the English has), in source order."""
    wanted = Counter(required_tokens(entry.english))
    have = Counter(required_tokens(translation))
    return [(token, max(0, count - have[token]), count) for token, count in wanted.items()]


def insert_token(text: str, token: str, position: int | None = None) -> tuple[str, int]:
    """Insert ``token`` at ``position`` (default: the end); returns the new text and the cursor after the token."""
    position = len(text) if position is None else max(0, min(position, len(text)))
    return text[:position] + token + text[position:], position + len(token)


def display_width(text: str) -> int:
    """Width in half-width cells: full-width and wide characters count 2, everything else 1."""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(character) in "WF" else 1 for character in text)


@dataclass(frozen=True)
class LengthHint:
    width: int
    limit: int
    over: bool


_SHORT_FIELD_LIMIT = 24


def _visible(text: str) -> str:
    return _TAG.sub("", TOKENS.sub("", text)).strip()


def length_hint(entry: Entry, translation: str) -> LengthHint | None:
    """A width guide for short fields (button and tab labels, item names); None for sentences.

    A short English label is usually drawn in a fixed-size button or list cell, so a Japanese text much
    wider than the English is likely to be cut off. The limit is advisory, never an export error.
    """
    source = _visible(entry.english)
    if not source or len(source) > _SHORT_FIELD_LIMIT or "\n" in source or source.endswith((".", "!", "?")):
        return None
    width = display_width(_visible(translation))
    limit = max(12, len(source) * 2 + 8)
    return LengthHint(width, limit, width > limit)


_FULL_ALNUM = re.compile("[０-９Ａ-Ｚａ-ｚ]")
_HALF_KANA = re.compile("[｡-ﾟ]")


def _same_as_source(entry: Entry, translation: str) -> bool:
    visible = _visible(entry.english)
    return (translation.strip() == entry.english.strip()
            and len(re.findall("[A-Za-z]", visible)) >= 3)


def qa_extra(entry: Entry, translation: str | None = None) -> list[QaIssue]:
    """Advisory style checks: full/half-width mixing, half-width kana, and a translation left as the English."""
    translation = entry.japanese if translation is None else translation
    if not translation.strip():
        return []
    issues = []
    body = _TAG.sub("", TOKENS.sub("", translation))
    if _FULL_ALNUM.search(body) and re.search("[0-9A-Za-z]", body):
        issues.append(QaIssue("width_mixing", "warning", "全角の英数字と半角の英数字が混在しています", entry.id,
                              "どちらかに統一してください(数字は半角が一般的です)"))
    if _HALF_KANA.search(translation):
        issues.append(QaIssue("halfwidth_kana", "warning", "半角カナが含まれています", entry.id, "全角カナに直してください"))
    if _same_as_source(entry, translation):
        issues.append(QaIssue("same_as_source", "warning", "訳が英語の原文のままです", entry.id))
    return issues


_TERMINATORS = "。！？!?…」』）)"
_POLITE = re.compile(r"(?:です|ます|ません|でした|ました|ください|でしょう|ましょう)[0-9０-９]*$")
# Majority and minority are only meaningful with enough sentences.
_STYLE_MIN_ROWS, _STYLE_MAJORITY = 5, 0.75


def _translated_pairs(project: Project, language: str | None):
    language = language or project.language
    if language not in project.languages:
        raise ValueError(f"プロジェクトで選択していない言語です: {language}")
    stored = project.translations.get(language, {})
    for entry in project.entries:
        translation = entry.japanese if language == project.language else stored.get(entry.id, "")
        yield entry, translation


def _minority(labelled: list[tuple[Entry, str]]) -> list[Entry]:
    if len(labelled) < _STYLE_MIN_ROWS:
        return []
    counts = Counter(label for _, label in labelled)
    label, count = counts.most_common(1)[0]
    if count / len(labelled) < _STYLE_MAJORITY or count == len(labelled):
        return []
    return [entry for entry, mine in labelled if mine != label]


def sentence_style_issues(project: Project, language: str | None = None) -> list[QaIssue]:
    """Rows that break the project's prevailing sentence ending or です/ます versus だ/である style.

    Only sentences are compared (English ending in . ! ?), and only when one style clearly dominates.
    """
    ending, style = [], []
    for entry, translation in _translated_pairs(project, language):
        text = translation.strip()
        if entry.stale or entry.blocked or entry.excluded or not text or not entry.english.strip().endswith((".", "!", "?")):
            continue
        closed = text.endswith(tuple(_TERMINATORS))
        ending.append((entry, "closed" if closed else "open"))
        if text.endswith("。"):
            style.append((entry, "polite" if _POLITE.search(text.rstrip("。").rstrip()) else "plain"))
    issues = [QaIssue("sentence_ending", "warning", "他の文は句点などで終わっていますが、この訳は文末が閉じていません", entry.id,
                      "文末の句読点を揃えてください") for entry in _minority(ending)]
    majority = Counter(label for _, label in style).most_common(1)
    labels = {entry.id: label for entry, label in style}
    for entry in _minority(style):
        # The label comes from the translation that was checked, which is not entry.japanese for another language.
        mine = "です・ます調" if labels[entry.id] == "polite" else "だ・である調"
        issues.append(QaIssue("style_mixing", "warning", f"文体が混在しています(この訳は{mine}、多数派は{'です・ます調' if majority[0][0] == 'polite' else 'だ・である調'})",
                              entry.id, "文体を揃えてください"))
    return issues


def _skippable(entry: Entry) -> bool:
    return entry.stale or entry.blocked or entry.excluded or bool(entry_nonlocalizable_reason(entry))


def untranslated_rows(project: Project, language: str | None = None) -> list[Entry]:
    """Rows with no translation, or whose translation is still the English text."""
    return [entry for entry, translation in _translated_pairs(project, language)
            if not _skippable(entry) and entry.english.strip()
            and (not translation.strip() or _same_as_source(entry, translation))]


def _changed(project: Project, entry: Entry, language: str) -> bool:
    if language == project.language:
        return entry.changed
    return bool(project.language_states.get(language, {}).get(entry.id, {}).get("changed"))


def outdated_rows(project: Project, language: str | None = None) -> list[Entry]:
    """Translated rows whose English changed after a MOD update; the old English is ``entry.previous_english``."""
    language = language or project.language
    return [entry for entry, translation in _translated_pairs(project, language)
            if translation.strip() and not entry.stale and _changed(project, entry, language)]


def outdated_issues(project: Project, language: str | None = None) -> list[QaIssue]:
    """``outdated_rows`` as issues carrying the old English, so the translator sees what changed."""
    return [QaIssue("source_changed", "warning",
                    "MOD の更新で英文が変わりました。古い訳のままです。" + (f"(旧: {entry.previous_english})" if entry.previous_english else ""),
                    entry.id, "訳を見直してから確認済みにしてください") for entry in outdated_rows(project, language)]


def reviewed_with_errors(project: Project, language: str | None = None) -> list[QaIssue]:
    """QA errors on rows that are marked reviewed. Such a row does not count as reviewed until fixed."""
    language = language or project.language
    states = project.language_states.get(language, {})
    found = []
    for entry, translation in _translated_pairs(project, language):
        reviewed = entry.reviewed if language == project.language else states.get(entry.id, {}).get("reviewed", False)
        if reviewed and translation.strip():
            found.extend(issue for issue in qa_entry(entry, translation, project.glossary) if issue.severity == "error")
    return found


def review_blockers(entry: Entry, translation: str | None = None, glossary: dict[str, str] | None = None) -> list[str]:
    """Messages of the QA errors that keep a row from being marked reviewed."""
    return [issue.message for issue in qa_entry(entry, translation, glossary) if issue.severity == "error"]


@dataclass
class PreflightReport:
    """Everything ``preflight`` found. ``ok`` is False while any QA error would block or damage the output."""
    languages: list[str]
    errors: list[QaIssue] = field(default_factory=list)
    warnings: list[QaIssue] = field(default_factory=list)
    untranslated: list[Entry] = field(default_factory=list)
    untranslated_by_language: dict[str, list[Entry]] = field(default_factory=dict)
    outdated: list[Entry] = field(default_factory=list)
    reviewed_with_errors: list[QaIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        return (f"エラー {len(self.errors)} 件 / 警告 {len(self.warnings)} 件 / 未訳・原文のまま {len(self.untranslated)} 件 / "
                f"英文変更あり {len(self.outdated)} 件")


def preflight(project: Project, language: str | None = None) -> PreflightReport:
    """Run every check once before export: entry QA, advisory style checks, sentence style, untranslated rows,
    rows whose English changed, and reviewed rows that now carry errors.

    ``language`` limits the run to one language; by default every selected language is checked.
    ``untranslated`` and ``outdated`` describe the first checked language (see ``untranslated_by_language``).
    """
    languages = [language] if language else list(project.languages)
    report = PreflightReport(list(languages))
    project.stash_current_language()
    for number, target in enumerate(languages):
        issues = list(qa_project(project, target))
        for entry, translation in _translated_pairs(project, target):
            if not _skippable(entry):
                issues.extend(qa_extra(entry, translation))
        issues.extend(sentence_style_issues(project, target))
        issues.extend(outdated_issues(project, target))
        report.errors.extend(issue for issue in issues if issue.severity == "error")
        report.warnings.extend(issue for issue in issues if issue.severity != "error")
        rows = untranslated_rows(project, target)
        report.untranslated_by_language[target] = rows
        report.reviewed_with_errors.extend(reviewed_with_errors(project, target))
        if number == 0:
            report.untranslated = rows
            report.outdated = outdated_rows(project, target)
    return report
