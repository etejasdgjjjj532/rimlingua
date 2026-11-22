# rimlingua

*RimWorld の MOD を多言語に翻訳するエディター*

[English](README.md) · [はじめての使い方](docs/GETTING_STARTED.ja.md) · [導入・ビルド手順](docs/DISTRIBUTION.md) · [変更履歴](CHANGELOG.md)

元 MOD の文章を読み取り、選んだ言語の翻訳を編集して、独立した翻訳 MOD を作るデスクトップアプリです。翻訳は利用者が入力するか、既存の翻訳から取り込みます。元 MOD のファイルを変更せず、作業データとゲーム用ファイルを別のフォルダーに保存します。

**ポータブル版は Python・Git・VS Code のインストール不要です。** RimWorld と翻訳対象の元 MOD は別途必要です。画面のメニューは日本語・英語、翻訳先は日本語を含む29言語に対応します。

## 最初の翻訳

1. アプリを起動し、**ファイル → 新しい翻訳**で元 MOD を選びます。Steam Workshop の一覧は名前・ID・作者で検索でき、お気に入りに登録できます。手元のフォルダーからも選べます。
2. 翻訳先の言語、抽出に使うゲーム版・有効 MOD を確認し、アプリや元 MOD と別の場所に作業を保存します。通常の保存先候補は `Documents/RimWorldTranslations/` です。生成する翻訳 MOD の出力先は、初期状態では作業フォルダー内の `mod/` で、**プロジェクト → 出力先フォルダーを設定**でプロジェクトごとに変えられます。元 MOD・Steam Workshop・ゲームの `Data`・設定で追加した MOD フォルダーの中には出力できません。
3. 一覧で項目を選び、下の翻訳欄へ入力します。**保存して書き出す（Ctrl+S）**で作業データとゲーム用 XML を更新します。編集を止めてからしばらくすると自動保存・書き出しも試みます（初期値は60秒。**ヘルプ → 設定・文字サイズ・ゲームの場所 → 一般**で10〜3600秒に変更でき、0で無効）。書き出す前に内容を確かめたいときは **ファイル → 翻訳 MOD を書き出す（Ctrl+E）**を使います。
4. **プロジェクト → 品質チェック…（Ctrl+Shift+K）**と**プロジェクト → 抽出と翻訳の診断**を確認し、**ゲーム → 翻訳 MOD を導入・更新**で導入内容を確認します。その後、RimWorld の MOD 画面で元 MOD と翻訳 MOD を有効にし、翻訳 MOD を元 MOD より後に読み込みます。

書き出しに失敗した場合も、先に保存できた作業データは残ります。画面に「XML 更新には診断の修正が必要」と出たら修正して再度保存してください。導入済みの翻訳 MOD は保存だけでは更新されないため、再度 **導入・更新**が必要です。

画像付きの選択からゲームでの確認、取り込み、復元までの手順は[はじめての使い方](docs/GETTING_STARTED.ja.md)にあります。

## 起動と配布状況

現在の版は **0.3.0** です。Linux x86_64 のポータブル版と、Wine 上で生成した Windows x64 EXE/ZIP をローカルに保存しています。Windows ZIP の名前には `wine-preview` が付き、Windows 実機での起動・DPI を確認済みとは扱いません。ネイティブ Windows ビルドと実際の CI 実行は未実施です。公開ダウンロードページはまだありません。

Linux のローカル生成物は `dist/linux-current/RimWorldTranslationEditor/` にあります。フォルダー全体を保持し、同名の実行ファイルを開きます。

```bash
./dist/linux-current/RimWorldTranslationEditor/RimWorldTranslationEditor
# 作業データを直接開く
./dist/linux-current/RimWorldTranslationEditor/RimWorldTranslationEditor /path/to/project/project.json
# ポータブル版の版・同梱ランタイムを確認
./dist/linux-current/RimWorldTranslationEditor/RimWorldTranslationEditor --version
./dist/linux-current/RimWorldTranslationEditor/RimWorldTranslationEditor --self-test
```

`_internal/` は実行に必要です。実行ファイルだけを別の場所へ移動しないでください。Linux は対応する glibc とデスクトップ環境が必要です。ビルド環境の実値は同梱の `release-manifest.json` にあります。展開方法、Windows の準備、OS 別ビルドは[導入・ビルド手順](docs/DISTRIBUTION.md)を参照してください。

## 主な操作

- **多言語編集**: 言語ごとに訳・確認済み・承認済みの状態を保存します。再スキャンで同じキーの訳を維持し、変更された原文や旧項目を区別します。**確認済みにする**は、プレースホルダーやタグが崩れるなど QA エラーが残る行には使えず、進捗の確認済み件数にも数えません。
- **取り込みと交換**: 既存の翻訳 MOD・言語フォルダー・XML・CSV・gettext PO・unified diff（.diff／.patch）をプレビューして取り込みます。差分は基準 XML のあるフォルダーを明示して読み取り専用で照合します。異なる既存訳は初期状態で保護します。CSV は UTF-8 のほか Excel の Shift_JIS、区切りがカンマ・セミコロン・タブのものを読み込みます。**ファイル → CSV を書き出す**は選択中の全言語を出力し、**詳しい列を付ける**と元ファイル・状態・以前の英文・メモも出ます。**PO を書き出す**は現在の言語を出力し、メモ・以前の英文・要確認（fuzzy）の印を含みます。**他の翻訳 MOD と照らし合わせる…**で、他の人の翻訳 MOD との違いを確認して取り込めます。
- **一括作業と候補**: 訳文の一括置換は適用前に比較でき、取り込み・一括置換を元に戻す／やり直す操作があります。編集欄の横の**候補**タブには、同じ原文の訳、公式訳、前提 MOD の既存の訳、用語集の用語が並びます（Ctrl+Shift+1〜3 で挿入）。編集欄の下には、原文の記号（`{0}` など）を入れるボタンと、ボタンのラベルなど短い欄の幅の目安も表示されます。**編集 → 用語集**には、同じ英語に複数の訳がある用語を見つける**訳のぶれ**タブがあります。**メモ**タブで項目ごとのメモと印（後で見直す など）を付けられ、**プロジェクト → ファイルごとの担当者…**で元ファイルごとに担当者名を記録できます。
- **絞り込みと進み具合**: 状態（QA エラーあり を含む）、Def の種類、元ファイル、メモの印で一覧を絞り込めます。Ctrl+J／Ctrl+Shift+J で次の未訳／次の要確認へ、Ctrl+Shift+Return で確認済みにして次へ、Ctrl+K で「後で見直す」を付け外しできます。サイドバーには全体の進み具合に加えて、アイテム名・説明だけの進み具合（名前・説明）を表示します。
- **抽出条件**: ゲーム版と有効 MOD を画面で指定し、LoadFolders や条件付き項目を判定します。ゲームの MOD 設定（`ModsConfig.xml`）の取り込みは読み取り専用で、場所は設定の**フォルダー**タブで指定できます（Linux の Proton の保存先も自動で探します）。複数の版を宣言する MOD では、**プロジェクト → 版ごとの状態…**、**別の版へ訳を引き継ぐ…**（プレビュー付き。確認・承認は引き継ぎません）、**版どうしを比べる…**で版ごとの違いを確認できます。複数版の試験出力は `mod-test/` に作られます。
- **診断**: プレースホルダー、対応するタグ、改行、空白、用語、訳の不一致を確認できます。診断は平易な言葉で表示し、元の開発者向けの文面は**技術的な詳細**に畳んであります。項目を特定できる診断はダブルクリックで編集欄へ移動します。各行には**対象になった理由**（なぜその文章が翻訳対象に入ったか）が技術的な詳細に表示され、手動で除外した行は一覧に ⊘ が付きます。**プロジェクト → 前提 MOD…**は、足りない前提 MOD を名前・packageId・Workshop のリンクで一覧し、見つかった MOD ごとに依存する行数を示します。
- **品質チェックと書き出し前の確認**: **プロジェクト → 品質チェック…（Ctrl+Shift+K）**は、エラー・原文が変わった行・表記や文体（全角半角の混在、半角カナ、原文のまま、文末・文体の不揃い）・未訳・確認済みなのにエラーの行をまとめて調べます。**翻訳 MOD を書き出す（Ctrl+E）**は、チェック結果と出力ファイルの増減を確認してから書き出します。エラーがあると書き出しません。
- **導入とテスト**: 生成翻訳だけをゲームへ導入し、更新時は以前の翻訳をバックアップします。依存 MOD・読み込み順の診断はゲーム設定を読み取ります。隔離したゲームコピーで起動テストもできます。
- **履歴と復元**: 保存時にローカル履歴を記録し、画面から復元できます。残す世代数は設定の**出力**タブで決められます。Git がない場合はファイル形式の履歴を使用します。過去の Git 履歴を読むには Git が必要です。
- **表示と設定**: **ヘルプ → 設定・文字サイズ・ゲームの場所**は **一般**（言語・配色・8〜24ポイントの文字サイズ・自動保存の間隔・設定の書き出しと取り込み）、**フォルダー**（Workshop・ゲームの Mods・追加の MOD フォルダー・`ModsConfig.xml`。読み取り専用）、**抽出**（ゲームの場所・ゲーム版ライブラリ・C# 情報の読み取り・キャッシュの場所と消去）、**出力**（翻訳者名・ライセンス・翻訳先言語の既定とバックアップの世代数）の4つのタブに分かれています。小さいウィンドウではサイドバーを省略し、メニューやスクロールから操作できます。Qt 標準のボタンやファイルダイアログは画面の言語に従いますが、一部の独自ダイアログ・診断文は日本語のままです。

## 作業データと互換性

```text
RimWorldTranslations/Example-JP/
  project.json
  .git/ または .history/              ローカル履歴
  mod/                                既定の出力先（変更できる。複数版の試験出力は mod-test/）
    .rimworld-translator.json         生成ファイルの管理情報
    About/About.xml
    About/Preview.png
    Languages/Japanese/
      DefInjected/ThingDef/Translations.xml
      Keyed/Keyed.xml
```

既存の `schema: 1` の日本語・多言語プロジェクトを引き続き開けます。バックアップや引っ越しでは、隠しフォルダーの履歴を含む**プロジェクトフォルダー全体**をコピーしてください。元 MOD の場所は作業データに記録されるため、再スキャンにはその元 MOD が必要です。1つのファイルで受け渡したいときは **ファイル → プロジェクトバンドルを書き出す…**で `.rwtbundle` を作ります（訳・確認状態・用語集・メモ・担当者・版を含み、元 MOD の場所は含みません）。受け取る側は **プロジェクトバンドルを開く…**で、自分の PC にある同じ元 MOD を選んで読み込みます。履歴（`.git/`・`.history/`）は含まれません。

アプリの更新は、作業を保存してバックアップし、新しいアプリフォルダーに置き換える方法です。別に保存した翻訳プロジェクトを保持し、以前のアプリを残して新しいアプリで開く・編集・保存・書き出しを確認してください。

更新確認は初期状態で無効です。公開された実在の GitHub `owner/repository` を設定して利用者が有効にした場合だけ、**ヘルプ → アップデートを確認**から安定版の通知を確認できます。定期確認・自動ダウンロード・自動インストールは行いません。公開先未設定なら通信しません。

## 抽出と検証の範囲

抽出はゲーム版に応じた LoadFolders、XML 継承、対応するパッチ操作、リストのキー、既存翻訳カタログ、C# フィールドのメタデータを利用します。DLL のメタデータは実行せずに読みます。情報が不足する場合はフィールド名などの推定を使い、根拠と警告を表示します。

動的に生成される文章、DLL に埋め込まれた文章、独自パッチ、他 MOD の条件や定義を必要とする内容は完全には再現できません。ゲームを起動して全文章を取得する仕組みではなく、100%の抽出や全 MOD の互換性は保証しません。未訳の項目は元の文章に戻り、重複・旧項目・手動で除外した項目は書き出しません。確認・承認は出力の必須条件ではありません。プレースホルダーや対応するタグにエラーがあると、選択中の言語を含む MOD 全体の書き出しを止めます。

検証は次の範囲を区別しています。

| 検証 | 確認したこと・限界 |
| --- | --- |
| 自動テスト・実 MOD の読み取り | 19 Workshop MOD と Core のスキャン、独立した XML 出力確認、元ファイルの不変性を確認。全項目の抽出率やゲーム画面表示を意味しません。 |
| Linux の実ゲーム | 6個の実 MOD から生成した日本語の `ThingDef.label` が読み込まれ、隔離 RimWorld 内の診断用 `Verse.Window` に表示されたことを確認。通常の装備・建築・プレイ画面や全言語の表示は未確認です。 |
| Linux エディター | 最新ポータブル版を別の場所へ展開し、Python・GitをPATHから外して、Waylandの100%・200%表示、編集・保存・出力・ファイル履歴・小型画面のスクロール／Ctrl+Sを確認。物理ディスプレイは1366×768です。 |
| Windows Wineプレビュー | 実際のx64 EXEを展開し、Python・GitをPATHから外して100%・200%の同じ操作をWineで確認。Windows実機・Windowsのゲーム内表示の証拠ではありません。 |
| Windows・CI・公開リリース | 手順と workflow は準備済み。ネイティブ Windows 環境と remote repository がないため、実行結果・公開ダウンロードは未取得です。 |

最新の展開済みLinux版のレポートは `artifacts/linux-portable-current-verification/archive-report.json`、Windows Wine版は `artifacts/windows-portable-verification/archive-report.json` にあります。実 MOD のレポートは `artifacts/installed-verification-final.json`、`artifacts/sol-runtime/runtime-ui-report.json`、画面証拠は `artifacts/sol-runtime/isolated-run/game-translation-proof.png` にあります。これらのゲーム／MOD 由来の資料は配布物に含めません。最終の検証結果は各レポートの実値を参照してください。

## ソースから起動・開発する場合

開発時のみ Python 3.11 以上と依存ライブラリーが必要です。[開発・設定隔離の手順](docs/DEVELOPMENT.md)も参照してください。Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install '.[dev]'
./run.sh
# 既存プロジェクト
./run.sh /path/to/project/project.json
# 同じ起動方法
.venv/bin/python -m rimworld_translator
.venv/bin/python run.py
```

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install '.[dev]'
.venv\Scripts\python.exe -m rimworld_translator
```

Linux の `./install-launcher.sh` はソース環境用のユーザーランチャーを追加します。登録先は `~/.local/share/applications/rimworld-translator.desktop` です。ポータブル版の導入とは別の手順です。

```bash
.venv/bin/python tools/run_tests.py
.venv/bin/python tools/run_tests.py --script tools/smoke_gui.py
.venv/bin/python tools/verify_installed.py --report artifacts/installed-verification-final.json
.venv/bin/python tools/build_portable.py --dry-run
```

実 MOD の検証にはインストール済みのゲームと Workshop MOD が必要です。独自パスは `verify_installed.py --game /path/to/RimWorld` で指定します。ネイティブ GUI・DPI とポータブルビルドの検証コマンドは[導入・ビルド手順](docs/DISTRIBUTION.md)にあります。

## 配布時の著作権と不具合報告

公開する翻訳 MOD の名前・翻訳者・説明・翻訳ライセンスは **プロジェクト → 配布用 MOD 情報**で編集できます。**ファイル → Workshop 用の文章を作る…**は、タイトル・説明（BBCode）・更新内容・公開前チェック・タグの雛形をテキストファイルに保存します。エディターが Workshop へ公開することはなく、公開は利用者が自分で行います。元画像を使いたくない場合は同画面の **元 MOD のプレビュー画像を使う**を外します。独自の背景に国旗を載せた画像を生成します。

配布対象は通常、生成した翻訳 MOD のフォルダー（既定は `mod/`）です。元 MOD の DLL・英語 XML はコピーしません。原文を含む `project.json`・履歴や、元作者の画像を加工した Preview の公開には、元作品の利用条件と許諾を確認してください。国旗素材は [flag-icons の MIT ライセンス](rimworld_translator/assets/flags/LICENSE)、同梱ライブラリーは [Third-party notices](packaging/THIRD_PARTY_NOTICES.md)を参照してください。エディター本体は [MIT ライセンス](LICENSE)です。非公式のファンツールで、Ludeon Studios とは無関係です。RimWorld は同社の商標です。ゲームのファイルは同梱せず、インストール済みのゲームから読み取った名前表は利用者のキャッシュに作られます(配布物には含みません)。キャッシュの場所は設定の**抽出**タブで変更でき、**キャッシュを消去…**はエディターが作った `game-table`・`schema` フォルダーだけを削除します。

不具合は **ヘルプ → 問題報告用の情報をコピー**で環境情報を取得し、操作手順・期待した結果・実際の結果を添えて作者へ報告してください。公開 Issues の URL は未設定です。公開先を用意した場合に使う[不具合報告](.github/ISSUE_TEMPLATE/bug_report.yml)と[機能提案](.github/ISSUE_TEMPLATE/feature_request.yml)のテンプレートがあります。詳細は[ガイドのトラブル対応](docs/GETTING_STARTED.ja.md#困ったとき)を参照してください。

## ライセンス

Mozilla Public License 2.0（`LICENSE` を参照）。Copyright (c) 2026 goma。

## 免責事項

これはコミュニティ製のツールで、無償で配布しています。Ludeon Studios とは無関係です。以下は RimWorld の利用規約が求める表示です。

Portions of the materials used to create this content/mod are trademarks and/or copyrighted works of Ludeon Studios Inc. All rights reserved by Ludeon. This content/mod is not official and is not endorsed by Ludeon.
