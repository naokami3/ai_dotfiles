# データ形式

作業ディレクトリ（以下 `W`）に置くファイルの形式。スクリプトが生成するものは手で編集しない。

| ファイル | 作る人 | 内容 |
|---|---|---|
| `files.json` | `build_file_manifest.py` | ファイル分母・除外一覧 |
| `inventory.json` | `enumerate_entrypoints.py` | 入口分母 |
| `slices.json` | `plan_slices.py` | スライス定義 |
| `extract/<S>.json` | 抽出担当エージェント | スライスごとの局所機能（下記） |
| `verify/<S>.json` | `verify_evidence.py` | スライスの検証結果 |
| `digest.txt` | `features.py digest` | 局所機能の1行ダイジェスト |
| `grouping.json` | オーケストレーター | ドメイン・機能のグループ分け（下記） |
| `features.json` | `features.py merge` | **正典**。機能一覧のすべての出力の元 |
| `review-sample.json` | `features.py sample` | 独立検証の対象 |
| `review/<batch>.json` | 検証担当エージェント | 独立検証の結果（下記） |
| `coverage.json` | `check_coverage.py` | 網羅率 |
| `feature-inventory.{xlsx,html,md}` | `render_inventory.py` | 人間向けの成果物 |

## extract/<S>.json（抽出担当が書く）

```json
{
  "slice_id": "S001",
  "slice_hash": "329936b2cd23ed77",
  "read": [{"path": "backend/app/api/routes/items.py", "start": 1, "end": 110}],
  "features": [
    {
      "local_id": "S001-F1",
      "name": "アイテムの一覧表示",
      "summary": "ログインユーザーが自分のアイテムを一覧で見る。管理者は全ユーザーのアイテムを見られる。",
      "actors": ["ログインユーザー", "管理者"],
      "entry_ids": ["fastapi-route@backend/app/api/routes/items.py:13"],
      "data": ["item"],
      "external": [],
      "confidence": "confirmed",
      "evidence": [
        {"path": "backend/app/api/routes/items.py", "line": 13, "quote": "@router.get(\"/\", response_model=ItemsPublic)"},
        {"path": "backend/app/api/routes/items.py", "line": 22, "quote": "if current_user.is_superuser:"}
      ],
      "open_questions": []
    }
  ],
  "unmapped_entries": [
    {"entry_id": "github-actions-cron@.github/workflows/issue-manager.yml:5",
     "reason": "リポジトリ運用（Issue の自動クローズ）でありシステムの機能ではない"}
  ],
  "missing_entries": [
    {"kind": "http_endpoint", "label": "GET /health", "path": "backend/app/main.py", "line": 40,
     "quote": "app.add_route(\"/health\", health)"}
  ],
  "notes": []
}
```

| 項目 | 規則 |
|---|---|
| `slice_hash` | 作業票の `hash` をそのまま写す。違うと古い結果として不合格 |
| `read` | 実際に Read した範囲。全文読みの全項目を覆わないと不合格 |
| `local_id` | `<スライスID>-F<連番>` |
| `name` | 業務の言葉で、利用者から見た機能名。クラス名・関数名をそのまま使わない |
| `summary` | 誰が・何をできるか・どんな制約があるか。コードで確認したことだけを書く |
| `actors` | 利用者の種類（未ログイン / ログイン / 管理者 / システム（定期実行）など） |
| `entry_ids` | 作業票の入口 ID。入口の無い内部処理なら空配列 |
| `data` | 読み書きするテーブル・コレクション・主要なファイル |
| `external` | 外部サービス・他システム（メール送信、決済、S3 等） |
| `confidence` | 下の基準 |
| `evidence` | 1件以上必須。`quote` はその行に**実際に書かれている** 6 文字以上の断片をそのまま写す |
| `open_questions` | コードだけでは断定できなかった点。推測で埋めずにここへ書く |
| `unmapped_entries` | 機能に対応付けない入口（運用スクリプト、ヘルスチェック、開発用等）と理由 |
| `missing_entries` | 読んでいて見つけた、作業票に無い入口。`kind` は `references/detectors.md` の種別（該当なしは `other`）。検出器の改善に使う |

### 確信度の基準

| 値 | 基準 |
|---|---|
| `confirmed` | 入口から主要な処理・データ操作までをこのスライスのコードで確認した |
| `inferred` | 一部（スライス外の呼び出し先、設定値による有効/無効など）を推定で補った。補った点を `open_questions` に書く |
| `unknown` | コードは存在するが、目的や使われているかを断定できない |

## grouping.json（オーケストレーターが書く）

`digest.txt` だけを見て書く。**ここには名前・要約・グループ分け・sources しか書けない。**
入口・データ・根拠・確信度は `merge` が sources から機械的に引き継ぐ。

```json
{
  "system": {"name": "サンプル業務システム", "description": "1〜2文の説明"},
  "domains": [
    {
      "name": "アイテム管理",
      "summary": "利用者が自分のアイテムを登録・閲覧・更新・削除する。",
      "features": [
        {"name": "アイテムの一覧表示", "summary": "…", "actors": ["ログインユーザー"],
         "sources": ["S003-F1", "S005-F2"]}
      ]
    }
  ]
}
```

- 全局所機能をどこかに必ず配置する（漏れると `merge` が不合格）
- 同じ機能を API 側・画面側の両方から抽出していることが多い。sources に両方入れて1機能にまとめる
- `summary` は sources の局所要約を統合して書く。局所要約に無い事実を足さない

## review/<batch>.json（検証担当が書く）

```json
{
  "results": [
    {
      "feature_id": "F012",
      "verdict": "partially_correct",
      "comment": "管理者は他人のアイテムも削除できる点が要約に無い",
      "evidence": [{"path": "backend/app/api/routes/items.py", "line": 105, "quote": "if not current_user.is_superuser and"}]
    }
  ]
}
```

`verdict`: `correct` / `partially_correct` / `incorrect` / `unverifiable`。誤りの指摘には `evidence` が必須。
