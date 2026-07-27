# pattern-radar

デザインパターンの適用候補を、**観測可能なシグナルから逆引き**して提示する Claude Code プラグイン。

設計時とレビュー時で同じ発火条件を使う。候補を並べるところまでが責任範囲で、**採否の判断と実装はユーザーが行う**。

## 設計方針

| 原則 | 内容 |
|---|---|
| 逆引き索引 | 「パターン名 → 定義」ではなく「シグナル → 候補パターン」で引く |
| 数えられる発火条件 | ✗「複雑なフォーム」 / ✓「1アクション内で save または update! が2回以上」 |
| 適用しない条件を対で持つ | 書けない項目はそもそも作らない |
| 2段ルーティング | SKILL.md は10軸の要約のみ。詳細は該当軸の references だけを読む |
| 自動修正の禁止 | 検出しても提案までで止め、コードを書き換えない |
| シグナルから始める | 指摘の第1行は必ず検出した事実。パターン名から始めない |

## 使い方

```bash
# 設計相談・実装前の方針検討（会話の中で自動的に発火）
「この画面で User と Profile を同時に保存したい。どう設計する？」

# パスを指定して検査
/pattern-radar:pattern-radar app/controllers/orders_controller.rb

# git diff の変更範囲をレビュー
/pattern-radar:pattern-radar review
```

## 10軸

| 軸 | 対象 | 詳細を持つパターン |
|---|---|---|
| A | 分岐の増殖 | Strategy / State Machine / Null Object |
| B | 生成の複雑化 | （スタブのみ） |
| C | 境界と外部依存 | Adapter・Gateway |
| D | 手続きの肥大 | Service(Command) |
| E | データアクセス | Query Object |
| F | 入力と表示 | Form Object / Presenter・Decorator |
| G | 値とドメイン | Value Object / Policy Object |
| H | 副作用と通知 | （スタブのみ） |
| I | 横断関心 | （スタブのみ） |
| J | フロントエンド | （スタブのみ） |

スタブは発火条件1〜2行のみを持つ。詳細（実装例・テストの置き方・過剰適用の兆候）は必要になった時点で追記する。

## detect.rb

Ruby 標準ライブラリのみで動く正規表現ベースの検出器。完全性より誤検出の少なさを優先し、**閾値未満は出力しない**。

```bash
ruby skills/pattern-radar/scripts/detect.rb app/ src/
ruby skills/pattern-radar/scripts/detect.rb --diff        # 未ステージ＋ステージ済み＋未追跡
ruby skills/pattern-radar/scripts/detect.rb --diff main   # main...HEAD（ブランチ全体）
```

出力は JSON Lines。

```json
{"file":"app/controllers/orders_controller.rb","line":2,"signal":"persistence_calls_per_method","count":2,"threshold":2,"axis":"F/D"}
```

| signal | 内容 | 既定の閾値 | 軸 |
|---|---|---|---|
| `controller_action_lines` | controller の1アクションのコード行数 | 21 | D |
| `persistence_calls_per_method` | 1メソッド内の save/save!/update/update!/create! の回数 | 2 | F/D |
| `case_when_branches` | 1つの case に属する when 節の数 | 3 | A |
| `nil_checks_per_receiver` | 同一レシーバへの nil?/present?/blank? の回数 | 3 | A |
| `validates_with_context` | `validates ... on:` の出現 | 1 | F |
| `callback_block_lines` | after_commit / after_save のブロック行数 | 5 | H |
| `use_state_per_component` | 1コンポーネントあたりの useState 呼び出し数 | 3 | J |
| `prop_passthrough_components` | 受け取った同名 prop を素通し（`name={name}`）しているコンポーネント数 | 3 | J |

閾値は `scripts/detect.rb` 冒頭の `THRESHOLDS` にまとまっている。

ヒューリスティックの範囲:

- Ruby はコメント・文字列リテラルの中身を `Ripper.lex` で除外してから数える（`"save"` を呼び出しと数えない）
- `nil_checks_per_receiver` はスコープを見る。**メソッド内で代入されている名前（ローカル変数）は
  メソッドごとに別対象として数え**、属性・関連・ivar だけがファイル全体で1つの対象になる
  （別メソッドの同名ローカル変数を「同一対象への nil 判定」と誤報しないため）
- `prop_passthrough_components` は JSX の親子チェーンを解析しない。「props で受け取った名前をそのまま同名で子へ渡している」
  コンポーネントの**数**で伝播の段数を近似する（兄弟へ配るだけは1回、自前の useState を渡すだけは数えない）
- ディレクトリ展開時に `node_modules` `vendor` `tmp` `dist` などを除外し、シンボリックリンクは辿らず、512KB を超えるファイルは読まない

## 出力フォーマット（固定）

```
検出シグナル: <数えられる事実。ファイルと行を含む>
候補: A) <パターン名> B) <パターン名> C) 現状維持
帰結: A) <得るもの / 失うもの> B) <同> C) <同>
適用しない条件に該当するか: <該当有無と理由>
判断はユーザーに委ねる
```

## 決定の記録

後戻りコストが高い選択で AskUserQuestion を使った場合、回答を `<project>/.claude/decisions.md` に1行追記する。

```
- 2026-07-27 | app/controllers/orders_controller.rb#create | Form Object | 規約同意がカラムに無く、Order と Shipment を同時保存するため
```

同じ対象に既存の記録があれば再質問せず、その決定に従う。

## 構成

```
plugins/pattern-radar/
├── .claude-plugin/plugin.json
├── README.md
├── LICENSE
└── skills/pattern-radar/
    ├── SKILL.md
    ├── references/axis-a-branching.md … axis-j-frontend.md（10軸）
    ├── scripts/detect.rb
    └── evals/evals.json
```

## evals

優先10パターンそれぞれに、発火すべき依頼2件・発火してはいけない依頼2件・適用すべきコード1件・
指摘したら誤検出になるコード1件を用意している（計60件、skill-creator の evals 形式）。

## License

MIT
