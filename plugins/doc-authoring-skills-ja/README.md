# doc-authoring-skills-ja

技術ドキュメントの作成・レビュー用スキル集（日本語版）。[Agent Skills オープン標準](https://agentskills.io) に準拠しているため、Claude Code 以外のエージェントでも利用できる。

## スキル一覧

| スキル | 説明 |
|--------|------|
| `write-adr` | ADR（Architecture Decision Record）を構造化フォーマットで作成 |
| `write-agent-instructions` | エージェント指示ファイル（AGENTS.md を正、CLAUDE.md はブリッジ）を作成・更新 |
| `write-project-docs` | プロジェクトドキュメント（architecture.md, roadmap.md 等）の作成基準 |
| `write-html-docs` | 人間向け HTML 資料（図付き概観・詳細仕様）を md 正典から作る基準。**オプション**（md だけで足りるなら作らない） |
| `review-docs` | 実装と突合した検証済み指摘（findings）を出し、総合判定を機械的に算出する独立レビュー。リンク全数検証スクリプト同梱 |

## 設計思想

[Anthropic のハーネス設計研究](https://www.anthropic.com/engineering/harness-design-long-running-apps)の生成者-評価者パターンに着想を得て、ドキュメントの **作成**（write-*）と **評価**（review-docs）を分離している。生成したエージェント自身は、自分の出力に対して批判的なフィードバックを出しにくいためである。

`review-docs` は次の2点で「それらしい評価」を避ける設計にしている。

- **findings が先、判定は後**: 実装と突合して検証済みの指摘を列挙し、総合判定はその severity から機械的に算出する。先に総合評価を決めてから根拠を探す形にしない
- **未検証を「問題なし」にしない**: 確認できなかった検証項目は「未検証」として明示的に報告する

各 `write-*` スキルは完了条件として `review-docs` による検証を含む。

ドキュメントの読者は二層に分ける: **エージェントは md（正典）を読み、人間は HTML（必要なら）を読む**。
HTML はオプションの成果物で、作る場合は `write-html-docs` に従い md 正典からの生成物として扱う
（手書きの二重管理をしない・最新性は検証ゲートで機械検査する）。

## インストール

スキルは `skills/<name>/SKILL.md` という標準構成なので、ツールごとの配置先にコピーまたはシンボリックリンクするだけで動作する。

### Claude Code（プラグインとして）

```bash
# GitHub マーケットプレイスから
/plugin marketplace add naokami3/ai_dotfiles
/plugin install doc-authoring-skills-ja@ai-dotfiles

# ローカルテスト
claude --plugin-dir ./plugins/doc-authoring-skills-ja
```

### その他のエージェント（スキルとして配置）

| ツール | 配置先 | 呼び出し |
|---|---|---|
| Claude Code | `.claude/skills/` または `~/.claude/skills/` | `/write-adr` |
| Codex CLI | `.agents/skills/` または `~/.agents/skills/` | `$write-adr` |
| GitHub Copilot | `.github/skills/` | 自動 |
| Cursor | `.cursor/skills/` | 自動 |
| Gemini CLI | `.gemini/skills/` | 自動 |

```bash
# 例: Codex CLI にリポジトリ単位で入れる
mkdir -p .agents/skills
cp -R plugins/doc-authoring-skills-ja/skills/* .agents/skills/
```

各スキルは標準のフロントマター（`name` / `description`）と本文だけで成立しており、ツール固有のフロントマターに依存していない。

## 使い方

Claude Code でプラグインとして導入した場合:

```
/doc-authoring-skills-ja:write-adr
/doc-authoring-skills-ja:write-agent-instructions
/doc-authoring-skills-ja:write-project-docs
/doc-authoring-skills-ja:write-html-docs
/doc-authoring-skills-ja:review-docs
```

`description` にトリガー条件を含めてあるため、明示的に呼ばなくても該当する作業時に自動で選択される。

## English Version

English version is available as: `doc-authoring-skills`

## 変更履歴

### 2.1.0

- 新スキル `write-html-docs` を追加: 人間向け HTML 資料（図付き概観・詳細仕様）を md 正典から
  作る基準。二層構成（人間=HTML / エージェント=md）の原則、生成器の fail closed 要件、
  生成物の非変更型最新性検査、図の作成基準（図は事実を主張する・SVG アクセシビリティ・
  ライト/ダーク対応・生成ページへのフラグメント注入）を規定。**HTML 作成はオプション**で、
  他スキルからは参照のみ
- `write-project-docs`: 大きくなったドキュメントの分割手順（行範囲コピー + 逸失検証 +
  互換アンカー索引）、実測記録・正典・橋渡しの 3 層分離パターン、エージェント向け参照文書の
  「この文書で分かること」ブロック、役割分担表への HTML 資料（オプション）行を追加
- `review-docs`: リンク・アンカー全数検証スクリプト `scripts/check-doc-links.py` を同梱し
  検証項目を機械化。HTML 資料向けの検証項目（タグ整合・ライト/ダーク実表示・図中の事実主張の
  突合・SVG アクセシビリティ）と、「新資料ではなく正典側が古い」ケースの扱い（実装を第三の
  照合点にする）を追加
- 全スキルのルーティング表に `write-html-docs` を追加

### 2.0.0

- **破壊的変更:** `write-claude-md` を `write-agent-instructions` にリネーム。AGENTS.md を一次ファイルとし、CLAUDE.md はブリッジとして扱う構成に変更した（Agent Skills 仕様は `name` に予約語 `claude` を含めることを認めていないため、命名も併せて是正）
- `review-docs` を findings 先行・判定は機械的算出の方式に再設計。未検証項目の扱いを明示
- 各 `write-*` の完了条件に `review-docs` による検証を追加
- `write-adr` に採番スクリプト `scripts/next-adr-number.sh` を同梱。決定内容の捏造を防ぐ規定を追加
- 全スキルにスキル間のルーティング表を追加
- Claude Code 以外のエージェント向けインストール手順を追加

## ライセンス

MIT
