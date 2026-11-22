# Usability design notes

These notes record the standard usability guidelines I looked up and how they were applied to this UI, with the goal that translators can translate "without getting lost, without stopping, and with a sense of progress". Sources are listed at the end. In the material I found, there is little decisive research on the usability of translation tools (mostly vendor articles and small studies), so this builds on well-established general guidelines.

## Guidelines and how they are reflected in this UI

| Guideline (source) | How it is reflected in this UI |
| --- | --- |
| **Visibility of system status** (NN/g 1) | Progress bar, counts, and "untranslated / total" in the category tree. Save state is shown in the status bar. The "Progress" tab shows progress per type and the number of entries translated today. The sidebar also shows progress for item names and descriptions only (Names and descriptions). Reviewed rows that still have QA errors are not counted as reviewed. |
| **Match between system and the real world** (NN/g 2) | The category tree uses plain wording ("Def text / UI text / Name lists"); technical names (such as DefInjected) are kept in tooltips. |
| **User control and freedom** (NN/g 3) | Focus mode exits with Esc. Ctrl+Z / Ctrl+Y while typing. Bulk changes can be undone. Autosave and history. |
| **Consistency and standards** (NN/g 4, GNOME) | Common keys keep their usual meaning: Ctrl+S, Ctrl+Z, Esc, F1, Tab, and so on. Custom shortcuts use Ctrl+letter or F-keys. |
| **Error prevention** (NN/g 5) | Translations that break placeholders or tags are blocked before export, and all reasons for blocking are shown together at once. The quality check (Ctrl+Shift+K) and Ctrl+E "Review before export" gather, in the same screen, not only errors but also untranslated rows, rows whose source changed, and rows marked reviewed that still have errors. Marking a row as reviewed is also refused, with the reason shown, when QA errors remain. |
| **Recognition rather than recall** (NN/g 6) | Shortcuts are shown on buttons and menus. F1 opens the keyboard shortcut list. |
| **Flexibility and efficiency of use** (NN/g 7, research on translation tools) | A full pass is possible with the keyboard alone: Alt+Down/Up (next/previous item), F3 / Ctrl+J (next untranslated), Ctrl+Shift+J (next needs-review, keeping the current filter), Ctrl+Return (mark reviewed and go to next), Ctrl+Shift+Return (mark reviewed and go to next untranslated / needs-review), Ctrl+K (mark "Review later"), Ctrl+Shift+1 to 3 (insert a suggestion), Ctrl+1 to 4 (tabs), Ctrl+L (search). |
| **Aesthetic and minimalist design** (NN/g 8) | On a real device (1366x768), the list, source, and translation field fit without scrolling. On short screens, auxiliary rows are collapsed. Focus mode shows only the source and the translation field, enlarged. |
| **Help users recognize, diagnose, and recover from errors** (NN/g 9) | Errors say in plain words which item is wrong and what is wrong with it. Multiple errors are shown as a list. Extraction diagnostics also describe what happened and the next step in plain words; the original developer-oriented text is folded into "Technical details". |
| **Help and documentation** (NN/g 10) | First-run guide and the F1 list. For each row, the "reason it became a target" is shown in the technical details, and manually excluded rows get a ⊘ mark in the list. |
| **Full keyboard operation** (GNOME HIG, Phrase) | Logical Tab order and visible focus. Closing a dialog returns focus to where it was. |
| **Closer to the goal, faster the pace** (goal-gradient effect) | The Progress tab shows "N more to finish ThingDef" and surfaces the types with the fewest remaining entries. |

## Screen layout

- Top tabs: **Translate / Review / Progress / Export**. The list being edited and the input fields stay on the same screen (they are used back and forth, so they are not split across tabs).
- Category tree on the left, list on the right, source and translation field below. The tree can be hidden with Ctrl+T.
- **Focus mode** (Ctrl+Shift+F): only the source and the translation field. Ctrl+Return marks as reviewed and moves to the next untranslated row.
- Two color schemes, light and dark ("View" menu, Ctrl+Shift+D). Text-to-background contrast of 4.5 or more for every combination is guaranteed by tests.

## Visual design (added 2026-11-15)

In addition to the usability guidelines, I looked up visual design techniques and applied them. Search results were mostly secondary sources (summaries and companies' design systems); the official Material Design 3 pages and the NN/g article on table design could not be confirmed. Only points on which several sources agree were adopted.

| Technique (source) | How it is reflected in this UI |
| --- | --- |
| **Build hierarchy with size, weight, and color; add color last** (summary of Refactoring UI) | One accent color (indigo). Supporting information is small gray text. Only the primary action gets a filled button. |
| **Choose spacing and font sizes from a fixed scale** (same) | Spacing is in multiples of 4; corner radii are unified to 7 / 10 / 12. |
| **For few, short options use chips rather than a dropdown; above 8 options use a list** (SAP Fiori, Uxcel) | The 6 main statuses became chips with counts. All statuses, including reviewed and approved, remain in the dropdown, and the two are kept in sync. |
| **Chips filter, buttons execute** (Uxcel) | Chips only narrow the list. Saving and exporting are buttons. |
| **Mark the state in tables, size columns to the longest value, left-align text** (Elastic UI and others) | Colored markers in the status column. Grid lines removed and rows made taller. The source and translation columns share the remaining width. |
| **Header actions only for the current context** (GNOME HIG) | Language and version are combined in a single bar, and version actions are tucked into a menu. |
| **Show the source and translation side by side, with the item list beside or above** (Crowdin, Poedit) | Keeps the layout with the source and translation side by side below the list. |

How verified: off-screen rendered screenshots and automated tests. How it looks on a real device (Windows, real Japanese fonts) has not been confirmed.

## Cross-check against primary sources (added 2026-11-15)

These are the points fixed after reading the official documents directly and comparing them with the UI. WCAG is a standard for the web, so applying it to a desktop app is by analogy. The content of two official Material Design 3 pages (chips, color roles) could not be retrieved, so the official Android implementation documentation was used for chips instead.

| Source | Criterion | Response |
| --- | --- | --- |
| WCAG 2.2 1.4.11 (AA) | Boundaries needed to identify a component, such as input borders, must have at least 3:1 against their surroundings | Changed the input border color (previously about 1.6:1, now 3.2:1 or more). Verified against all backgrounds in tests. |
| WCAG 2.2 2.4.13 (AAA) | Focus indicator equivalent to a 2px perimeter, at least 3:1 | Focus outline on inputs and buttons is 2px. Color is 5.6:1 or more. |
| WCAG 2.2 2.5.8 (AA) | Targets at least 24x24px | Chip height is 26px. |
| WCAG 2.2 1.4.1 (A) | Do not convey information by color alone | Status is "marker + text"; the selected chip is "fill + bold + border". |
| GNOME HIG buttons | Only one suggested (emphasized) button per screen | The sidebar's "New translation" and the first button on the Export tab were made regular buttons. Only "Export translation mod" is emphasized. |
| GNOME HIG header bars | Tooltips on primary actions | Added descriptive tooltips to save and export. |
| GNOME HIG / Fluent 2 typography | No all-caps text; reduce the variety of sizes and weights | Removed "WELCOME". |
| NN/g visual hierarchy | At most 3 text sizes | Unified to 3 levels: small, body, title (verified by tests). Subheadings are distinguished by weight. |
| Windows typography | Minimum 12px (Regular) | Lower bound for small text set to 9pt (12px). |
| NN/g data tables | Make it obvious at a glance that a filter is active; do not let users lose their place in rows | "Clear filters" is shown only while filtering. Hover highlight on rows. |
| NN/g progressive disclosure | Show only the main options first; one entry point to details, at most two levels | Main statuses as chips, all statuses in a single dropdown. |

Not adopted: the GNOME HIG guidance "header buttons are frameless with icons" was set aside because the app has no icon set. A full realignment to Fluent 2's spacing scale (4px base) has not been done because it would affect the existing checks that keep the UI fitting on small screens.

## Playfulness (added 2026-11-18)

This is a tool used for long stretches every day, so I did not add visual elements; I added them through motion and wording. The rationale is the "goal-gradient effect" (table above) and the guideline on showing status.

- Milestone messages: only at 25/50/75/100% progress and at the 1st/10th/50th/100th entry today. Not shown every time (it would be noise). Shown at the right of the status bar for 7 seconds, no click needed.
- The progress bar glides for about 0.26 seconds, only while the window is visible. No extra text or colors; the accent stays the existing `ok` color.
- The wording is not overly polite, and since this is a tool to be published, no dialect is used.
- "View > Reduce motion" stops the progress bar glide (saved in settings). Qt cannot reliably read the OS reduced-motion setting (on Linux / offscreen it always reports disabled), so there is no automatic link to the OS setting.
- The message text color `ok` is guaranteed by tests to have at least 4.5:1 against the status bar background `status` as well (light 5.05, dark 8.85).
- Progress is capped at 99% while even one entry remains (so that 199 of 200 does not show "100% - time to export").
- Not handled: in projects over 5000 entries the count update is delayed, so the moment a message appears can drift when it overlaps with a filter operation. Translations that were deleted and retyped also count toward "today's count". How it looks on a real device (Windows) has not been confirmed.

## Input assistance (added 2026-11-20)

Past translations of the same source are shown with numbers in an empty translation field and can be inserted with Ctrl+Shift+1 to 3. The "Suggestions" tab to the right of the edit field lists translations of the same source, the game's official translations, existing translations from prerequisite MODs, and glossary terms. The Ctrl+M "Translation memory" dialog is also kept. Below the input field are a button for inserting symbols from the source and a guide to the width of short fields.

## Future work (not implemented)

- Combine version and language actions into one row to reduce the header further.
- Verify the experience with screen readers (currently only accessible names are set).

## Sources

- Nielsen Norman Group, [10 Usability Heuristics for User Interface Design](https://www.nngroup.com/articles/ten-usability-heuristics/)
- GNOME Human Interface Guidelines, [Keyboard](https://developer.gnome.org/hig/guidelines/keyboard.html)
- Phrase, [Why accessibility matters in translation tools](https://phrase.com/blog/posts/why-accessibility-matters-translation-tools/)
- Laws of UX, [Goal-Gradient Effect](https://lawsofux.com/goal-gradient-effect/)
- [Book summary: Refactoring UI](https://sglavoie-github-io.pages.dev/posts/2023/09/09/book-summary-refactoring-ui/) (secondary source)
- SAP Fiori for Android, [Chips: usage](https://www.sap.com/design-system/fiori-design-android/v26-4/components/input-and-selection/chips/usage)
- Uxcel, [Chips: anatomy](https://uxcel.com/lessons/anatomy-694)
- Elastic UI, [Tables: layout guidelines](https://eui.elastic.co/docs/components/tables/layout-guidelines/)
- GNOME Human Interface Guidelines, [Header bars](https://developer.gnome.org/hig/patterns/containers/header-bars.html)
- Crowdin, [Online editor](https://support.crowdin.com/online-editor/)
- Poedit, [Features](https://poedit.com/features/)
- W3C, Understanding WCAG 2.2: [1.4.11 Non-text Contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html), [2.4.13 Focus Appearance](https://www.w3.org/WAI/WCAG22/Understanding/focus-appearance.html), [2.5.8 Target Size (Minimum)](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html), [1.4.1 Use of Color](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html), [1.4.3 Contrast (Minimum)](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)
- GNOME HIG: [Buttons](https://developer.gnome.org/hig/patterns/controls/buttons.html), [Typography](https://developer.gnome.org/hig/guidelines/typography.html), [Sidebars](https://developer.gnome.org/hig/patterns/nav/sidebars.html), [UI styling](https://developer.gnome.org/hig/guidelines/ui-styling.html)
- Nielsen Norman Group: [Data Tables](https://www.nngroup.com/articles/data-tables/), [Visual Hierarchy](https://www.nngroup.com/articles/visual-hierarchy-ux-definition/), [Progressive Disclosure](https://www.nngroup.com/articles/progressive-disclosure/), [Filter Categories and Values](https://www.nngroup.com/articles/filter-categories-values/), [Empty States](https://www.nngroup.com/articles/empty-state-interface-design/)
- Microsoft: [Fluent 2 Layout](https://fluent2.microsoft.design/layout), [Fluent 2 Typography](https://fluent2.microsoft.design/typography), [Windows typography](https://learn.microsoft.com/en-us/windows/apps/design/style/typography), [Windows spacing](https://learn.microsoft.com/en-us/windows/apps/design/style/spacing)
- Material Components for Android, [Chip](https://github.com/material-components/material-components-android/blob/master/docs/components/Chip.md)
