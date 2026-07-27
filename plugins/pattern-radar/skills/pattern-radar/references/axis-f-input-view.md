# 軸F: 入力と表示

対象シグナル: フォーム / 複数モデル保存 / 規約同意チェックボックス / DBカラムに無い入力項目 /
確認用パスワード / 表示専用メソッドがモデルにある / helper が引数だらけ / API レスポンスの整形

detect.rb の該当 signal: `persistence_calls_per_method`, `validates_with_context`

---

## Form Object

### 発火条件（いずれか）

- 1リクエストで2モデル以上を保存する（1アクション内で `save` / `update!` / `create!` が2回以上）
- DBカラムに対応しない入力項目がある（規約同意、確認用入力、一時トークンなど）
- `validates` に `on:` を使ってコンテキスト分岐している

### 適用しない条件

- 単一モデルに素直に写像でき、全フィールドがカラムである

### 最小実装（Rails 7）

```ruby
# app/forms/registration_form.rb
class RegistrationForm
  include ActiveModel::Model

  attr_accessor :name, :email, :agreed_to_terms

  validates :name, :email, presence: true
  validates :agreed_to_terms, acceptance: true   # カラムに無い入力項目

  def save
    return false if invalid?

    ActiveRecord::Base.transaction do
      user = User.create!(name: name, email: email)
      Profile.create!(user: user, display_name: name)
      @user = user
    end
    true
  end

  attr_reader :user
end

# app/controllers/registrations_controller.rb
def create
  @form = RegistrationForm.new(form_params)
  @form.save ? redirect_to(@form.user) : render(:new, status: :unprocessable_entity)
end
```

### テストの置き方

- `spec/forms/registration_form_spec.rb` に、コントローラを介さずフォーム単体で `valid?` / `save` の分岐を検証する
- コントローラ側のテストは「フォームを呼び、失敗時に 422 を返すか」だけに縮める
- カラムに無い項目（`agreed_to_terms`）の検証はフォームにしか書かない。モデル側に重複させない

### よくある過剰適用の兆候

- フォームがモデルのバリデーションをそのまま写経している（二重定義）
- 属性が1つしかないフォームが増えている
- フォームが保存以外（メール送信、外部API）まで抱え、Service(Command) と役割が重なっている

---

## Presenter・Decorator

### 発火条件（いずれか）

- 表示専用メソッドがモデルに侵入している（`full_name_with_title`、`status_label`、`formatted_price` など2つ以上）
- helper が引数だらけ（同じモデルの属性を3つ以上引数で受け取る helper がある）
- 同じ整形ロジックがビューとメーラーとAPIの2箇所以上で重複している

### 適用しない条件

- ビューロジックが数行で、そのビューでしか使わない

### 最小実装（Rails 7）

```ruby
# app/presenters/order_presenter.rb
class OrderPresenter
  def initialize(order, view)
    @order = order
    @view = view
  end

  def status_label
    @view.tag.span(I18n.t("order.status.#{@order.status}"), class: "badge-#{@order.status}")
  end

  def formatted_total = @view.number_to_currency(@order.total)
end

# app/controllers/orders_controller.rb
def show
  @order = OrderPresenter.new(Order.find(params[:id]), view_context)
end
```

React 18 では表示専用の変換を持つ純関数コンポーネント、または `useMemo` での派生値が同じ役割になる。

### テストの置き方

- `spec/presenters/order_presenter_spec.rb` に、モデルのダブルを渡して出力文字列を検証する
- View spec / system spec では整形の細部を検証しない（Presenter 側に寄せる）

### よくある過剰適用の兆候

- Presenter がモデルへの委譲メソッド（`delegate :name, to: :order`）ばかりになっている
- Presenter が DB を叩き始めている（クエリは Query Object の担当）
- Presenter を通さない直接描画が残り、整形が2系統になっている

---

## View Model（スタブ）

発火条件: 1画面が3モデル以上のデータを組み合わせて表示する / インスタンス変数が
1アクションで4つ以上生まれている。
適用しない条件: 画面が単一モデルの一覧・詳細。

## Serializer（スタブ）

発火条件: 同じモデルの JSON 表現が2種類以上ある（一覧用・詳細用、公開用・管理用） /
`as_json(only:, include:)` の指定がコントローラに散っている。
適用しない条件: JSON 表現が1種類で、モデルの属性そのまま。
