"""Scalable source selection, author search and user-owned favorites."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QDialog,QLineEdit,QListWidget,QPushButton,QWidget
from rimworld_translator.dialogs import select_workshop_mod
from rimworld_translator.settings import SettingsStore


class PickerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workshop = self.root/'workshop'
        for ident,name,author in [('1111111111','First source','Carson'),('2222222222','Second source','Mira')]:
            path = self.workshop/ident/'About/About.xml'
            path.parent.mkdir(parents=True)
            path.write_text(f'<ModMetaData><name>{name}</name><author>{author}</author><packageId>sample.mod{ident}</packageId></ModMetaData>')

    def test_author_search_and_favorite_persist_without_changing_sources(self):
        parent = QWidget()
        self.addCleanup(parent.close)
        parent.ui_language = 'en'
        parent.settings = SettingsStore(self.root/'settings.json')
        before = {p:p.read_bytes() for p in self.workshop.rglob('*.xml')}
        def simulate(dialog):
            listing = dialog.findChild(QListWidget)
            search = dialog.findChild(QLineEdit)
            search.setText('Mira')
            visible = [listing.item(i) for i in range(listing.count()) if not listing.item(i).isHidden()]
            self.assertEqual(len(visible),1,'Author must be searchable')
            listing.setCurrentItem(visible[0])
            favorite = dialog.findChild(QPushButton,'favoriteSource')
            self.assertIsNotNone(favorite,'Favorite action must be available')
            favorite.click()
            return QDialog.Accepted
        with patch.object(QDialog,'exec',new=simulate):
            selected = select_workshop_mod(parent,self.workshop)
        self.assertEqual(selected,self.workshop/'2222222222')
        self.assertIn(str(selected.resolve()),SettingsStore(self.root/'settings.json').data['favorite_sources'])
        self.assertEqual(before,{p:p.read_bytes() for p in self.workshop.rglob('*.xml')})

    def test_game_library_location_is_a_string_or_default(self):
        path = self.root/'settings.json'
        path.write_text('{"game_library": 5}', encoding='utf-8')
        self.assertEqual(SettingsStore(path).data['game_library'], '')
        path.write_text('{"game_library": "/lib"}', encoding='utf-8')
        self.assertEqual(SettingsStore(path).data['game_library'], '/lib')

    def test_recent_projects_are_deduplicated_and_bounded(self):
        settings = SettingsStore(self.root/'settings.json')
        for i in range(20):
            settings.remember_project(self.root/f'{i}/project.json')
        settings.remember_project(self.root/'19/project.json')
        loaded = SettingsStore(self.root/'settings.json')
        self.assertEqual(len(loaded.data['recent_projects']),15)
        self.assertEqual(loaded.data['recent_projects'][0],str(self.root/'19/project.json'))
        self.assertEqual(len(set(loaded.data['recent_projects'])),15)


if __name__=='__main__':
    unittest.main()
