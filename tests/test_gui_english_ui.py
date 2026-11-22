"""With the UI language set to English no control may stay Japanese (user data such as MOD names is exempt)."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import re
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QAbstractButton, QApplication, QComboBox, QLabel, QPlainTextEdit, QTabWidget,
                               QTableView, QTextEdit, QLineEdit, QTreeWidget, QWidget, QGroupBox)

from rimworld_translator.core import Project, scan_mod
from rimworld_translator.gui import Window
from rimworld_translator.notes import assign_file, set_note
from rimworld_translator.scan_context import Prerequisite, PrerequisiteReport

from rimworld_translator.languages import LANGUAGES

NATIVE_NAMES = {value[0].split('  (')[0] for value in LANGUAGES.values()}
JAPANESE = re.compile('[぀-ヿ一-鿿]')


def japanese_strings(root, generated=()):
    """(description, text) for every Japanese UI string reachable from ``root``; user-editable contents are skipped."""
    found = []

    def check(widget, what, value):
        if isinstance(value, str) and JAPANESE.search(value):
            found.append((f'{type(widget).__name__}:{widget.objectName() or "-"}.{what}', value))

    for widget in [root] + root.findChildren(QWidget):
        check(widget, 'windowTitle', widget.windowTitle())
        check(widget, 'toolTip', widget.toolTip())
        check(widget, 'accessibleName', widget.accessibleName())
        check(widget, 'accessibleDescription', widget.accessibleDescription())
        if isinstance(widget, (QAbstractButton, QLabel, QGroupBox)):
            check(widget, 'text', widget.text() if not isinstance(widget, QGroupBox) else widget.title())
        if isinstance(widget, (QLineEdit, QPlainTextEdit)):
            check(widget, 'placeholderText', widget.placeholderText())
        if isinstance(widget, QTabWidget):
            for index in range(widget.count()):
                check(widget, f'tab{index}', widget.tabText(index))
                check(widget, f'tabTip{index}', widget.tabToolTip(index))
        if isinstance(widget, QComboBox):
            for index in range(widget.count()):
                if widget.itemText(index).split('  (')[0] not in NATIVE_NAMES:  # a language's own name is not UI text
                    check(widget, f'item{index}', widget.itemText(index))
        if isinstance(widget, QPlainTextEdit) and widget.isReadOnly() and widget.objectName() != 'mono':
            check(widget, 'generatedText', widget.toPlainText()) if widget in generated else None
        if isinstance(widget, QTreeWidget):
            header = widget.headerItem()
            for column in range(widget.columnCount()):
                check(widget, f'header{column}', header.text(column))
            if widget.columnCount() >= 4:  # the prerequisite list: its last two columns are program text, not MOD data
                for row in range(widget.topLevelItemCount()):
                    item = widget.topLevelItem(row)
                    check(widget, f'itemTip{row}', item.toolTip(3))
                    check(widget, f'itemEffect{row}', item.text(3))
        if isinstance(widget, QTableView) and widget.model() is not None:
            model = widget.model()
            for column in range(model.columnCount()):
                check(widget, f'column{column}', model.headerData(column, Qt.Horizontal))
                check(widget, f'columnTip{column}', model.headerData(column, Qt.Horizontal, Qt.ToolTipRole))
            if hasattr(model, 'entries'):  # state/note columns are program text; key/English/translation are data
                for row in range(model.rowCount()):
                    for column in (0, 4):
                        index = model.index(row, column)
                        check(widget, f'cell{row},{column}', model.data(index, Qt.DisplayRole))
                        check(widget, f'cellTip{row},{column}', model.data(index, Qt.ToolTipRole))
    bar = root.menuBar() if hasattr(root, 'menuBar') else None
    pending = list(bar.actions()) if bar else []
    while pending:  # only the menus the person can reach; replaced menus are not UI
        action = pending.pop()
        check(action, 'text', action.text())
        if action.menu() is not None:
            pending.extend(action.menu().actions())
    return found


class EnglishUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        source = self.root / 'source'
        files = {
            'About/About.xml': '<ModMetaData><name>Sample Mod</name><packageId>test.english</packageId>'
                               '<supportedVersions><li>1.6</li></supportedVersions></ModMetaData>',
            'Languages/English/Keyed/a.xml': '<LanguageData><Greeting>Hello</Greeting><Bye>Goodbye sword</Bye></LanguageData>',
            'Languages/English/Keyed/b.xml': '<LanguageData><Other>Sword of dawn</Other></LanguageData>',
            'Defs/ThingDefs/t.xml': '<Defs><ThingDef><defName>Gun1</defName><label>sword gun</label>'
                                    '<description>A sword.</description></ThingDef>'
                                    '<ThingDef><defName>Gun2</defName><label>sword gun</label></ThingDef></Defs>',
        }
        for relative, content in files.items():
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
        project = Project.create_versions(source, {'1.6': scan_mod(source, game_version='1.6')})
        project.entries[0].japanese = '日本語の訳'
        project.glossary['sword'] = '剣'
        set_note(project, project.entries[0].id, 'メモ', 'later')
        assign_file(project, project.entries[0].source_file, 'Alice')
        self.saved = self.root / 'workspace/project.json'
        project.save(self.saved)
        self.window = Window(settings_path=self.root / 'settings.json')
        self.window.load_project(self.saved)
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.dirty = False
        for name in ('quality_dialog', 'glossary_window'):
            dialog = getattr(self.window, name, None)
            if dialog is not None:
                dialog.close()
        self.window.close()
        self.app.processEvents()

    def assert_english(self, root, label, generated=()):
        self.app.processEvents()
        self.assertEqual([], japanese_strings(root, generated), f'{label}: Japanese left in English UI')

    def test_main_window_english(self):
        self.window.set_gui_language('en')
        self.window.show()
        self.assert_english(self.window, 'main window')

    def test_target_reason_p0_exclusion_and_variance_english(self):
        project = self.window.project
        labels = [e for e in project.entries if e.kind == 'DefInjected' and e.key.endswith('.label')]
        self.assertEqual(2, len(labels))
        first, second = labels
        first.reasons = ['keyed', 'must-translate', 'official-pattern']
        next(e for e in project.entries if e.kind == 'Keyed').excluded = True
        project.glossary.pop('sword', None)
        for entry, rendering in ((first, '剣'), (second, '刀')):
            entry.japanese = rendering
        self.window.set_gui_language('en')
        self.window.populate()
        self.window.show()
        self.window.table.selectRow(self.window.model.row_for_id[first.id])
        self.app.processEvents()
        self.assertIn('Why this row is a target', self.window.notice_details.toPlainText() + self.window.notice.toPlainText())
        self.assert_english(self.window, 'row selected', generated=(self.window.notice, self.window.notice_details))
        self.assertIn('Names and descriptions', self.window.p0_text.text())
        self.window.glossary_dialog()
        view = self.window.glossary_window.inconsistent
        self.assertTrue(view.found, 'the variance fixture must produce a finding')
        for index in range(view.tree.topLevelItemCount()):
            self.assertNotRegex(view.tree.topLevelItem(index).text(1), JAPANESE)
        self.assert_english(self.window.glossary_window, 'variance panel')
        self.window.set_gui_language('ja')
        self.assertIn('名前・説明', self.window.p0_text.text())
        self.assertIn('対象になった理由', self.window.notice_details.toPlainText() + self.window.notice.toPlainText())

    def test_switch_back_and_forth_keeps_english(self):
        self.window.set_gui_language('ja')
        self.window.set_gui_language('en')
        self.assert_english(self.window, 'after ja->en')

    def test_switch_to_japanese_restores_japanese(self):
        self.window.set_gui_language('en')
        self.window.set_gui_language('ja')
        self.assertEqual('メモ', self.window.side_tabs.tabText(2))
        self.assertEqual('次の未訳', self.window.jump_untranslated.text())

    def test_dialogs_english(self):
        self.window.set_gui_language('en')
        self.assert_english(self.window.quality_check_dialog(), 'quality dialog')
        self.window.glossary_dialog()
        self.assert_english(self.window.glossary_window, 'glossary dialog')
        from rimworld_translator.dialogs_tools import PrerequisitesDialog
        report = PrerequisiteReport(
            (Prerequisite('a.b', 'Missing Mod', '123456'),),
            (Prerequisite('c.d', 'Found Mod', '', '', self.root, ('English',)),), 5)
        from rimworld_translator.prerequisite_effects import PrerequisiteEffect
        effects = {'c.d': PrerequisiteEffect('c.d', 2, None, 1, frozenset({'a', 'b'}),
                                             ('assemblies-unreadable', 'conditional-def-level'))}
        dialog = PrerequisitesDialog(self.window, report, effects)
        self.assert_english(dialog, 'prerequisites dialog')
        dialog.deleteLater()

    def test_assignee_filter_only_with_assignments(self):
        self.window.set_gui_language('en')
        combo = self.window.assignee_filter
        self.window.show()
        self.app.processEvents()
        self.assertFalse(combo.isHidden())
        self.assertIn('Alice', [combo.itemText(i) for i in range(combo.count())])
        combo.setCurrentIndex(combo.findData('Alice'))
        self.app.processEvents()
        project = self.window.project
        alice_rows = [e for e in project.entries if project.assignments.get(e.source_file) == 'Alice']
        self.assertEqual(len(alice_rows), self.window.proxy.rowCount())
        self.assertLess(len(alice_rows), len(project.entries))
        project.assignments.clear()
        self.window.refresh_filter_options()
        self.assertTrue(combo.isHidden())
