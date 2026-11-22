"""Classification tree beside the entry table: kind > Def type > Def, with remaining-work counts.

Selecting a node narrows the table to that scope; the existing search and status filters still apply on top.
"""
from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidgetItem

from .field_semantics import entry_nonlocalizable_reason

SCOPE_ROLE = Qt.UserRole + 1
# Plain-language names for the three kinds (the technical name stays in the tooltip).
KIND_NAMES = {'DefInjected': ('定義の文章', 'Def text'), 'Keyed': ('画面の文言', 'UI text'), 'Strings': ('名前リスト', 'Name lists')}


def kind_name(kind: str, english: bool = False) -> str:
    return KIND_NAMES.get(kind, (kind, kind))[1 if english else 0]
# A project with more Defs than this shows the tree down to the Def type only, to keep the widget light.
MAX_DEF_NODES = 6000


def def_name(entry) -> str:
    return entry.key.split('.', 1)[0] if entry.kind == 'DefInjected' else ''


def in_scope(entry, scope) -> bool:
    """True when the entry belongs to a (kind[, group[, def]]) scope; an empty scope matches everything."""
    if not scope:
        return True
    if entry.kind != scope[0]:
        return False
    if len(scope) > 1 and entry.group != scope[1]:
        return False
    return len(scope) < 3 or def_name(entry) == scope[2]


def _countable(entry) -> bool:
    return not (entry.blocked or entry.stale or entry.excluded or entry_nonlocalizable_reason(entry))


def _stats(entries, with_defs: bool):
    stats = defaultdict(lambda: [0, 0])   # scope -> [remaining, total]
    for entry in entries:
        if not _countable(entry):
            continue
        todo = 0 if entry.japanese.strip() else 1
        scopes = [(), (entry.kind,), (entry.kind, entry.group)]
        if with_defs and entry.kind == 'DefInjected':
            scopes.append((entry.kind, entry.group, def_name(entry)))
        for scope in scopes:
            stats[scope][0] += todo
            stats[scope][1] += 1
    return stats


def _label(name: str, remaining: int, total: int) -> str:
    return f'{name}    {remaining}/{total}'


def build(tree, entries, all_label: str = 'すべて') -> None:
    """Rebuild the tree from scratch, keeping the selected scope when it still exists."""
    previous = current_scope(tree)
    tree.blockSignals(True)
    tree.clear()
    defs = {(e.kind, e.group, def_name(e)) for e in entries if e.kind == 'DefInjected'}
    with_defs = len(defs) <= MAX_DEF_NODES
    stats = _stats(entries, with_defs)
    names = defaultdict(lambda: defaultdict(set))   # kind -> group -> defs
    for entry in entries:
        names[entry.kind][entry.group].add(def_name(entry))
    root = QTreeWidgetItem([_label(all_label, *stats[()])])
    root.setData(0, SCOPE_ROLE, ())
    tree.addTopLevelItem(root)
    for kind in sorted(names):
        kind_item = QTreeWidgetItem(root, [_label(kind_name(kind), *stats[(kind,)])])
        kind_item.setData(0, SCOPE_ROLE, (kind,))
        kind_item.setToolTip(0, kind)
        for group in sorted(names[kind]):
            group_item = QTreeWidgetItem(kind_item, [_label(group, *stats[(kind, group)])])
            group_item.setData(0, SCOPE_ROLE, (kind, group))
            if kind == 'DefInjected' and with_defs:
                for name in sorted(names[kind][group]):
                    leaf = QTreeWidgetItem(group_item, [_label(name, *stats[(kind, group, name)])])
                    leaf.setData(0, SCOPE_ROLE, (kind, group, name))
    root.setExpanded(True)
    for index in range(root.childCount()):
        root.child(index).setExpanded(True)
    tree.blockSignals(False)
    select(tree, previous)


def refresh_counts(tree, entries) -> None:
    """Update the numbers in place (cheap enough to run after edits, debounced by the caller)."""
    defs_present = False
    iterator = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
    while iterator:
        item = iterator.pop()
        scope = item.data(0, SCOPE_ROLE) or ()
        if len(scope) == 3:
            defs_present = True
        iterator.extend(item.child(i) for i in range(item.childCount()))
    stats = _stats(entries, defs_present)
    iterator = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
    tree.blockSignals(True)
    while iterator:
        item = iterator.pop()
        scope = tuple(item.data(0, SCOPE_ROLE) or ())
        name = item.text(0).rsplit('    ', 1)[0]
        item.setText(0, _label(name, *stats[scope]))
        iterator.extend(item.child(i) for i in range(item.childCount()))
    tree.blockSignals(False)


def current_scope(tree) -> tuple:
    item = tree.currentItem()
    return tuple(item.data(0, SCOPE_ROLE) or ()) if item is not None else ()


def select(tree, scope: tuple) -> None:
    """Select the node for a scope, falling back to the root."""
    target = tree.topLevelItem(0)
    stack = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
    while stack:
        item = stack.pop()
        if tuple(item.data(0, SCOPE_ROLE) or ()) == tuple(scope):
            target = item
            break
        stack.extend(item.child(i) for i in range(item.childCount()))
    if target is not None:
        tree.setCurrentItem(target)


def group_stats(entries) -> tuple[list[tuple[str, str, int, int]], int, int]:
    """([(kind, group, remaining, total)] by most remaining first, remaining, total) over translatable entries."""
    stats = _stats(entries, False)
    rows = [(scope[0], scope[1], todo, total) for scope, (todo, total) in stats.items() if len(scope) == 2]
    rows.sort(key=lambda row: (-row[2], row[0], row[1]))
    remaining, total = stats[()]
    return rows, remaining, total
