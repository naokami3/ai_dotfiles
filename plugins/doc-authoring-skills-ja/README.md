# doc-authoring-skills-ja

技術ドキュメントの作成・レビュー用 Claude Code プラグイン（日本語版）。

## スキル一覧

| スキル | 説明 |
|--------|------|
| `write-adr` | ADR（Architecture Decision Record）を構造化フォーマットで作成 |
| `write-claude-md` | Anthropic推奨構成で CLAUDE.md を作成・更新 |
| `write-project-docs` | プロジェクトドキュメント（architecture.md, roadmap.md 等）の作成基準 |
| `review-docs` | 4軸評価（正確性・必要十分性・読者適合性・行動可能性）による独立ドキュメントレビュー |

## 設計思想

[Anthropicのハーネス設計研究](https://www.anthropic.com/engineering/harness-design-long-running-apps)の生成者-評価者パターンに着想を得て、ドキュメントの **作成**（write-*）と **評価**（review-docs）を分離しています。独立したレビュアーが、生成エージェントが自身の出力に対して行えない批判的フィードバックを提供します。

## インストール

```bash
# GitHub マーケットプレイスから
/plugin marketplace add naokami3/ai_dotfiles
/plugin install doc-authoring-skills-ja@ai-dotfiles

# ローカルテスト
claude --plugin-dir ./plugins/doc-authoring-skills-ja
```

## 使い方

```
/doc-authoring-skills-ja:write-adr
/doc-authoring-skills-ja:review-docs
```

## English Version

English version is available as: `doc-authoring-skills`

## ライセンス

MIT
