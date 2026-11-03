# 検出器 YAML の書き方

入口分母は検出器（正規表現）の実行結果だけで作る。エージェントが入口を手で列挙してはいけない。
同梱の検出器で拾えないスタックでは、作業ディレクトリに検出器 YAML を追加で書いて実行する。

## 書式

```yaml
name: my-stack           # 検出器名（入口 ID には rule の id が使われる）
rules:
  - id: my-route         # 一意な ID
    kind: http_endpoint  # 下の種別のいずれか
    files: ["**/*.py"]   # 対象ファイルの glob（** / * / ? / {a,b}）。省略時は全ファイル
    exclude: []          # 除外する glob
    path_pattern: '...'  # ファイルパスに対する正規表現（任意）。名前付きグループをラベルに使える
    pattern: '...'       # ファイル内容に対する正規表現（任意）。MULTILINE。マッチ1件=入口1件
    label: "{method|upper} {path}"   # 名前付きグループを埋め込む。|upper |lower が使える
    normalize:           # ラベルに順に適用する置換 [正規表現, 置換文字列]
      - ['/index$', '']
```

- `pattern` と `path_pattern` の少なくとも一方が必要
- `pattern` が無いルールは「パスに一致したファイル1件 = 入口1件」（ファイルベースルーティング向け）
- `pattern` と `path_pattern` の両方があれば、両方の名前付きグループをラベルに使える
- 組み込み変数: `{file}`（ファイルパス）、`{match}`（マッチ文字列の1行目）
- YAML の単一引用符文字列の中で `'` は `''` と書く
- 既定では role が source / config のファイルだけを対象にする（テスト内の文字列を拾わない）

## 種別（kind）

| kind | 意味 |
|---|---|
| `http_endpoint` | HTTP API のエンドポイント |
| `ui_route` | 画面（URL を持つページ） |
| `cli_command` | CLI コマンド・スクリプトの入口 |
| `scheduled_job` | 定期実行 |
| `background_job` | 非同期ジョブ・キューのワーカー |
| `event_consumer` | メッセージ・イベントの購読 |
| `webhook` | 外部からのコールバック受信 |
| `data_entity` | テーブル・エンティティ定義 |
| `graphql_operation` | GraphQL の操作 |
| `rpc_method` | RPC・Server Actions 等 |
| `other` | 上のいずれでもない入口（ミドルウェア、マウント等） |

## 新しいスタック向けに書く手順

1. Phase 0 でスタックを判定したら、そのフレームワークの「ルート・ジョブ・CLI・モデルの宣言の書き方」を
   公式ドキュメントか実コード数件で確認する
2. 宣言の行に一致するパターンを書き、`enumerate_entrypoints.py` を実行する
3. 件数を `grep -c` 等の別手段と突き合わせる（ずれたらパターンを直す）
4. 抽出後に `check_coverage.py` が出す「分母に無かった入口の報告」が多い種別は、検出器の追加・修正候補
