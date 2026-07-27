# 軸A: 分岐の増殖

対象シグナル: case が伸びる / 仕様追加のたびに分岐が増える / status で振る舞いが変わる /
同じ対象への nil 判定が散る / 抽出条件が組み合わさる / 承認者が順番に処理する

detect.rb の該当 signal: `case_when_branches`, `nil_checks_per_receiver`

---

## Strategy

### 発火条件（いずれか）

- `case`/`when` がアルゴリズム選択であり、仕様追加のたびに `when` 節が伸びる（`when` 節が3つ以上）
- 同じ入力に対して「どの計算式を使うか」だけが異なる分岐が2箇所以上に複製されている
- 分岐の各枝が3行以上あり、枝ごとに必要なデータが異なる

### 適用しない条件

- 分岐が2つで、増える見込みがない
- 分岐が値の写像だけ（`when :a then 1`）で、Hash 定数で足りる

### 最小実装（Rails 7）

```ruby
# app/models/pricing/base.rb
module Pricing
  class Base
    def initialize(order) = @order = order
    def total = raise NotImplementedError
  end

  class Standard < Base
    def total = @order.subtotal
  end

  class Member < Base
    def total = @order.subtotal * 0.9
  end

  STRATEGIES = { standard: Standard, member: Member }.freeze

  def self.for(order) = STRATEGIES.fetch(order.plan.to_sym).new(order)
end

# 呼び出し側
Pricing.for(order).total
```

### テストの置き方

- `spec/models/pricing/member_spec.rb` のようにストラテジ単位で1ファイル。呼び出し側のテストは「選択が正しいか」だけに縮める
- `STRATEGIES` の全キーを回して `total` が数値を返すことを検証する網羅テストを1本置くと、追加漏れが落ちる

### よくある過剰適用の兆候

- ストラテジが1メソッドしか持たず、実体は Hash と Lambda で足りている
- 分岐条件そのもの（どのストラテジを選ぶか）に別の `case` が育っている
- ストラテジ間で共有したい状態が増え、`Base` に protected メソッドが積み上がっている

---

## State（State Machine）

### 発火条件（いずれか）

- `status` / `state` カラムがあり、取りうる値が3つ以上で、遷移規則（どこからどこへ行けるか）が決まっている
- 遷移に副作用がある（遷移時にメール送信、在庫引当、外部API呼び出しが伴う）
- `if status == "..."` の判定が2ファイル以上に散っている

### 適用しない条件

- 単なる真偽フラグ（`published` / `archived` の2値で、遷移規則も副作用もない）
- 値は複数あるが、遷移が自由（どの値からどの値へでも行ける）

### 最小実装（Rails 7 / gem を足さない場合）

```ruby
# app/models/order_state.rb
class OrderState
  TRANSITIONS = {
    "draft"     => %w[submitted canceled],
    "submitted" => %w[approved rejected],
    "approved"  => %w[shipped],
    "shipped"   => [],
  }.freeze

  def initialize(order) = @order = order

  def can?(to) = TRANSITIONS.fetch(@order.status, []).include?(to.to_s)

  def transition_to!(to)
    raise ArgumentError, "#{@order.status} -> #{to} は不正な遷移" unless can?(to)

    @order.transaction do
      @order.update!(status: to)
      after_transition(to)
    end
  end

  private

  def after_transition(to)
    ShipmentJob.perform_later(@order.id) if to.to_s == "shipped"
  end
end
```

React 18 では `useReducer` が同じ役割を果たす（軸J の Reducer・State Machine を参照）。

### テストの置き方

- `spec/models/order_state_spec.rb` に「許可される遷移」「禁止される遷移」を表で回す
- 副作用は遷移テストとは別に、`transition_to!("shipped")` で Job がエンキューされることだけを検証する

### よくある過剰適用の兆候

- 状態が2つしかないのに遷移テーブルと専用クラスがある
- 遷移メソッドが状態ごとに増え続け、`transition_to!` 以外の入口が生まれている
- 遷移表に載っていない更新（`update!(status: ...)`）がモデル側に残っている

---

## Null Object

### 発火条件（いずれか）

- 同一対象への `nil?` / `present?` / `blank?` による分岐が3箇所以上ある
- `user&.profile&.name || "ゲスト"` のような安全呼び出し＋既定値が2箇所以上で重複している
- ビューとモデルの両方で同じ nil 分岐を書いている

### 適用しない条件

- nil が例外的で、分岐が1箇所しかない
- nil であること自体がエラーで、既定の振る舞いが定義できない（この場合は例外を投げる）

### 最小実装（Rails 7）

```ruby
# app/models/guest_user.rb
class GuestUser
  def name = "ゲスト"
  def admin? = false
  def registered? = false
end

# app/controllers/application_controller.rb
def current_user
  @current_user ||= User.find_by(id: session[:user_id]) || GuestUser.new
end
```

### テストの置き方

- `spec/models/guest_user_spec.rb` で、実クラスと同じメッセージに答えることを検証する
- 実クラスと Null Object の両方に同じ shared_examples を当てると、インタフェースのずれが落ちる

### よくある過剰適用の兆候

- Null Object 側が「何もしない」以上のロジックを持ち始めている
- `is_a?(GuestUser)` という判定が生まれ、消したはずの nil 分岐が名前を変えて復活している
- 呼び出し側が Null Object を保存しようとしてエラーになる

---

## Polymorphism・STI（スタブ）

発火条件: 同じ `case type` が2箇所以上にあり、分岐対象がそのままモデルの種別である /
種別ごとに固有カラムが3つ以上ある。
適用しない条件: 種別ごとの差分が表示文言だけ。

## Specification（スタブ）

発火条件: 「対象を満たすか」の判定条件が2つ以上の場所（画面の絞り込みとバッチの抽出）で
一致している必要がある / 判定と検索の両方で同じ条件を書いている。
適用しない条件: 条件が1箇所でしか使われない。

## Chain of Responsibility（スタブ）

発火条件: 順番に評価し、最初に該当したものが処理を打ち切る分岐が4段以上ある /
処理の順序自体が仕様として与えられている（承認フロー、割引の適用順）。
適用しない条件: 順序に意味がなく、単なる並列判定。
