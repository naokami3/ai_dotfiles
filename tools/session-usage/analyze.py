#!/usr/bin/env python3
"""Claude Code のセッション記録からトークン使用量とコストを集計する。

~/.claude/projects/*/*.jsonl を読み、モデル別のトークン消費、コンテキストの
肥大の推移、会話内容の構成比を出力する。--simulate を付けると、実装ターンを
サブエージェントに委譲した場合のコストを仮定ベースで試算する。

使い方:
    python3 analyze.py                      # 全セッションの要約
    python3 analyze.py -p xrev              # プロジェクト名で絞り込み
    python3 analyze.py -d                   # コンテキスト推移と内容構成も出す
    python3 analyze.py --simulate           # 分担した場合のコストを試算
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from collections import defaultdict

# 単価（USD / 1Mトークン）。モデルIDの前方一致で判定する。
# 価格帯名（"opus" / "sonnet"）での部分一致は使わない。同じ価格帯でも世代で
# 単価が変わるため、部分一致だと新しいモデルを黙って古い単価で計算してしまう。
# 未登録のモデルは計上せず、実行後に警告を出す。
PRICE: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

# 課金対象外の疑似モデル。未計上の警告には出さない。
NON_BILLED_MODELS = {"<synthetic>"}

CACHE_READ_RATE = 0.10   # キャッシュ読み込みは入力単価の10%
CACHE_WRITE_RATE = 1.25  # キャッシュ書き込みは入力単価の1.25倍（5分TTL前提）

# 実装作業とみなすツール。--simulate で委譲対象を判定するのに使う。
IMPL_TOOLS = {"Edit", "Write", "NotebookEdit", "Bash", "BashOutput", "KillShell"}

SESSION_ROOT = os.path.expanduser("~/.claude/projects")

# --simulate の仮定。すべてCLIから上書きできる。
# キー -> (既定値, 型, ヘルプ)
SIM_PARAMS: dict[str, tuple[str | int, type, str]] = {
    "main-model": ("claude-opus-5", str, "メイン側のモデル"),
    "delegate-model": ("claude-sonnet-5", str, "委譲先のモデル"),
    "handoff-input": (40_000, int, "引き継ぎ1回の入力トークン"),
    "handoff-output": (2_500, int, "引き継ぎ1回の出力トークン"),
    "review-turns": (10, int, "レビュー1パスのターン数"),
    "review-input-start": (20_000, int, "レビュー初回の入力トークン"),
    "review-input-step": (9_000, int, "レビュー1ターンあたりの入力増分"),
    "review-output": (1_200, int, "レビュー1ターンの出力トークン"),
    "sub-initial-context": (3_000, int, "サブエージェントの初期コンテキスト"),
}


def model_price(model: str | None) -> tuple[float, float] | None:
    """モデル名から単価を引く。前方一致する登録名のうち最長のものを採用する。

    未登録のモデルは None を返す。呼び出し側で未計上として警告すること。
    """
    name = model or ""
    matched = [k for k in PRICE if name.startswith(k)]
    if not matched:
        return None
    return PRICE[max(matched, key=len)]


def cost(price: tuple[float, float], inp: int, cache_read: int, cache_write: int, out: int) -> float:
    price_in, price_out = price
    return (
        inp * price_in
        + cache_read * price_in * CACHE_READ_RATE
        + cache_write * price_in * CACHE_WRITE_RATE
        + out * price_out
    ) / 1e6


def approx_tokens(text: str) -> int:
    """日英混在テキストの粗いトークン近似。構成比を見る用途にのみ使う。"""
    return max(1, len(text) // 3)


def flatten(content) -> str:
    """メッセージの content からテキスト量を取り出す。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(flatten(x) for x in content)
    if isinstance(content, dict):
        if isinstance(content.get("text"), str):
            return content["text"]
        if "content" in content:
            return flatten(content["content"])
        if content.get("type") == "tool_use":
            return json.dumps(content.get("input", {}), ensure_ascii=False)
        return json.dumps(content, ensure_ascii=False)
    return ""


def is_duplicate(rec: dict, seen_uuid: set, seen_request: set) -> bool:
    """既出のレコードなら True を返し、初出なら見たキーを記録する。

    uuid と requestId は存在するときだけキーに使う。None を混ぜると、
    欠損したレコードの2件目以降が全て重複扱いで落ちてしまう。
    両方欠損したレコードは判定できないので残す（呼び出し側で数える）。
    """
    uuid, request_id = rec.get("uuid"), rec.get("requestId")
    if uuid:
        if uuid in seen_uuid:
            return True
        seen_uuid.add(uuid)
    if request_id:
        if request_id in seen_request:
            return True
        seen_request.add(request_id)
    return False


def parse_session(path: str) -> dict:
    """1セッションのJSONLを読み、課金対象ターンと内容構成を返す。

    同一 requestId のレコードが複数回現れるため（アシスタントの応答が
    thinking / text / tool_use のブロックごとに別レコードとして書かれ、
    同じ usage を繰り返す）、重複を除去しないと2倍以上に過大計上される。
    """
    seen_uuid: set = set()
    seen_request: set = set()
    turns: list[dict] = []
    composition: dict[str, int] = defaultdict(int)
    unknown_models: dict[str, int] = defaultdict(int)
    unpriced_tokens = 0
    no_id_records = 0

    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = rec.get("message") or {}
            content = message.get("content")

            # 内容構成は課金レコード以外（ユーザー発話・ツール結果）も対象にする
            if content is not None:
                if rec.get("type") == "user":
                    is_tool_result = isinstance(content, list) and any(
                        isinstance(x, dict) and x.get("type") == "tool_result" for x in content
                    )
                    key = "ツール実行結果" if is_tool_result else "ユーザー発話"
                    composition[key] += approx_tokens(flatten(content))
                elif rec.get("type") == "assistant":
                    blocks = content if isinstance(content, list) else [content]
                    for block in blocks:
                        kind = block.get("type") if isinstance(block, dict) else "text"
                        key = {
                            "tool_use": "ツール呼び出し",
                            "thinking": "思考",
                            "text": "アシスタント発話",
                        }.get(kind or "text", "その他")
                        composition[key] += approx_tokens(flatten(block))

            usage = message.get("usage")
            if not usage:
                continue
            if is_duplicate(rec, seen_uuid, seen_request):
                continue
            if not rec.get("uuid") and not rec.get("requestId"):
                no_id_records += 1

            tools = (
                {x.get("name") for x in content if isinstance(x, dict) and x.get("type") == "tool_use"}
                if isinstance(content, list)
                else set()
            )
            turn = {
                "model": message.get("model"),
                "input": usage.get("input_tokens", 0),
                "cache_read": usage.get("cache_read_input_tokens", 0),
                "cache_write": usage.get("cache_creation_input_tokens", 0),
                "output": usage.get("output_tokens", 0),
                "is_impl": bool(tools & IMPL_TOOLS),
                "is_sub": bool(rec.get("isSidechain")),
            }
            turns.append(turn)

            model = turn["model"]
            if model_price(model) is None and model not in NON_BILLED_MODELS:
                unknown_models[model or "(モデル名なし)"] += 1
                unpriced_tokens += (
                    turn["input"] + turn["cache_read"] + turn["cache_write"] + turn["output"]
                )

    return {
        "project": os.path.basename(os.path.dirname(path)),
        "session": os.path.basename(path)[:8],
        "turns": turns,
        "composition": dict(composition),
        "unknown_models": dict(unknown_models),
        "unpriced_tokens": unpriced_tokens,
        "no_id_records": no_id_records,
    }


def session_cost(turns: list[dict]) -> float:
    """記録された使用量から実測コストを求める。未登録モデルは加算しない。"""
    total = 0.0
    for t in turns:
        price = model_price(t["model"])
        if price:
            total += cost(price, t["input"], t["cache_read"], t["cache_write"], t["output"])
    return total


def simulate_split(turns: list[dict], params: dict) -> dict:
    """実装ターンを委譲した場合のコストを、明示した仮定のもとで試算する。

    実測値の延長ではなく仮定ベースのシナリオ比較。両シナリオとも入力を
    キャッシュ読み込み単価で近似し、同じ価格前提どうしを比べる。分担後の
    キャッシュ書き込み量は予測できないため、片側だけ1.25倍で課金すると
    削減率が実態より大きく出てしまう。

    委譲したターンが生んだコンテキスト増分は、以降メイン側に積まれない
    ものとして計算する。サブエージェントの重複読み込みは計上していないため
    分担側を過小に、委譲対象を実装ツール使用ターンのみに限っているため過大に
    見積もる。

    既存のサイドチェーン（サブエージェント）は主系列と系列が異なり、
    コンテキストの増分を共有できないため対象から除外する。
    """
    main_price = PRICE[params["main_model"]]
    sub_price = PRICE[params["delegate_model"]]

    main_turns = [t for t in turns if not t["is_sub"]]
    skipped_sub_turns = len(turns) - len(main_turns)

    scenario_base = sum(
        cost(main_price, 0, t["input"] + t["cache_read"] + t["cache_write"], 0, t["output"])
        for t in main_turns
    )

    removed = 0                                # メインコンテキストから外れた累積分
    sub_ctx = params["sub_initial_context"]    # 作業指示書＋システムプロンプト相当
    main_cost = sub_cost = 0.0
    prev_ctx = 0
    impl_turns = 0

    for t in main_turns:
        ctx = t["input"] + t["cache_read"] + t["cache_write"]
        delta = max(0, ctx - prev_ctx)
        prev_ctx = ctx
        if t["is_impl"]:
            impl_turns += 1
            sub_ctx += delta
            sub_cost += cost(sub_price, 0, sub_ctx, 0, t["output"])
            removed += delta
        else:
            main_cost += cost(main_price, 0, max(0, ctx - removed), 0, t["output"])

    # 引き継ぎ（指示書の作成＋実装結果の受け取り）
    handoff = cost(
        main_price, 0, params["handoff_input"], 0, params["handoff_output"]
    )
    # レビュー1パス（委譲先が差分を読みテストを実行する想定）
    review = sum(
        cost(
            sub_price,
            0,
            params["review_input_start"] + i * params["review_input_step"],
            0,
            params["review_output"],
        )
        for i in range(params["review_turns"])
    )

    return {
        "scenario_base": scenario_base,
        "scenario_split": main_cost + sub_cost + handoff + review,
        "main": main_cost,
        "sub": sub_cost,
        "handoff": handoff,
        "review": review,
        "impl_turns": impl_turns,
        "main_turns": len(main_turns),
        "skipped_sub_turns": skipped_sub_turns,
    }


def print_summary(sessions: list[dict]) -> None:
    header = f"{'プロジェクト':<30} {'session':<9} {'ターン':>6} {'sub':>4} {'入力':>13} {'出力':>9} {'入:出':>7} {'$':>9}"
    print(header)
    print("-" * len(header))
    grand = 0.0
    for s in sessions:
        turns = s["turns"]
        inp = sum(t["input"] + t["cache_read"] + t["cache_write"] for t in turns)
        out = sum(t["output"] for t in turns)
        c = session_cost(turns)
        grand += c
        subs = sum(1 for t in turns if t["is_sub"])
        print(
            f"{s['project'][:30]:<30} {s['session']:<9} {len(turns):>6} {subs:>4} "
            f"{inp:>13,} {out:>9,} {inp // max(out, 1):>6}:1 {c:>9.2f}"
        )
    print(f"{'合計':<30} {'':<9} {'':>6} {'':>4} {'':>13} {'':>9} {'':>7} {grand:>9.2f}")


def print_detail(s: dict) -> None:
    turns = s["turns"]
    ctxs = [t["input"] + t["cache_read"] + t["cache_write"] for t in turns]
    if not ctxs:
        return
    print(f"\n=== {s['project']} / {s['session']} ===")
    print(f"  1ターンあたり入力: 平均 {sum(ctxs) // len(ctxs):,} / 最小 {min(ctxs):,} / 最大 {max(ctxs):,}")
    q = len(ctxs) // 4
    if q:
        print("  コンテキストの推移:")
        for i in range(4):
            seg = ctxs[i * q :] if i == 3 else ctxs[i * q : (i + 1) * q]
            print(f"    第{i + 1}四分位: 平均 {sum(seg) // len(seg):>9,} tok ({len(seg)}ターン)")
    total = sum(s["composition"].values()) or 1
    print("  会話内容の構成（近似）:")
    for k, v in sorted(s["composition"].items(), key=lambda x: -x[1]):
        print(f"    {k:<14} {v:>10,} tok  {v / total * 100:>5.1f}%")


def print_simulation(sessions: list[dict], min_turns: int, params: dict) -> None:
    print("\n=== 分担した場合の試算（仮定ベースのシナリオ比較） ===")
    print(
        f"  メイン {params['main_model']} / 委譲先 {params['delegate_model']} / "
        f"レビュー{params['review_turns']}ターン"
    )
    header = (
        f"{'セッション':<26} {'ターン':>6} {'実装':>5} {'実測$':>9} {'比較基準$':>10} "
        f"{'委譲案$':>9} {'基準比':>7}   内訳"
    )
    print(header)
    print("-" * 120)
    skipped_total = 0
    for s in sessions:
        if len(s["turns"]) < min_turns:
            continue
        r = simulate_split(s["turns"], params)
        if r["scenario_base"] <= 0:
            continue
        skipped_total += r["skipped_sub_turns"]
        observed = session_cost(s["turns"])
        name = f"{s['project'][-16:]}/{s['session']}"
        reduction = (1 - r["scenario_split"] / r["scenario_base"]) * 100
        print(
            f"{name:<26} {r['main_turns']:>6} {r['impl_turns']:>5} {observed:>9.2f} "
            f"{r['scenario_base']:>10.2f} {r['scenario_split']:>9.2f} {reduction:>6.1f}%   "
            f"main {r['main']:.2f} / sub {r['sub']:.2f} / 引継 {r['handoff']:.2f} / レビュー {r['review']:.2f}"
        )
    print()
    print("※ 実測$ は記録された使用量とモデル別単価から算出した値。")
    print("   比較基準$ と 委譲案$ は同じ価格仮定（全キャッシュ読み込み近似）で計算した")
    print("   仮定ベースの値で、実測$ とは前提が異なる。基準比は 比較基準$ と 委譲案$ の比較。")
    if skipped_total:
        print(f"※ 既存サイドチェーンの {skipped_total} ターンは試算から除外した。")
    print("※ 本試算は仮定への感度が高く、精度を保証しない。複数のパラメータ設定で")
    print("   削減傾向が維持されるかを確認する用途に限定すること。")


def print_warnings(sessions: list[dict]) -> None:
    unknown: dict[str, int] = defaultdict(int)
    unpriced_tokens = 0
    no_id_records = 0
    for s in sessions:
        for model, n in s["unknown_models"].items():
            unknown[model] += n
        unpriced_tokens += s["unpriced_tokens"]
        no_id_records += s["no_id_records"]

    if unknown:
        print("\n警告: 価格未登録のモデルがあり、コストに含まれていません")
        for model, n in sorted(unknown.items(), key=lambda x: -x[1]):
            print(f"  {model}  {n}ターン")
        print(f"  未計上トークン合計: {unpriced_tokens:,}")
        print("  analyze.py の PRICE に単価を追加してください。")
    if no_id_records:
        print(f"\n警告: uuid と requestId の両方が無いレコードが {no_id_records} 件あり、")
        print("      重複除去できていません。過大計上の可能性があります。")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Claude Code のトークン使用量を集計する")
    parser.add_argument("-p", "--project", help="プロジェクト名の部分一致で絞り込む")
    parser.add_argument("-d", "--detail", action="store_true", help="コンテキスト推移と内容構成を出す")
    parser.add_argument("--simulate", action="store_true", help="分担した場合のコストを試算する")
    parser.add_argument("--min-turns", type=int, default=10, help="試算対象の最小ターン数（既定10）")
    parser.add_argument("--root", default=SESSION_ROOT, help="セッション記録のディレクトリ")
    for name, (default, typ, help_text) in SIM_PARAMS.items():
        parser.add_argument(
            f"--{name}", type=typ, default=default, help=f"[試算] {help_text}（既定 {default}）"
        )
    return parser


def simulation_params(args: argparse.Namespace) -> dict:
    return {name.replace("-", "_"): getattr(args, name.replace("-", "_")) for name in SIM_PARAMS}


def main() -> None:
    args = build_parser().parse_args()
    params = simulation_params(args)

    for key in ("main_model", "delegate_model"):
        if params[key] not in PRICE:
            print(f"'{params[key]}' は単価が登録されていません。指定できるモデル:")
            for name in PRICE:
                print(f"  {name}")
            return

    paths = sorted(glob.glob(os.path.join(args.root, "*", "*.jsonl")))
    if not paths:
        print(f"セッション記録が見つかりません: {args.root}")
        print("--root でセッション記録のディレクトリを指定してください。")
        return
    if args.project:
        matched = [p for p in paths if args.project in os.path.basename(os.path.dirname(p))]
        if not matched:
            names = sorted({os.path.basename(os.path.dirname(p)) for p in paths})
            print(f"'{args.project}' に一致するプロジェクトがありません。候補:")
            for n in names:
                print(f"  {n}")
            return
        paths = matched

    sessions = [s for s in (parse_session(p) for p in paths) if s["turns"]]
    if not sessions:
        print("課金対象のターンを含むセッションがありません。")
        return
    sessions.sort(key=lambda s: (s["project"], s["session"]))

    print_summary(sessions)
    if args.detail:
        for s in sessions:
            print_detail(s)
    if args.simulate:
        print_simulation(sessions, args.min_turns, params)
    print_warnings(sessions)


if __name__ == "__main__":
    main()
