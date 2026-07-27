# 軸D: 手続きの肥大

対象シグナル: コントローラが太い / 1アクションが長い / 複数モデル横断のトランザクション /
処理の途中で外部APIを呼ぶ / 似た手順が種別ごとに複製されている / 途中で失敗すると整合が崩れる

detect.rb の該当 signal: `controller_action_lines`

---

## Service（Command）

### 発火条件（いずれか）

- 複数モデル横断のトランザクション＋外部I/O（メール送信、外部API、ファイル出力）が同じ手続きに含まれる
- controller の1アクションが20行超

### 適用しない条件

- モデルのインスタンスメソッドで足りる（貧血ドメイン化のリスク）

### 最小実装（Rails 7）

```ruby
# app/services/orders/submit.rb
module Orders
  class Submit
    Result = Struct.new(:success?, :order, :error)

    def initialize(order) = @order = order

    def call
      ActiveRecord::Base.transaction do
        @order.update!(status: "submitted")
        Inventory.reserve!(@order)
      end
      OrderMailer.submitted(@order).deliver_later   # トランザクション外
      Result.new(true, @order, nil)
    rescue ActiveRecord::RecordInvalid, Inventory::OutOfStock => e
      Result.new(false, @order, e.message)
    end
  end
end

# app/controllers/orders_controller.rb
def submit
  result = Orders::Submit.new(Order.find(params[:id])).call
  result.success? ? redirect_to(result.order) : render(:show, alert: result.error)
end
```

呼び出し口は1つ（`call`）に固定する。副作用のうち外部I/Oはトランザクションの外に出す。

### テストの置き方

- `spec/services/orders/submit_spec.rb` に成功・失敗の両方を置く。失敗時にロールバックされることを必ず1本書く
- 外部I/Oはこのテストでのみスタブする。コントローラ spec では `Result` を返すことだけを確認する

### よくある過剰適用の兆候

- モデルが `attr_accessor` だけになり、振る舞いが全部 Service に吸われている（貧血ドメイン）
- Service が別の Service を3つ以上呼び、手続きの階層が深くなっている
- 1メソッドしか無く、モデルのメソッドをそのまま包んだだけの Service が増えている

---

## Interactor・UseCase（スタブ）

発火条件: 同じ手続きが複数の入口（Web / API / バッチ / rake）から呼ばれる /
入力の検証・実行・結果の表現をまとめて扱いたい。
適用しない条件: 入口が1つで、Service(Command) で足りる。

## Template Method（スタブ）

発火条件: 手順の骨格が同じで、差分が1〜2ステップだけのクラスが3つ以上ある。
適用しない条件: 差分がステップの中身ではなく手順の順序そのもの（Strategy か Pipeline を検討）。

## Pipeline（スタブ）

発火条件: 入力を段階的に変換する処理が4段以上あり、段の追加・削除が仕様変更で起きる /
各段が前段の出力だけに依存している。
適用しない条件: 段が2つで固定。

## Saga・Process Manager（スタブ）

発火条件: 複数サービス/外部システムをまたぐ手続きで、1つのDBトランザクションに収まらない /
途中失敗時に補償処理（キャンセル、返金）が必要。
適用しない条件: 単一DBのトランザクションで原子性が担保できる。
