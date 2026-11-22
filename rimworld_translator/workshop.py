"""Starting material for a Steam Workshop page. The editor never publishes; the user does that in Steam."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import xml.etree.ElementTree as ET

from .core import Project, atomic_write, safe_xml, source_workshop_id, writable_destination
from .languages import LANGUAGES
from .progress import progress

DISCLAIMER = 'Unofficial community translation. Not affiliated with or endorsed by Ludeon Studios or the original mod author.'


@dataclass
class WorkshopMaterial:
    title: str
    description: str          # Steam BBCode
    changelog: str
    checklist: str
    tags: list[str] = field(default_factory=lambda: ['Translation'])


def _original_author(source: Path) -> str:
    try:
        return (safe_xml(source / 'About' / 'About.xml').findtext('author') or '').strip()
    except (OSError, ValueError, ET.ParseError):
        return ''


def workshop_material(project: Project, translator: str = '', diff=None, version_note: str = '') -> WorkshopMaterial:
    """Draft title, BBCode description, changelog and a pre-publish checklist.

    ``diff`` is an ``export_diff.ExportDiff``; its files become the changelog's first lines.
    Everything is a template for the user to edit. The disclaimer is always included.
    """
    source = Path(project.source)
    suffix = ' 日本語翻訳' if project.languages == ['Japanese'] else ' 翻訳' if len(project.languages) == 1 else ' 多言語翻訳'
    title = project.metadata.get('name') or project.name + suffix
    workshop_id = source_workshop_id(source)
    link = (f'[url=https://steamcommunity.com/sharedfiles/filedetails/?id={workshop_id}]{project.name}[/url]'
            if workshop_id else project.name)
    author = _original_author(source)
    lines = [f'[h1]{title}[/h1]', '', f'[b]{project.name}[/b] の翻訳 MOD です。元の MOD が必要です: {link}'
             + (f'(作者: {author})' if author else ''), '', '[h2]対応言語と進み具合[/h2]', '[list]']
    for language in project.languages:
        done = progress(project, language)
        label = LANGUAGES[language][0] if language in LANGUAGES else language
        lines.append(f'[*] {label}: {done.percent:g}%({done.translated}/{done.total})'
                     + (f'、名前と説明は {done.p0_percent:g}%' if done.p0_total else ''))
    lines += ['[/list]', '', '[h2]導入[/h2]', '[list]', '[*] 元の MOD の後に読み込まれるようにしてください(自動で設定されます)。',
              '[*] 訳がない項目は元の言語のまま表示されます。', '[/list]']
    if translator or project.metadata.get('author'):
        lines += ['', f'[b]翻訳:[/b] {translator or project.metadata["author"]}']
    if project.metadata.get('license'):
        lines.append(f'[b]翻訳のライセンス:[/b] {project.metadata["license"]}')
    lines += ['', DISCLAIMER]
    changes = []
    if diff is not None:
        changes += [f'+ {change.path}' for change in diff.added] + [f'~ {change.path}' for change in diff.changed] \
            + [f'- {change.path}' for change in diff.removed]
    changelog = '\n'.join([version_note or '更新内容', '', *changes]) + '\n'
    checklist = '\n'.join([
        '[ ] 元の MOD の作者に翻訳の公開を伝え、許可や条件(再配布ルール)を確認した',
        '[ ] 出力前チェックでエラーが 0 件になっている',
        '[ ] 出力した MOD をゲームに入れて、名前・説明・UI の表示を確認した',
        '[ ] About.xml の名前・作者・説明を確認した',
        '[ ] Preview.png を確認した(元 MOD の画像を使う場合は許可を確認する)',
        '[ ] 公開は自分で行う(このアプリは公開しません)']) + '\n'
    return WorkshopMaterial(title, '\n'.join(lines) + '\n', changelog, checklist)


def write_workshop_material(project: Project, folder: Path, **options) -> list[Path]:
    """Write title.txt, description.bbcode.txt, changelog.txt and checklist.txt into ``folder`` (a separate, writable folder)."""
    folder = writable_destination(Path(folder), Path(project.source))
    material = workshop_material(project, **options)
    written = []
    for name, text in (('title.txt', material.title + '\n'), ('description.bbcode.txt', material.description),
                       ('changelog.txt', material.changelog), ('checklist.txt', material.checklist)):
        path = folder / name
        atomic_write(path, text.encode('utf-8'))
        written.append(path)
    return written
