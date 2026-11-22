"""The main translation screen's helpers around the row being edited.

Filters (Def type, file, flag), the P0 progress line, placeholder buttons, width hint, advisory warnings,
rich-text preview, suggestions (memory, official, glossary), per-row notes and the keyboard flow.
The window class mixes this in; the widgets themselves are built in ``layout.py``.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import Counter

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import QListWidgetItem, QMessageBox, QPushButton

from .field_semantics import entry_nonlocalizable_reason
from .notes import FLAGS, FLAG_LABELS, get_note, set_note
from .preview import rich_text_html
from .progress import is_p0
from .qa import insert_token, length_hint, qa_extra, token_palette
from .row_filters import def_type, row_statuses

FLAG_ENGLISH = {'later': 'Review later', 'question': 'Question', 'check_in_game': 'Check in game', 'done_for_now': 'Done for now'}
NOTE_MARK = {'flag': '⚑', 'text': '✎'}
KIND_LABEL = {'memory': ('同じ原文', 'Same source'), 'official': ('公式訳', 'Official'),
              'glossary': ('用語', 'Term'), 'candidate': ('用語候補', 'Term candidate'),
              'prerequisite': ('前提MOD', 'Prerequisite MOD')}


REASON_JA = {
    'keyed': '英語の Keyed カタログ（ゲームの UI 文字列の経路）',
    'strings-resource': '英語の Strings リソース',
    'english-catalog': 'MOD 自身の英語 DefInjected カタログがこのキーを挙げている',
    'must-translate': 'C# フィールドに MustTranslate 属性がある',
    'may-translate': 'C# フィールドに MayTranslate 属性がある',
    'string-field': '属性のない C# 文字列フィールド',
    'shape:ambiguous': '単語1つだけ（ラベルかタグか判別できない）',
    'field-name': '読めなかったクラスのフィールドで、名前が表示文字列らしい',
    'own-translation': 'MOD 自身の別言語訳にこのキーがある',
    'official-pattern': '公式の翻訳がこの Def 型・フィールドを訳している',
}


def reason_lines(entry, tr) -> list[str]:
    """Plain-language lines for the entry's machine-readable ``reasons``; nothing for rows saved without them."""
    from .extraction import REASONS
    if not entry.reasons:
        return []
    lines = [tr('対象になった理由', 'Why this row is a target')]
    lines += [f'  {code}: ' + tr(REASON_JA.get(code, REASONS.get(code, code)), REASONS.get(code, code)) for code in entry.reasons]
    return lines


def note_marker(project, entry_id: str) -> str:
    """The table's note column: a flag mark, a pencil for text only, nothing for no note."""
    if project is None or entry_id not in project.notes:
        return ''
    note = get_note(project, entry_id)
    return NOTE_MARK['flag'] if note.flag else NOTE_MARK['text'] if note.text.strip() else ''


def term_in(english: str, term: str) -> bool:
    return bool(re.search(r'(?<![A-Za-z0-9])' + re.escape(term) + r'(?![A-Za-z0-9])', english, re.I))


class EditorPanelMixin:
    # ---- setup ----
    def init_editor_panel(self):
        from PySide6.QtWidgets import QListWidget  # noqa: F401  (widgets are created in layout.py)
        self._note_sync = False
        self._aid_signature = None
        self._suggest_cache = None
        self._identical_counts = Counter()
        self._term_candidates = None
        self._memory = None
        self.reset_flag_combos()
        index = self.status_filter.findData('qa-error')
        if index < 0:
            self.status_filter.addItem(self.tr('QA エラーあり', 'Has QA error'), 'qa-error')
        self.japanese.textChanged.connect(self.refresh_aids)
        self.flag_combo.currentIndexChanged.connect(self.note_changed)
        self.note_edit.textChanged.connect(self.note_changed)
        self.suggest_list.itemDoubleClicked.connect(lambda _item: self.insert_selected_suggestion())
        self.suggest_list.currentItemChanged.connect(lambda *_: self.update_suggestion_buttons())
        for keys, callback in (('Ctrl+J', lambda: self.jump_to_next('untranslated')),
                               ('Ctrl+Shift+J', lambda: self.jump_to_next('needs-review')),
                               ('Ctrl+Shift+Return', self.confirm_and_next),
                               ('Ctrl+K', self.toggle_later_flag)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)
        self.refresh_aids()

    def reset_flag_combos(self):
        for combo, first, extra in ((self.flag_combo, self.tr('印なし', 'No flag'), ()),
                                    (self.flag_filter, self.tr('すべての印', 'All flags'),
                                     ((self.tr('印あり', 'Any flag'), '*'),))):
            chosen = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(first, '')
            for label, data in extra:
                combo.addItem(label, data)
            for flag in FLAGS:
                combo.addItem(self.tr(FLAG_LABELS[flag], FLAG_ENGLISH[flag]), flag)
            combo.setCurrentIndex(max(0, combo.findData(chosen)) if chosen else 0)
            combo.blockSignals(False)

    # ---- filters ----
    def refresh_filter_options(self):
        """Fill the Def type and file drop-downs from the open project, keeping the chosen values when still present."""
        types, files = Counter(), Counter()
        for entry in self.model.entries:
            types[def_type(entry)] += 1
            files[entry.source_file] += 1
        for combo, counts, first in ((self.def_type_filter, types, self.tr('すべての種類', 'All Def types')),
                                     (self.file_filter, files, self.tr('すべてのファイル', 'All files'))):
            chosen = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(first, '')
            for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
                combo.addItem(f'{name}  ({count})', name)
            combo.setCurrentIndex(max(0, combo.findData(chosen)) if chosen else 0)
            combo.blockSignals(False)
        self.refresh_assignee_filter()
        self._identical_counts = Counter(e.english for e in self.model.entries
                                         if e.english.strip() and not (e.stale or e.blocked or e.excluded))
        self._term_candidates = None
        self._suggest_cache = None

    def refresh_assignee_filter(self):
        """List the translators files are assigned to; the drop-down is hidden while nobody is assigned."""
        project = self.project
        names = sorted({name for name in (project.assignments.values() if project else ()) if name})
        combo = self.assignee_filter
        chosen = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(self.tr('すべての担当者', 'All assignees'), '')
        for name in names:
            combo.addItem(name, name)
        combo.setCurrentIndex(max(0, combo.findData(chosen)) if chosen else 0)
        combo.blockSignals(False)
        combo.setVisible(bool(names))
        if chosen and chosen not in names:
            self.filter_changed()

    def sync_extra_filters(self):
        self.proxy.def_type = self.def_type_filter.currentData() or ''
        self.proxy.file = self.file_filter.currentData() or ''
        self.proxy.flag = self.flag_filter.currentData() or ''
        self.proxy.assignee = self.assignee_filter.currentData() or ''

    def reset_extra_filters(self):
        for combo in (self.def_type_filter, self.file_filter, self.flag_filter, self.assignee_filter):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self.sync_extra_filters()

    def extra_filters_active(self) -> bool:
        return bool(self.def_type_filter.currentData() or self.file_filter.currentData() or self.flag_filter.currentData()
                    or self.assignee_filter.currentData())

    def navigate_entry(self, identity):
        self.reset_extra_filters()
        return super().navigate_entry(identity)

    # ---- progress ----
    def refresh_p0(self, eligible):
        rows = [e for e in eligible if is_p0(e)]
        done = sum(bool(e.japanese.strip()) for e in rows)
        if not rows:
            self.p0_text.setText(self.tr('名前・説明: 対象なし', 'Names and descriptions: none'))
            self.p0_bar.setValue(0)
            return
        percent = round(100 * done / len(rows))
        if done < len(rows):
            percent = min(percent, 99)
        self.p0_text.setText(self.tr(f'名前・説明 {done} / {len(rows)} ({percent}%)',
                                     f'Names and descriptions {done} / {len(rows)} ({percent}%)'))
        self.p0_text.setToolTip(self.tr('アイテム名・説明など、プレイヤーが最初に目にする文章だけの進み具合です。',
                                        'Progress on item names and descriptions only: what players read first.'))
        self.p0_bar.setValue(percent)

    # ---- the row editor ----
    def sync_panel(self):
        """Refresh everything beside the editors for the current row; cheap enough to run on every keystroke."""
        self.review_message.hide()
        self.refresh_aids()
        self.refresh_suggestions()
        self.sync_note_widgets()

    def refresh_aids(self, *_):
        entry = getattr(self, 'current', None)
        text = self.japanese.toPlainText()
        if entry is None or not hasattr(self, 'token_row'):
            self.set_token_buttons([])
            self.hint_label.hide()
            self.advice_label.hide()
            self.preview_view.clear()
            return
        self.set_token_buttons(token_palette(entry, text) if not self.japanese.isReadOnly() else [])
        hint = length_hint(entry, text) if text.strip() else None
        if hint is None:
            self.hint_label.setText('')
            self.hint_label.hide()
        else:
            self.hint_label.setText(self.tr(f'幅 {hint.width} / 目安 {hint.limit}' + ('  ·  長すぎて切れるかもしれません' if hint.over else ''),
                                            f'Width {hint.width} / guide {hint.limit}' + ('  ·  may be cut off' if hint.over else '')))
            self.hint_label.setProperty('over', hint.over)
            self.repolish(self.hint_label)
            self.hint_label.show()
        issues = qa_extra(entry, text) if not self.japanese.isReadOnly() else []
        if issues:
            from .diagnostic_text import explain
            plains = [explain({'code': issue.code, 'message': issue.message, 'suggestion': issue.suggestion}, self.ui_language)
                      for issue in issues]
            self.advice_label.setText('\n'.join(p.title + (f'  ({p.action})' if p.action else '') for p in plains))
            self.advice_label.show()
        else:
            self.advice_label.setText('')
            self.advice_label.hide()
        self.preview_view.setHtml(rich_text_html(text))
        self.update_suggestion_buttons()

    @staticmethod
    def repolish(widget):
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def set_token_buttons(self, palette):
        signature = tuple(palette)
        if signature == self._aid_signature:
            return
        self._aid_signature = signature
        layout = self.token_row
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.token_buttons = []
        for token, missing, total in palette:
            label = token if missing <= 1 else f'{token} ×{missing}'
            button = QPushButton(label)
            button.setObjectName('token')
            button.setProperty('missing', missing > 0)
            button.setFocusPolicy(Qt.NoFocus)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(self.tr(f'原文の記号。カーソル位置に入れます(あと {missing} 個必要 / 原文に {total} 個)',
                                      f'Source marker. Inserts at the cursor ({missing} still missing / {total} in the source)'))
            button.clicked.connect(lambda _checked=False, t=token: self.insert_palette_token(t))
            layout.addWidget(button)
            self.token_buttons.append(button)
        layout.addStretch(1)
        self.token_scroll.setVisible(bool(palette))

    def insert_palette_token(self, token):
        if self.japanese.isReadOnly():
            return
        self.replace_translation(*insert_token(self.japanese.toPlainText(), token, self.japanese.textCursor().position()))

    def replace_translation(self, text, cursor_position=None):
        """Put ``text`` in the translation box as one undoable edit."""
        cursor = self.japanese.textCursor()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.Document)
        cursor.insertText(text)
        cursor.endEditBlock()
        cursor.setPosition(len(text) if cursor_position is None else cursor_position)
        self.japanese.setTextCursor(cursor)
        self.japanese.setFocus()

    # ---- suggestions ----
    def memory(self):
        if self._memory is None:
            from .translation_memory import TranslationMemory
            self._memory = TranslationMemory(self.settings.path.with_name('translation-memory.json'))
        return self._memory

    def remember_translations(self):
        """Add this project's clean translations to the shared memory, so later projects can reuse them."""
        try:
            memory = self.memory()
            memory.forget_project(self.project.package_id)
            memory.add_project(self.project)
            memory.save()
        except Exception:
            pass  # the memory is a convenience; any failure of it must never get in the way of saving or exporting
        self._suggest_cache = None

    def suggestion_sources(self, entry):
        """(this project's earlier translations, remembered ones, official ones) of the same English."""
        from .workflow import translation_memory
        key = (entry.id, self.project.language, len(self.project.glossary))
        if self._suggest_cache and self._suggest_cache[0] == key:
            return self._suggest_cache[1]
        try:
            own = [item.translation for item in translation_memory(self.project, entry.id, self.project.language)[:3]]
        except ValueError:
            own = []
        try:
            remembered = [hit.translation for hit in self.memory().suggest(self.project, entry.id, limit=3)]
        except ValueError:
            remembered = []
        remembered = [text for text in remembered if text not in own]
        official = [text for text in self.official_suggestions(entry) if text not in own and text not in remembered]
        result = (own[:3], remembered[:3], official[:3])
        self._suggest_cache = (key, result)
        return result

    def prerequisite_token(self):
        project = self.project
        return (id(project), project.language, project.game_version) if project else None

    def prerequisite_rows(self, entry):
        """Translations a found prerequisite MOD ships for this row's key or Def, as read-only suggestion rows.

        The folders are read once per scan, in the background; the list refreshes itself when they are ready.
        """
        index = self.prerequisite_index()
        if index is None:
            return []
        rows = []
        for hit in index.lookup(entry):
            shown = f'[{hit.mod}] ' + (f'{hit.key.split(".", 1)[-1]} → ' if hit.same_def else '') + hit.text
            rows.append(('prerequisite', shown, hit.text))
        return rows

    def prerequisite_index(self):
        state = getattr(self, '_prerequisite_translations', None)
        token = self.prerequisite_token()
        if state is None or state[0] != token:
            self._prerequisite_translations = (token, None)
            self.start_prerequisite_lookup(token)
            return None
        return state[1]

    def start_prerequisite_lookup(self, token):
        """Look the prerequisites up in a thread (Workshop folders can be large); only MODs that declare some are searched."""
        import threading
        from pathlib import Path
        from PySide6.QtCore import QObject, Signal
        from .installation import dependencies_for, read_mod_metadata
        project = self.project
        try:
            declared = bool(dependencies_for(read_mod_metadata(Path(project.source)), project.game_version))
        except (OSError, ValueError, ET.ParseError):
            declared = False
        if not declared:
            return

        class Worker(QObject):
            done = Signal(object, object)

        worker = Worker(self)
        self._prerequisite_worker = worker
        games, roots = self.discovered_games(), self.user_mod_roots()
        language, version = project.language, project.game_version
        active = list(project.active_mods) if project.active_mods_known else None

        def run():
            try:
                from .gui import matching_installation
                from .platforms import mod_folders
                from .prerequisite_translations import read_prerequisite_translations
                from .scan_context import dependency_context, prerequisite_report
                context = dependency_context(matching_installation(games, version), games, project.source, version, active,
                                             mod_folders(roots.all()))
                found = [item for item in prerequisite_report(context).found if not item.official]
                index = read_prerequisite_translations(found, language, version, active)
            except Exception:  # a convenience; never let it break editing
                index = None
            try:
                worker.done.emit(token, index)
            except RuntimeError:
                pass  # the window was closed meanwhile

        def arrived(done_token, index):
            if index is not None and self.prerequisite_token() == done_token:
                self._prerequisite_translations = (done_token, index)
                self._force_suggestions = True
                self.refresh_suggestions()

        worker.done.connect(arrived)
        threading.Thread(target=run, daemon=True).start()

    def glossary_matches(self, entry):
        found = [('glossary', term, text) for term, text in self.project.glossary.items() if term_in(entry.english, term)]
        known = {term.casefold() for _, term, _ in found} | {term.casefold() for term in self.project.glossary}
        if self._term_candidates is None:
            from .glossary import collect_terms
            try:
                self._term_candidates = collect_terms(self.project, self.project.language)
            except ValueError:
                self._term_candidates = []
        found += [('candidate', item.term, item.translation) for item in self._term_candidates
                  if item.term.casefold() not in known and term_in(entry.english, item.term)]
        return found

    def refresh_suggestions(self):
        entry = self.current
        key = (entry.id if entry else None, self.project.language if self.project else None)
        if key == getattr(self, '_listed_for', None) and not getattr(self, '_force_suggestions', False):
            return
        self._listed_for, self._force_suggestions = key, False
        self.suggest_list.clear()
        if entry is None or self.project is None or entry_nonlocalizable_reason(entry):
            self.update_suggestion_buttons()
            return
        own, remembered, official = self.suggestion_sources(entry)
        rows = ([('memory', text, text) for text in [*own, *remembered]] + [('official', text, text) for text in official]
                + self.prerequisite_rows(entry) + self.glossary_matches(entry))
        for kind, left, right in rows:
            label = self.tr(*KIND_LABEL[kind])
            text = f'{label}: {left}' if kind in ('memory', 'official', 'prerequisite') else f'{label}: {left} → {right}'
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, (kind, left, right))
            item.setToolTip(right)
            self.suggest_list.addItem(item)
        if rows:
            self.suggest_list.setCurrentRow(0)
        self.side_tabs.setTabText(1, self.tr('候補', 'Suggestions') + (f' ({len(rows)})' if rows else ''))
        self.update_suggestion_buttons()

    def update_suggestion_buttons(self):
        item = self.suggest_list.currentItem()
        kind = item.data(Qt.UserRole)[0] if item else ''
        writable = bool(self.current) and not self.japanese.isReadOnly() and not self.busy
        self.insert_suggestion_button.setEnabled(writable and bool(item))
        self.register_term_button.setEnabled(writable and kind == 'candidate')
        entry = self.current
        others = self._identical_counts[entry.english] - 1 if entry else 0
        can = bool(entry) and writable and others > 0 and bool(self.japanese.toPlainText().strip())
        self.apply_identical_button.setEnabled(can)
        self.apply_identical_button.setText(self.tr('同じ原文すべてに適用', 'Apply to all identical')
                                            + (f' ({others})' if others > 0 else ''))

    def insert_selected_suggestion(self):
        item = self.suggest_list.currentItem()
        if item is None or self.japanese.isReadOnly() or self.busy:
            return
        kind, left, right = item.data(Qt.UserRole)
        if kind in ('memory', 'official', 'prerequisite'):
            self.replace_translation(right)
        else:
            self.replace_translation(*insert_token(self.japanese.toPlainText(), right, self.japanese.textCursor().position()))

    def register_selected_term(self):
        item = self.suggest_list.currentItem()
        if item is None or not self.project:
            return
        kind, term, translation = item.data(Qt.UserRole)
        if kind != 'candidate':
            return
        from .workflow import set_glossary_term
        try:
            set_glossary_term(self.project, term, translation)
        except ValueError as exc:
            self.error(exc)
            return
        self._term_candidates = None
        self._force_suggestions = True
        self.on_edit()
        self.statusBar().showMessage(self.tr(f'用語集に登録しました: {term} → {translation}', f'Added to the glossary: {term} → {translation}'), 6000)

    def apply_identical(self):
        """Copy the current translation to every other row with exactly the same English (undoable as one batch)."""
        from .workflow import preview_apply_identical
        entry = self.current
        if not entry or not self.project or self.busy:
            return
        try:
            preview = preview_apply_identical(self.project, entry.id, self.project.language)
        except ValueError as exc:
            self.error(exc)
            return
        protected = len(preview.conflicts)
        if not preview.changes:
            self.statusBar().showMessage(self.tr('同じ原文で、まだ訳していない項目はありません。', 'No untranslated rows share this English.'), 6000)
            return
        note = self.tr(f'\n(すでに別の訳がある {protected} 件は変更しません)', f'\n({protected} rows that already differ are left alone)') if protected else ''
        shown = entry.english if len(entry.english) <= 40 else entry.english[:39] + '…'
        answer = QMessageBox.question(
            self, self.tr('同じ原文すべてに適用', 'Apply to all identical'),
            self.tr(f'「{shown}」と同じ原文の他の {len(preview.changes)} 件に、この訳を入れます。{note}\n「一括変更を元に戻す」で取り消せます。',
                    f'Put this translation into {len(preview.changes)} other rows with the same English "{shown}".{note}\nUndo with Undo batch.'))
        if answer != QMessageBox.Yes:
            return
        if self.apply_preview(preview):
            self.statusBar().showMessage(self.tr(f'{len(preview.changes)} 件に同じ訳を入れました。', f'Applied to {len(preview.changes)} rows.'), 8000)

    # ---- notes ----
    def sync_note_widgets(self):
        entry = self.current
        note = get_note(self.project, entry.id) if entry and self.project else None
        self._note_sync = True
        try:
            wanted = note.flag if note else ''
            if self.flag_combo.currentData() != wanted:
                self.flag_combo.setCurrentIndex(max(0, self.flag_combo.findData(wanted)))
            text = note.text if note else ''
            if self.note_edit.toPlainText() != text:
                self.note_edit.setPlainText(text)
            enabled = bool(entry) and not self.busy
            self.flag_combo.setEnabled(enabled)
            self.note_edit.setReadOnly(not enabled)
        finally:
            self._note_sync = False

    def note_changed(self, *_):
        entry = self.current
        if self._note_sync or not entry or not self.project or self.busy:
            return
        try:
            set_note(self.project, entry.id, self.note_edit.toPlainText(), self.flag_combo.currentData() or '')
        except ValueError as exc:
            self.error(exc)
            return
        row = self.model.row_for_id.get(entry.id)
        if row is not None:
            self.model.dataChanged.emit(self.model.index(row, 4), self.model.index(row, 4))
        self.mark_dirty_quietly()
        if self.flag_filter.currentData():
            self.filter_changed()

    def mark_dirty_quietly(self):
        """A note changed: the project needs saving, but nothing about the translation did."""
        self.dirty = True
        self.start_autosave()
        self.statusBar().showMessage(self.tr('未保存の変更  ·  メモを変更しました。', 'Unsaved changes  ·  note edited.'))

    def toggle_later_flag(self):
        entry = self.current
        if not entry or not self.project or self.busy:
            return
        flag = '' if get_note(self.project, entry.id).flag == 'later' else 'later'
        self.flag_combo.setCurrentIndex(self.flag_combo.findData(flag))

    # ---- keyboard flow ----
    def row_needs(self, entry, kind):
        if entry.stale or entry.blocked or entry.excluded or entry_nonlocalizable_reason(entry):
            return False
        untranslated = not entry.japanese.strip()
        review = entry.status in ('needs-review', 'changed') and not untranslated
        return {'untranslated': untranslated, 'needs-review': review, 'work': untranslated or review}[kind]

    def jump_to_next(self, kind):
        """Select the next row (after the current one, wrapping) that is untranslated / needs review; filters stay as they are."""
        if not self.project or self.busy:
            return False
        count = self.proxy.rowCount()
        start = -1
        if self.current is not None and self.current.id in self.model.row_for_id:
            mapped = self.proxy.mapFromSource(self.model.index(self.model.row_for_id[self.current.id], 0))
            start = mapped.row() if mapped.isValid() else -1
        if start < 0 and self.table.currentIndex().isValid():
            start = self.table.currentIndex().row()
        for step in range(1, count + 1):
            row = (start + step) % count
            entry = self.model.entries[self.proxy.mapToSource(self.proxy.index(row, 0)).row()]
            if self.row_needs(entry, kind) and entry is not self.current:
                index = self.proxy.index(row, 0)
                self.table.setCurrentIndex(index)
                self.table.scrollTo(index)
                self.japanese.setFocus()
                return True
        message = {'untranslated': self.tr('これ以上、未訳の項目はありません。', 'No more untranslated rows.'),
                   'needs-review': self.tr('これ以上、要確認の項目はありません。', 'No more rows needing review.'),
                   'work': self.tr('これ以上、未訳・要確認の項目はありません。', 'No more untranslated or review rows.')}[kind]
        self.statusBar().showMessage(message, 6000)
        return False

    def confirm_and_next(self):
        """Mark the current row reviewed and go to the next row that still needs work."""
        if not self.current or self.busy:
            return
        if not self.mark_reviewed():
            return
        if not self.focus_mode:
            self.jump_to_next('work')

    def show_review_message(self, text):
        self.review_message.setText(str(text))
        self.review_message.show()
        self.statusBar().showMessage(str(text), 10000)

    # ---- window geometry ----
    def adapt_panel(self):
        self.side_tabs.setVisible(self.width() >= 680)

    def fit_sidebar(self):
        """Keep the sidebar wide enough for its button labels at the current font size."""
        buttons = (self.new_button, self.open_button, self.save_side, self.rescan_side, self.manual_side,
                   self.warnings_side, self.git_side, self.output_side)
        need = max(b.fontMetrics().horizontalAdvance(b.text()) for b in buttons) + 52
        inner = max(220, need)
        if self.sidebar.widget().width() != inner:
            self.sidebar.widget().setFixedWidth(inner)
            self.sidebar.setFixedWidth(inner + 16)
