# データ形式

作業ディレクトリ（以下 `W`）に置くファイルの形式。スクリプトが生成するものは手で編集しない。

| ファイル | 作る人 | 内容 |
|---|---|---|
| `files.json` | `build_file_manifest.py` | ファイル分母・除外一覧 |
| `inventory.json` | `enumerate_entrypoints.py` | 入口分母・除外ファイル内の入口候補 |
| `slices.json` | `plan_slices.py` | スライス定義（ID は内容ハッシュ由来）・読了確認の窓 |
| `briefs/<S>.md` | `slice_brief.py` | 抽出担当への作業票 |
| `extract/<S>.json` | 抽出担当エージェント | スライスごとの局所機能（下記） |
| `verify/<S>.json` | `verify_evidence.py` | スライスの検証結果・不合格回数 |
| `digest.txt` | `features.py digest` | 合格済み局所機能の1行ダイジェスト |
| `grouping.json` | オーケストレーター | ドメイン・機能のグループ分け（下記） |
| `features.json` | `features.py merge` | **正典**。機能一覧のすべての出力の元 |
| `review-batches/bNN.json` | `features.py sample` | 独立検証の対象 |
| `review/bNN.json` | 検証担当エージェント | 独立検証の結果（下記） |
| `coverage.json` | `check_coverage.py` | 網羅率 |
| `feature-inventory.{xlsx,html,md}` | `render_inventory.py` | 人間向けの成果物 |

## extract/<S>.json（抽出担当が書く）

```json
{
  "slice_id": "S5bde43",
  "slice_hash": "5bde435afde92c5e...",
  "read_checks": [
    {"path": "backend/app/api/routes/items.py", "line": 27, "quote": "statement = select(Item).offset(skip)"}
  ],
  "features": [
    {
      "local_id": "S5bde43-F1",
      "name": "アイテムの一覧表示",
      "summary": "ログインユーザーが自分のアイテムを一覧する。管理者のみ全ユーザーのアイテムを見られる。",
      "actors": [{"name": "ログインユーザー", "evidence": 0}, {"name": "管理者", "evidence": 1}],
      "constraints": [{"text": "全ユーザーのアイテムを見られるのは管理者のみ", "evidence": 1}],
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
     "reason_code": "ops_script", "reason": "リポジトリ運用（Issue の自動クローズ）でありシステムの機能ではない"}
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
| `slice_id` / `slice_hash` | 作業票の値をそのまま写す。違うと古い結果として不合格 |
| `read_checks` | 作業票の「読了確認」の**全区間**について、区間内の 10 文字以上ある行を1つずつ引用する |
| `local_id` | `<スライスID>-F<連番>`。一度使った番号を別の機能に使い回さない |
| `name` | 業務の言葉で、利用者から見た機能名。クラス名・関数名をそのまま使わない |
| `summary` | 誰が・何をできるか。コードで確認したことだけを書く |
| `actors` | 利用者の種類。**各要素に根拠（`evidence` の番号、0 始まり）を付ける** |
| `constraints` | 権限・条件・禁止事項（「〜のみ」「〜できない」等）。**各要素に根拠の番号を付ける**。summary に制約を書いたら必ずここにも書く |
| `entry_ids` | 作業票の入口 ID。入口の無い内部処理なら空配列 |
| `data` | 読み書きするテーブル・コレクション・主要なファイル |
| `external` | 外部サービス・他システム（メール送信、決済、S3 等） |
| `confidence` | 下の基準 |
| `evidence` | 1件以上必須。`quote` はその行に**実際に書かれている** 8 文字以上の断片（短い行は行全体）をそのまま写す |
| `open_questions` | コードだけでは断定できなかった点。`inferred` / `unknown` では必須 |
| `unmapped_entries` | 機能に対応付けない入口と、`reason_code`（下表）・具体的な理由 |
| `missing_entries` | 読んでいて見つけた、作業票に無い入口。`kind` は `references/detectors.md` の種別（該当なしは `other`） |

### 確信度の基準

| 値 | 基準 |
|---|---|
| `confirmed` | 入口から主要な処理・データ操作までをこのスライスのコードで確認した |
| `inferred` | 一部（スライス外の呼び出し先、設定値による有効/無効など）を推定で補った。補った点を `open_questions` に書く |
| `unknown` | コードは存在するが、目的や使われているかを断定できない。理由を `open_questions` に書く |

### 対象外の理由コード（reason_code）

| コード | 意味 |
|---|---|
| `health_check` | 死活監視・ヘルスチェック |
| `dev_tool` | 開発環境専用・開発支援 |
| `ops_script` | リポジトリ運用・リリース・CI |
| `test_support` | テスト用の入口 |
| `framework_internal` | フレームワークの仕組み（ミドルウェア、マウント等）で業務機能ではない |
| `data_definition` | テーブル定義・マイグレーション（関連する機能の `data` に反映済み） |
| `duplicate` | 同じ入口の重複定義 |
| `dead_code` | 使われていない疑い（呼び出し元・ルーティング登録が見つからない） |
| `other` | 上のいずれでもない（reason に具体的に書く） |

## grouping.json（オーケストレーターが書く）

`digest.txt` だけを見て書く。**書けるのは名前・グループ分け・sources・利用者表記の写像と、
複数 sources をまとめた機能の統合要約だけ。** 入口・データ・根拠・制約・確信度は `merge` が sources から引き継ぐ。

```json
{
  "system": {"name": "サンプル業務システム", "description": "1〜2文の説明"},
  "actor_map": {"ログインユーザー": "ログインユーザー", "ログイン中の利用者": "ログインユーザー", "管理者": "管理者"},
  "domains": [
    {
      "name": "アイテム管理",
      "summary": "利用者が自分のアイテムを登録・閲覧・更新・削除する。",
      "features": [
        {"name": "アイテムの一覧表示", "summary": "（sources が2件以上のときだけ書く。局所要約の統合）",
         "sources": ["S5bde43-F1", "S9a0c11-F3"]},
        {"name": "アイテムの登録", "sources": ["S5bde43-F3"]}
      ]
    }
  ]
}
```

- 全局所機能をどこかに1回だけ配置する（漏れ・重複配置は `merge` が不合格にする）
- `actor_map` には digest に出た局所の利用者表記をすべて書き、統一語彙に写像する（漏れは不合格）
- sources が1件の機能は summary を書かない（書いても無視され、局所要約がそのまま使われる）。name は言い換えてよい
- sources が2件以上の機能は summary が必須。局所要約に無い事実を足さない（統合要約は独立検証で重点的に見る）
- ドメインごとに別ファイルに分けてよい（`merge --grouping a.json b.json`）

## review-batches/bNN.json（`features.py sample` が書く）と review/bNN.json（検証担当が書く）

バッチには `repo`（対象リポジトリ）、`output`（結果の書き込み先）、`items` が入る。
items は `type: feature`（機能）と `type: unmapped_entry`（対象外にした入口）の2種類。

```json
{
  "results": [
    {
      "feature_key": "3f9a1c0b2e",
      "verdict": "partially_correct",
      "comment": "管理者は他人のアイテムも削除できる点が要約に無い",
      "evidence": [{"path": "backend/app/api/routes/items.py", "line": 105, "quote": "if not current_user.is_superuser and"}]
    }
  ],
  "entry_results": [
    {"entry_id": "fastapi-route@backend/app/api/routes/utils.py:29", "verdict": "correct", "comment": "ヘルスチェック"}
  ]
}
```

- `results[].verdict`: `correct` / `partially_correct` / `incorrect` / `unverifiable`。誤りの指摘には `evidence` が必須
- `entry_results[].verdict`: `correct`（対象外で正しい）/ `should_be_feature`（業務機能なので対応付けるべき）/ `unverifiable`
- `feature_key` は機能の sources から決まる。merge し直して機能の構成が変わると、古い結果は自動的に無視される
