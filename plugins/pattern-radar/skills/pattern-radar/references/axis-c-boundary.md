# 軸C: 境界と外部依存

対象シグナル: 外部API / 外部SDK / Webhook / 決済 / メール配信サービス / タイムアウト /
リトライ / 二重実行 / モックが書けない / 相手先の仕様変更に引きずられる

---

## Adapter・Gateway

### 発火条件（いずれか）

- 外部SDKの型がドメイン層に露出している（`Stripe::Charge` や SDK のレスポンス Hash をモデル・ビューが直接触る）
- テストでモックが困難（SDK のクラスメソッドを直接呼んでおり、差し替え点が無い）
- 同じ外部エンドポイントの呼び出しが2箇所以上に書かれている

### 適用しない条件

- 使い捨ての一箇所呼び出し（rake タスク内の1回だけの呼び出しなど）

### 最小実装（Rails 7）

```ruby
# app/gateways/payment_gateway.rb
class PaymentGateway
  Charge = Struct.new(:id, :amount, :succeeded?, keyword_init: true)
  Error  = Class.new(StandardError)

  def charge(order)
    res = Stripe::Charge.create(amount: order.total_amount, currency: "jpy", source: order.token)
    Charge.new(id: res.id, amount: res.amount, succeeded?: res.status == "succeeded")
  rescue Stripe::StripeError => e
    raise Error, e.message      # 外部の例外型をドメインに漏らさない
  end
end
```

React+TypeScript では API 呼び出しを `src/api/*.ts` に閉じ、レスポンス型をアプリ側の型へ変換して返す
（軸J の Adapter層 を参照）。

### テストの置き方

- `spec/gateways/payment_gateway_spec.rb` でのみ SDK をスタブする。ここが外部と接する唯一の場所
- 呼び出し側のテストは Gateway をダブルに差し替える（SDK は登場させない）
- 契約テスト（VCR / WebMock）を置くならこのファイルに集約する

### よくある過剰適用の兆候

- Gateway が SDK のメソッドを1対1で委譲するだけで、戻り値も SDK の型のまま（変換していない＝適用の意味がない）
- Gateway がリトライ・ログ・キャッシュまで抱えて肥大している（Retry / Proxy として分ける）
- ドメイン側に `rescue Stripe::...` が残っている

---

## Anti-Corruption Layer（スタブ）

発火条件: 外部システムの語彙（項目名、状態値）が自システムと食い違い、変換表がコード中に散っている /
レガシーDBと新モデルの両方を同時に扱う。
適用しない条件: 外部の語彙と自システムの語彙が一致している。

## Facade（スタブ）

発火条件: 呼び出し側が3つ以上の下位オブジェクトを正しい順序で呼ぶ必要がある /
その呼び出し手順が2箇所以上に複製されている。
適用しない条件: 下位が1つ、または順序に制約がない。

## Proxy（スタブ）

発火条件: 本体を変えずに前後の処理（キャッシュ、遅延読み込み、アクセス記録）を挟みたい /
呼び出しインタフェースを変えられない。
適用しない条件: 本体を直接変更できる。

## Circuit Breaker（スタブ）

発火条件: 外部依存の障害時にリクエストが滞留し、こちら側まで落ちた実績がある /
外部の失敗率を監視して呼び出しを遮断する必要がある。
適用しない条件: 呼び出しが非同期ジョブ内のみで、失敗しても利用者影響が無い。

## Retry（スタブ）

発火条件: 相手が一時的失敗（5xx、タイムアウト）を返しうる、かつ操作が冪等である /
同じ `rescue ... retry` が2箇所以上にある。
適用しない条件: 操作が冪等でない（Idempotency Key を先に検討する）。

## Idempotency Key（スタブ）

発火条件: Webhook 受信や決済のように同一リクエストが再送される経路がある /
二重実行で金銭・在庫の不整合が起きる。
適用しない条件: 再送経路が存在せず、操作が読み取りのみ。
