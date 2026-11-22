"""Short encouragements shown while translating.

Kept to round numbers so they stay rare: a message on every entry would turn into noise.
"""
from __future__ import annotations

MILESTONES = ((25, '4分の1まで来た。', 'A quarter of the way.'),
              (50, '半分まで来た。折り返し。', 'Halfway there.'),
              (75, 'あと4分の1。', 'Down to the last quarter.'),
              (100, '全項目の翻訳が済んだ。保存して書き出そう。', 'Everything is translated. Save and export.'))

DAILY = {1: ('今日の1件目。', 'First one of the day.'),
         10: ('今日10件。いい調子。', '10 today. Nice pace.'),
         50: ('今日50件。かなり進んだ。', '50 today. Good progress.'),
         100: ('今日100件。ひと息入れてもいい頃。', '100 today. Maybe take a breather.')}


def progress_cheer(before: int, after: int, english: bool = False) -> str:
    """The highest milestone passed going from `before` to `after` percent; empty when none was passed."""
    passed = [m for m in MILESTONES if before < m[0] <= after]
    if not passed:
        return ''
    return passed[-1][2 if english else 1]


def daily_cheer(count: int, english: bool = False) -> str:
    text = DAILY.get(count)
    return text[1 if english else 0] if text else ''


def today_line(count: int, english: bool = False) -> str:
    """The progress page line: always shows the count, and the wording follows it."""
    if english:
        if count == 0:
            return 'Nothing translated yet today. Start with one.'
        tail = 'Keep going.' if count < 10 else 'Nice pace.' if count < 50 else 'Good progress.' if count < 100 else 'Maybe take a breather.'
        return f'Entries you translated today: {count}. {tail}'
    if count == 0:
        return '今日はまだ0件。最初の1件から始めよう。'
    tail = 'ここから伸ばそう。' if count < 10 else 'いい調子。' if count < 50 else 'かなり進んだ。' if count < 100 else 'ひと息入れてもいい頃。'
    return f'今日、新しく訳した項目: {count} 件。{tail}'
