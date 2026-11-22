"""Window actions for quality check, reviewed export, sharing, multi-version tools and prerequisites.

Mixed into ``ToolsMixin``; the dialogs live in ``dialogs_tools``. Every action leaves the original MOD alone.
"""
from __future__ import annotations

from pathlib import Path
import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

from . import dialogs_tools as tools


class _PrerequisiteWorker(QObject):
    done = Signal(object, str, object)


class ShareMixin:
    # ---- export with review ----
    def export_with_review(self, *_checked):
        """Pre-flight check and a before/after file diff, then the normal export once the user agrees."""
        if not self.project or self.busy:
            return False
        from .core import ExportBlocked
        from .export_diff import export_diff
        self.edit_detail()
        try:
            output = self.output_folder()
        except ValueError as exc:
            self.error(self.error_text(exc))
            return False
        report = tools.preflight_for(self.project)
        diff = blocked = None
        try:
            diff = export_diff(self.project, output)
        except ExportBlocked as exc:
            blocked = exc
        except (ValueError, OSError):
            # Not a row problem (no ready version, a folder that is not ours...): the export reports it the usual way.
            return self.generate()
        dialog = tools.ExportReviewDialog(self, report, diff, blocked, output)
        try:
            accepted = dialog.exec() == QDialog.Accepted
            wants_quality = dialog.open_quality
        finally:
            dialog.deleteLater()
        if wants_quality:
            self.quality_check_dialog()
            return False
        return bool(accepted and dialog.can_export and self.generate())

    def quality_check_dialog(self):
        if not self.project or self.busy:
            return None
        existing = getattr(self, 'quality_dialog', None)
        if existing is not None:
            existing.close()
            existing.deleteLater()
        self.quality_dialog = tools.QualityDialog(self)
        self.quality_dialog.show()
        return self.quality_dialog

    # ---- sharing ----
    def workshop_material_dialog(self):
        if not self.project or self.busy:
            return
        dialog = tools.WorkshopDialog(self)
        dialog.exec()
        dialog.deleteLater()

    def exchange_export(self, kind):
        if not self.project or self.busy:
            return
        self.edit_detail()
        dialog = tools.ExchangeDialog(self, kind)
        if dialog.exec() != QDialog.Accepted:
            return
        kind, language, detailed = dialog.choices()
        value, _ = QFileDialog.getSaveFileName(self, self.tr('翻訳を書き出す', 'Export translations'),
                                               str(self.project_path.parent / f'translations.{kind}'), f'{kind.upper()} (*.{kind})')
        if value:
            try:
                tools.write_exchange(self.project, Path(value), kind, language, detailed)
                self.statusBar().showMessage(self.tr('書き出しました: ', 'Exported: ') + value, 8000)
            except Exception as exc:
                self.error(exc)

    def export_bundle_to(self, path, include_output=False):
        """Save the project and write it as one .rwtbundle file; the generated MOD is added on request."""
        if not self.project or self.busy or not self.save(export=False):
            return False
        from .interchange import export_bundle
        try:
            # The formal output, never the multi-version trial folder the editor may be showing.
            output = self.output_folder() if include_output else None
            export_bundle(self.project, Path(path), output if output is not None and output.is_dir() else None)
        except (ValueError, OSError) as exc:
            self.error(self.error_text(exc))
            return False
        self.statusBar().showMessage(self.tr(f'プロジェクトバンドルを書き出しました: {path}', f'Project bundle written: {path}'), 10000)
        return True

    def export_bundle_dialog(self):
        if not self.project or self.busy:
            return
        name, _ = QFileDialog.getSaveFileName(self, self.tr('プロジェクトバンドルを書き出す', 'Export project bundle'),
                                              str(self.project_path.parent / f'{self.project.name}.rwtbundle'), 'Project bundle (*.rwtbundle)')
        if not name:
            return
        include = QMessageBox.question(
            self, self.tr('書き出した MOD も含める？', 'Include the generated MOD?'),
            self.tr('生成済みの翻訳 MOD（出力フォルダー）もバンドルに入れますか？\n元 MOD のファイルと、この PC の元 MOD の場所は含まれません。',
                    'Include the generated translation MOD (the output folder) in the bundle?\nThe source MOD files and its location on this PC are never included.'),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes
        self.export_bundle_to(Path(name), include)

    def import_bundle_from(self, bundle, source, destination, overwrite=False):
        from .interchange import import_bundle
        try:
            target = import_bundle(Path(bundle), Path(destination), Path(source), overwrite)
        except (ValueError, OSError) as exc:
            self.error(self.error_text(exc))
            return False
        self.load_project(target)
        return self.project_path == target

    def import_bundle_dialog(self):
        if self.busy or not self.confirm_switch():
            return
        tr = self.tr
        name, _ = QFileDialog.getOpenFileName(self, tr('プロジェクトバンドルを開く', 'Open project bundle'), '', 'Project bundle (*.rwtbundle *.zip)')
        if not name:
            return
        try:
            description = tools.describe_bundle(name, tr)
        except (ValueError, OSError) as exc:
            self.error(self.error_text(exc))
            return
        if QMessageBox.question(self, tr('このバンドルを取り込む？', 'Import this bundle?'),
                                description + tr('\n\n次に、あなたの PC にある元 MOD のフォルダーと、プロジェクトの保存先を選びます。',
                                                 '\n\nNext choose your own copy of the source MOD and a folder for the project.')) != QMessageBox.Yes:
            return
        source = QFileDialog.getExistingDirectory(self, tr('元 MOD のフォルダーを選ぶ（読み取り専用）', 'Choose the source MOD folder (read only)'))
        if not source:
            return
        destination = QFileDialog.getExistingDirectory(self, tr('プロジェクトの保存先フォルダーを選ぶ', 'Choose a folder for the project'))
        if destination:
            self.import_bundle_from(Path(name), Path(source), Path(destination))

    def match_mod_dialog(self):
        if not self.project or self.busy:
            return
        dialog = tools.MatchModDialog(self)
        dialog.exec()
        dialog.deleteLater()

    def assign_files_dialog(self):
        if not self.project or self.busy:
            return
        dialog = tools.AssignDialog(self)
        dialog.exec()
        dialog.deleteLater()

    # ---- versions ----
    def _version_dialog(self, factory, needs_two=False):
        if not self.project or self.busy:
            return
        if needs_two and len(tools.scanned_versions(self.project)) < 2:
            self.info_dialog(self.tr('版', 'Versions'), self.tr(
                '抽出済みの版が1つだけです。「宣言版を確認・追加」で他の版を抽出してください。',
                'Only one version has been extracted. Use "Check and add declared versions" to extract others.'))
            return
        dialog = factory(self)
        dialog.exec()
        dialog.deleteLater()

    def version_states_dialog(self):
        self._version_dialog(tools.VersionStatesDialog)

    def carry_versions_dialog(self):
        self._version_dialog(tools.CarryDialog, needs_two=True)

    def version_diff_dialog(self):
        self._version_dialog(tools.VersionDiffDialog, needs_two=True)

    # ---- prerequisites ----
    def prerequisites_dialog(self):
        """Look up the source MOD's prerequisites among installed MODs (in a thread; Workshop folders can be large)."""
        if not self.project or self.busy:
            return
        from .gui import matching_installation
        from .prerequisite_effects import prerequisite_effects
        from .scan_context import dependency_context, prerequisite_report
        project = self.project
        games = self.discovered_games()
        version = project.game_version
        extra = self.user_mod_roots()
        worker = _PrerequisiteWorker(self)
        self._prerequisite_worker = worker

        def run():
            try:
                from .platforms import mod_folders
                context = dependency_context(matching_installation(games, version), games, project.source, version,
                                             project.active_mods if project.active_mods_known else None, mod_folders(extra.all()))
                report = prerequisite_report(context, project.diagnostics)
                try:
                    effects = prerequisite_effects(project, report.found, version, project.active_mods if project.active_mods_known else None)
                except Exception:  # the row counts are extra information; the list itself must still open
                    effects = {}
                worker.done.emit(report, '', effects)
            except Exception as exc:  # shown in the dialog area; the thread must not die silently
                worker.done.emit(None, str(exc), None)
        worker.done.connect(self._show_prerequisites)
        self.statusBar().showMessage(self.tr('前提 MOD を調べています…', 'Looking up prerequisite MODs…'))
        threading.Thread(target=run, daemon=True).start()

    def _show_prerequisites(self, report, error, effects=None):
        self.statusBar().clearMessage()
        if report is None:
            self.error(error)
            return
        dialog = tools.PrerequisitesDialog(self, report, effects)
        dialog.exec()
        dialog.deleteLater()
