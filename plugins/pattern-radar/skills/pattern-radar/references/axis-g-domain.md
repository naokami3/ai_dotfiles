# 軸G: 値とドメイン

対象シグナル: 金額と通貨など常にセットで運ばれるプリミティブ / 書式・比較ロジックが helper に散る /
権限判定 / ロール分岐 / 管理者だけ許可 / どこまでを1トランザクションで守るか / 業務上の出来事の記録

---

## Value Object

### 発火条件（いずれか）

- プリミティブが常に2つ以上セットで運ばれる（`amount` と `currency`、`start_at` と `end_at`、`lat` と `lng`）
- その値の書式・比較ロジックが helper に散っている（同じ整形・等価判定が2箇所以上）
- メソッドの引数に同じプリミティブの組が3回以上現れる

### 適用しない条件

- 単独で意味が完結する値（`title`、`quantity` のように単体で解釈できる）

### 最小実装（Rails 7）

```ruby
# app/values/money.rb
class Money
  include Comparable

  attr_reader :amount, :currency

  def initialize(amount, currency = "JPY")
    @amount = BigDecimal(amount.to_s)
    @currency = currency
    freeze
  end

  def +(other)
    raise ArgumentError, "通貨が異なる" unless currency == other.currency

    Money.new(amount + other.amount, currency)
  end

  def <=>(other) = currency == other.currency ? amount <=> other.amount : nil
  def to_s = "#{currency} #{amount.to_i}"
end

# app/models/order.rb
class Order < ApplicationRecord
  def total = Money.new(total_amount, currency)
end
```

React+TypeScript では判別可能な型（`type Money = { amount: number; currency: Currency }`）と
純関数（`addMoney`, `formatMoney`）の組で同じ効果を得る。

### テストの置き方

- `spec/values/money_spec.rb` に等価性・比較・不正な組み合わせ（通貨違いの加算）を置く
- モデル spec では「Money を返すこと」だけ確認し、計算の詳細は Value Object 側に寄せる

### よくある過剰適用の兆候

- Value Object が可変（setter がある、`freeze` していない）
- DB アクセスや I18n の呼び出しを内部に持ち込んでいる
- 属性1つを包んだだけのクラスが増え、`.value` を経由する記述が全体に広がっている

---

## Policy Object

### 発火条件（いずれか）

- 権限判定の `if` がネストしている（`if admin? ... elsif owner? && !locked?` のような入れ子）
- ロール分岐が2ファイル以上に散っている（コントローラとビューの両方で同じ判定を書いている）

### 適用しない条件

- 判定が1箇所1条件（`if current_user.admin?` のみ）

### 最小実装（Rails 7）

```ruby
# app/policies/order_policy.rb
class OrderPolicy
  def initialize(user, order)
    @user = user
    @order = order
  end

  def show? = @user.admin? || owner?
  def update? = show? && @order.status == "draft"
  def destroy? = @user.admin?

  private

  def owner? = @order.user_id == @user.id
end

# app/controllers/orders_controller.rb
def update
  @order = Order.find(params[:id])
  head(:forbidden) and return unless OrderPolicy.new(current_user, @order).update?
  # ...
end
```

ビューでも同じ Policy を呼ぶ（判定の二重定義を作らない）。

### テストの置き方

- `spec/policies/order_policy_spec.rb` に「ロール × 状態」の表で全組み合わせを回す
- リクエスト spec では、許可されない場合に 403 を返すことを代表1本だけ置く

### よくある過剰適用の兆候

- Policy が権限以外の業務判定（在庫があるか、締切を過ぎたか）まで抱えている
- `?` メソッドが10個以上に膨らみ、画面ごとの都合が入り込んでいる
- Policy を通さない直接判定（`if current_user.admin?`）がコード中に残っている

---

## Aggregate 境界（スタブ）

発火条件: 1トランザクションで整合を守るべきモデル群と、そうでないものの区別が曖昧 /
子モデルが親を介さず直接更新されている箇所が3箇所以上。
適用しない条件: モデルが単独で完結し、整合を守る相手がいない。

## Domain Event（スタブ）

発火条件: 「注文が確定した」など業務上の出来事に対して、後から購読側（通知、集計、外部連携）が
増え続けている / 手続きの本体に無関係な処理が追記され続けている。
適用しない条件: 購読側が1つで、増える見込みがない。
