# 軸E: データアクセス

対象シグナル: 条件の組み合わせが多い where / 同じ where が2箇所 / 検索フォームの絞り込み /
集計・レポート / 一覧の並び替えと絞り込みが増える / 読み取りと書き込みで必要な形が違う

---

## Query Object

### 発火条件（いずれか）

- 条件を3つ以上組み合わせる（検索フォームの絞り込み、期間＋状態＋担当者など）
- 同一の複雑な `where` が2箇所以上に書かれている（照合の基準: 3条件以上を含む同一の条件列が2ファイル以上に現れる）
- 集計・レポート系（`group` / `sum` / `join` を含み、モデルの1レコードに対応しない結果を返す）

### 適用しない条件

- 単純 scope（1条件で、モデルの `scope` 1行に収まる）

### 最小実装（Rails 7）

```ruby
# app/queries/orders_query.rb
class OrdersQuery
  def initialize(relation = Order.all) = @relation = relation

  def call(status: nil, from: nil, to: nil, assignee_id: nil)
    scope = @relation
    scope = scope.where(status: status)              if status.present?
    scope = scope.where(created_at: from..)          if from.present?
    scope = scope.where(created_at: ..to)            if to.present?
    scope = scope.where(assignee_id: assignee_id)    if assignee_id.present?
    scope
  end
end

# app/controllers/orders_controller.rb
def index
  @orders = OrdersQuery.new.call(**search_params.to_h.symbolize_keys)
end
```

戻り値は ActiveRecord::Relation のままにする（呼び出し側で `page` / `order` を足せる）。

### テストの置き方

- `spec/queries/orders_query_spec.rb` に、条件の組み合わせごとに件数を検証するテストを置く
- 条件を1つも渡さない場合に全件を返すことを1本書く（絞り込み漏れの検出）
- コントローラ spec ではクエリの中身を検証しない

### よくある過剰適用の兆候

- Query Object が `scope 1つ` を包んだだけになっている
- 返り値が配列になっており、呼び出し側で追加の絞り込みができない
- クエリの中で表示用の整形（`map` して Hash 化）まで行っている（Presenter / Serializer の担当）

---

## Data Mapper・Repository（スタブ）

発火条件: ドメインオブジェクトを ActiveRecord から独立させたい要求がある /
永続化先が2つ以上（DB と外部API）に分かれている。
適用しない条件: Rails の ActiveRecord をそのまま使えており、置き換え予定がない。

## Unit of Work（スタブ）

発火条件: 1つの業務操作で更新するモデルが4つ以上あり、保存順序に依存がある /
コミット単位を呼び出し側が制御する必要がある。
適用しない条件: `ActiveRecord::Base.transaction` のブロックで足りる。

## CQRS（スタブ）

発火条件: 読み取り専用の集計要求が書き込みモデルの形と一致せず、参照用のテーブル/ビューを
別に持っている / 読み取り負荷と書き込み負荷を分離する必要がある。
適用しない条件: 同一モデルの読み書きで性能・形状の問題が出ていない。
