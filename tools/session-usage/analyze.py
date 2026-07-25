#!/usr/bin/env python3
"""Claude Code のセッション記録からトークン使用量とコストを集計する。

~/.claude/projects/*/*.jsonl を読み、モデル別のトークン消費、コンテキストの
肥大の推移、会話内容の構成比を出力する。--simulate を付けると、実装ターンを
Sonnet のサブエージェントに委譲した場合のコストを試算する。

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

# 単価（USD / 1Mトークン）。公表価格の変更に追従していない可能性があるため、
# 金額を根拠に判断する場合は最新の価格表と突き合わせること。
PRICE: dict[str, tuple[float, float]] = {
    "opus": (15.0, 75.0),
    "sonnet": (3.0, 15.0),
    "haiku": (1.0, 5.0),
}

CACHE_READ_RATE = 0.10   # キャッシュ読み込みは入力単価の10%
CACHE_WRITE_RATE = 1.25  # キャッシュ書き込みは入力単価の1.25倍

# 実装作業とみなすツール。--simulate で委譲対象を判定するのに使う。
IMPL_TOOLS = {"Edit", "Write", "NotebookEdit", "Bash", "BashOutput", "KillShell"}

SESSION_ROOT = os.path.expanduser("~/.claude/projects")


def tier(model: str | None) -> str | None:
    """モデル名から価格帯を判定する。未知のモデルは None。"""
    name = (model or "").lower()
    return next((t for t in PRICE if t in name), None)


def cost(model_tier: str, inp: int, cache_read: int, cache_write: int, out: int) -> float:
    price_in, price_out = PRICE[model_tier]
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


def parse_session(path: str) -> dict:
    """1セッションのJSONLを読み、課金対象ターンと内容構成を返す。

    同一 requestId のレコードが複数回現れるため（リトライ・ストリーミングの
    途中経過）、uuid と requestId で重複を除去しないと2倍以上に過大計上される。
    """
    seen_uuid: set = set()
    seen_request: set = set()
    turns: list[dict] = []
    composition: dict[str, int] = defaultdict(int)

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
            uuid, request_id = rec.get("uuid"), rec.get("requestId")
            if uuid in seen_uuid:
                continue
            seen_uuid.add(uuid)
            if request_id:
                if request_id in seen_request:
                    continue
                seen_request.add(request_id)

            tools = (
                {x.get("name") for x in content if isinstance(x, dict) and x.get("type") == "tool_use"}
                if isinstance(content, list)
                else set()
            )
            turns.append(
                {
                    "model": message.get("model"),
                    "input": usage.get("input_tokens", 0),
                    "cache_read": usage.get("cache_read_input_tokens", 0),
                    "cache_write": usage.get("cache_creation_input_tokens", 0),
                    "output": usage.get("output_tokens", 0),
                    "is_impl": bool(tools & IMPL_TOOLS),
                    "is_sub": bool(rec.get("isSidechain")),
                }
            )

    return {
        "project": os.path.basename(os.path.dirname(path)),
        "session": os.path.basename(path)[:8],
        "turns": turns,
        "composition": dict(composition),
    }


def session_cost(turns: list[dict]) -> float:
    total = 0.0
    for t in turns:
        model_tier = tier(t["model"])
        if model_tier:
            total += cost(model_tier, t["input"], t["cache_read"], t["cache_write"], t["output"])
    return total


def simulate_split(turns: list[dict]) -> dict:
    """実装ターンをSonnetに委譲した場合のコストを試算する。

    委譲したターンが生んだコンテキスト増分は、以降メイン側に積まれないものとして
    計算する。サブエージェントの重複読み込みは計上していないため分担側を過小に、
    委譲対象を実装ツール使用ターンのみに限っているため過大に見積もる。
    双方向の誤差があり、精度は±10ポイント程度と考えること。

    両アームとも入力をキャッシュ読み込み単価で近似する。分担後のキャッシュ
    書き込み量は予測できないため、片側だけ1.25倍で課金すると削減率が
    実態より大きく出てしまう。絶対額はサマリより低めに出るが、比較は正しくなる。
    """
    base = sum(
        cost("opus", 0, t["input"] + t["cache_read"] + t["cache_write"], 0, t["output"])
        for t in turns
    )

    removed = 0      # メインコンテキストから外れた累積分
    sub_ctx = 3_000  # 作業指示書＋システムプロンプト相当
    main_cost = sub_cost = 0.0
    prev_ctx = 0
    impl_turns = 0

    for t in turns:
        ctx = t["input"] + t["cache_read"] + t["cache_write"]
        delta = max(0, ctx - prev_ctx)
        prev_ctx = ctx
        if t["is_impl"]:
            impl_turns += 1
            sub_ctx += delta
            sub_cost += cost("sonnet", 0, sub_ctx, 0, t["output"])
            removed += delta
        else:
            main_cost += cost("opus", 0, max(0, ctx - removed), 0, t["output"])

    # 引き継ぎ（指示書の作成＋実装結果の受け取り）
    handoff = cost("opus", 0, 40_000, 0, 2_500)
    # レビュー1パス（Sonnetが差分を読みテストを実行する想定）
    review = sum(cost("sonnet", 0, 20_000 + i * 9_000, 0, 1_200) for i in range(10))

    return {
        "base": base,
        "split": main_cost + sub_cost + handoff + review,
        "main": main_cost,
        "sub": sub_cost,
        "handoff": handoff,
        "review": review,
        "impl_turns": impl_turns,
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


def print_simulation(sessions: list[dict], min_turns: int) -> None:
    print("\n=== 分担した場合の試算（実装ターンをSonnetサブエージェントへ委譲） ===")
    header = f"{'セッション':<26} {'ターン':>6} {'実装':>5} {'現状$':>9} {'分担$':>9} {'削減':>7}   内訳"
    print(header)
    print("-" * 112)
    for s in sessions:
        if len(s["turns"]) < min_turns:
            continue
        r = simulate_split(s["turns"])
        if r["base"] <= 0:
            continue
        name = f"{s['project'][-16:]}/{s['session']}"
        print(
            f"{name:<26} {len(s['turns']):>6} {r['impl_turns']:>5} {r['base']:>9.2f} {r['split']:>9.2f} "
            f"{(1 - r['split'] / r['base']) * 100:>6.1f}%   "
            f"main {r['main']:.2f} / sub {r['sub']:.2f} / 引継 {r['handoff']:.2f} / レビュー {r['review']:.2f}"
        )
    print("\n※ サブエージェントの重複読み込み未計上（分担側を過小評価）、")
    print("   委譲対象を実装ツール使用ターンに限定（過大評価）。精度は±10ポイント程度。")


def main() -> None:
    parser = argparse.ArgumentParser(description="Claude Code のトークン使用量を集計する")
    parser.add_argument("-p", "--project", help="プロジェクト名の部分一致で絞り込む")
    parser.add_argument("-d", "--detail", action="store_true", help="コンテキスト推移と内容構成を出す")
    parser.add_argument("--simulate", action="store_true", help="分担した場合のコストを試算する")
    parser.add_argument("--min-turns", type=int, default=10, help="試算対象の最小ターン数（既定10）")
    parser.add_argument("--root", default=SESSION_ROOT, help="セッション記録のディレクトリ")
    args = parser.parse_args()

    paths = sorted(glob.glob(os.path.join(args.root, "*", "*.jsonl")))
    if args.project:
        paths = [p for p in paths if args.project in p]
    if not paths:
        print(f"セッション記録が見つかりません: {args.root}")
        return

    sessions = [s for s in (parse_session(p) for p in paths) if s["turns"]]
    sessions.sort(key=lambda s: (s["project"], s["session"]))

    print_summary(sessions)
    if args.detail:
        for s in sessions:
            print_detail(s)
    if args.simulate:
        print_simulation(sessions, args.min_turns)


if __name__ == "__main__":
    main()
