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
import re
from collections import defaultdict
from datetime import datetime

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


# --- タスク分類 ---------------------------------------------------------

# ツール名から決まるカテゴリ。Bash だけはコマンドを見て決めるのでここには入れない。
TOOL_CATEGORY = {
    "WebSearch": "調査(Web)",
    "WebFetch": "調査(Web)",
    "Read": "調査(コード)",
    "Grep": "調査(コード)",
    "Glob": "調査(コード)",
    "NotebookRead": "調査(コード)",
    "Edit": "実装",
    "Write": "実装",
    "NotebookEdit": "実装",
    "AskUserQuestion": "ユーザー確認",
    "ExitPlanMode": "ユーザー確認",
}

# 1ターンが複数カテゴリに該当したときの優先順位（小さいほど優先）。
CATEGORY_PRIORITY = [
    "テスト実行",
    "lint実行",
    "バージョン管理",
    "スクリプト実行",
    "実装",
    "調査(コード)",
    "調査(Web)",
    "ユーザー確認",
    "解析不能",
    "その他",
    "相談",
]

TEST_COMMANDS = {
    "pytest", "py.test", "unittest", "rspec", "jest", "vitest", "mocha", "ava",
    "phpunit", "minitest", "tox", "nose2",
}
LINT_COMMANDS = {
    "rubocop", "eslint", "ruff", "black", "isort", "flake8", "prettier", "mypy",
    "pyright", "tsc", "gofmt", "golangci-lint", "clippy", "stylelint", "biome",
}
VCS_COMMANDS = {"git", "gh", "hub"}

# ファイルの中身や場所を見るコマンド。Read/Grep ツールと同じ用途とみなして
# 調査(コード) に寄せる。厳密な区別より、未分類を減らして行き先を見せることを優先する。
INSPECT_COMMANDS = {
    "cat", "head", "tail", "less", "more", "ls", "tree", "find", "grep", "rg", "ag",
    "wc", "diff", "file", "stat", "which", "sed", "awk", "jq", "column", "sort", "uniq",
}

# スクリプト実行。カテゴリ名に言語を含める（スクリプト実行(Python) など）。
SCRIPT_LANGUAGES = {
    "python": "Python", "python3": "Python", "uv": "Python",
    "ruby": "Ruby", "irb": "Ruby",
    "node": "Node", "deno": "Deno", "bun": "Bun",
    "perl": "Perl", "php": "PHP", "lua": "Lua",
    "bash": "Shell", "sh": "Shell", "zsh": "Shell",
    "Rscript": "R", "java": "Java", "swift": "Swift", "kotlin": "Kotlin",
}

# 結果が返るまで人間の応答を待つツール。待ち時間は機械の実行時間ではないので
# ツール待ちに混ぜず、ユーザー確認待ちとして分離する。
HUMAN_WAIT_TOOLS = {"AskUserQuestion", "ExitPlanMode"}

# 先頭から剥がしてよいラッパー。剥がした後のトークンで判定する。
WRAPPERS = {"sudo", "time", "env", "xargs", "nohup", "command", "exec", "export"}
# サブコマンドまで見ないと用途が分からないランナー。
SUBCOMMAND_RUNNERS = {"npm", "npx", "pnpm", "yarn", "bundle", "poetry", "uv", "rye", "go", "cargo", "rake"}

# 限定文法で扱えない構文。含まれていたら分類せず「解析不能」にする。
# 黙って「その他」に入れると、分類できていない事実が見えなくなる。
UNPARSEABLE_PATTERNS = [
    r"\$\(", r"`", r"\(", r"\)", r"\{", r"\}", r"<\(", r">\(",
    r"\\\n", r"\bsh\s+-c\b", r"\bbash\s+-c\b", r"\bzsh\s+-c\b",
    r"^\s*(if|for|while|until|case|function)\b",
]

QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
HEREDOC = re.compile(r"<<-?\s*'?(\w+)'?\n.*?^\1\s*$", re.DOTALL | re.MULTILINE)
ENV_ASSIGN = re.compile(r"^[A-Za-z_]\w*=")
SEGMENT_SPLIT = re.compile(r"&&|\|\||;|\||\n")


def strip_noise(command: str) -> str:
    """ヒアドキュメント本文と引用文字列の中身を落とす。

    引用の中のコマンド名（echo "rubocop を実行" など）を実行と誤認しないため。
    """
    text = HEREDOC.sub("", command)
    return QUOTED.sub('""', text)


def is_unparseable(text: str) -> bool:
    return any(re.search(p, text, re.MULTILINE) for p in UNPARSEABLE_PATTERNS)


def command_head(segment: str) -> list[str]:
    """セグメント先頭の環境変数代入・cd・ラッパーを剥がし、残りのトークンを返す。"""
    tokens = segment.split()
    while tokens:
        if ENV_ASSIGN.match(tokens[0]) or tokens[0] in WRAPPERS:
            tokens = tokens[1:]
            continue
        if tokens[0] == "cd":
            tokens = tokens[2:] if len(tokens) > 1 else []
            continue
        break
    return tokens


def classify_command(tokens: list[str]) -> str | None:
    """実行コマンドのトークン列からカテゴリを返す。該当なしは None。"""
    if not tokens:
        return None
    name = os.path.basename(tokens[0])
    if name in TEST_COMMANDS:
        return "テスト実行"
    if name in LINT_COMMANDS:
        return "lint実行"
    if name in VCS_COMMANDS:
        return "バージョン管理"
    if name in SUBCOMMAND_RUNNERS or name in SCRIPT_LANGUAGES:
        # npm run test / npx jest / bundle exec rspec / python3 -m pytest のように後続を見る。
        # 言語処理系でも、テストやlintを起動している場合はそちらを優先する
        for token in tokens[1:4]:
            sub = os.path.basename(token)
            if sub in TEST_COMMANDS or sub in {"test", "spec"}:
                return "テスト実行"
            if sub in LINT_COMMANDS or sub in {"lint", "fmt", "format"}:
                return "lint実行"
    if name in SCRIPT_LANGUAGES:
        return f"スクリプト実行({SCRIPT_LANGUAGES[name]})"
    if name in INSPECT_COMMANDS:
        return "調査(コード)"
    return None


def classify_bash(command: str) -> str:
    """Bash のコマンド文字列をカテゴリに落とす。

    実行コマンドの位置だけを見る。全文への正規表現だとコメントやファイル名にも
    一致してしまう。限定文法で扱えない構文は「解析不能」として数え、
    分類できていない事実を隠さない。
    """
    text = strip_noise(command)
    if is_unparseable(text):
        return "解析不能"
    found = [
        category
        for segment in SEGMENT_SPLIT.split(text)
        if (category := classify_command(command_head(segment)))
    ]
    if not found:
        return "その他"
    return min(found, key=category_rank)


def category_rank(category: str) -> int:
    """優先順位表での順番。スクリプト実行(言語) は言語を落として引く。"""
    base = "スクリプト実行" if category.startswith("スクリプト実行") else category
    return CATEGORY_PRIORITY.index(base) if base in CATEGORY_PRIORITY else len(CATEGORY_PRIORITY)


def merge_categories(categories: list[str]) -> str:
    """1ターンに複数カテゴリが現れたら優先順位の高いものを1つ選ぶ。"""
    if not categories:
        return "相談"
    return min(categories, key=category_rank)


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
    events: list[dict] = []
    bundles: dict[str, dict] = {}
    turn_durations: list[dict] = []

    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            collect_event(rec, events, bundles, turn_durations)
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
        "events": events,
        "bundles": bundles,
        "turn_durations": turn_durations,
    }


def parse_ts(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def bundle_key(rec: dict) -> str | None:
    """分類とトークン計上の単位。requestId が無いレコードは uuid 単位で独立させる。"""
    return rec.get("requestId") or rec.get("uuid")


def collect_event(rec: dict, events: list, bundles: dict, turn_durations: list) -> None:
    """1レコードをタイムライン用のイベントとして記録する。

    時間計測は物理レコードの順序で行うため、ここでは束ねない。
    束ねるのは分類とトークン計上（bundles）だけで、両者を混ぜない。
    """
    ts = parse_ts(rec.get("timestamp"))
    if ts is None:
        return
    rec_type = rec.get("type")
    if rec_type == "system":
        if rec.get("subtype") == "turn_duration" and isinstance(rec.get("durationMs"), (int, float)):
            turn_durations.append({"ts": ts, "duration_sec": rec["durationMs"] / 1000})
        events.append({"ts": ts, "kind": "system"})
        return

    message = rec.get("message") or {}
    content = message.get("content")
    blocks = content if isinstance(content, list) else []
    key = bundle_key(rec)

    if rec_type == "user":
        result_ids = [b.get("tool_use_id") for b in blocks if isinstance(b, dict) and b.get("type") == "tool_result"]
        events.append(
            {
                "ts": ts,
                "kind": "tool_result" if result_ids else "user_prompt",
                "tool_result_ids": [i for i in result_ids if i],
            }
        )
        return

    if rec_type != "assistant":
        return

    tool_uses = [b for b in blocks if isinstance(b, dict) and b.get("type") == "tool_use"]
    events.append(
        {
            "ts": ts,
            "kind": "assistant",
            "bundle": key,
            "tool_use_ids": [b.get("id") for b in tool_uses if b.get("id")],
            "human_ids": {b.get("id") for b in tool_uses if b.get("name") in HUMAN_WAIT_TOOLS and b.get("id")},
            "is_sub": bool(rec.get("isSidechain")),
        }
    )
    bundle = bundles.setdefault(
        key,
        {"tools": [], "usage": None, "model": None, "is_sub": bool(rec.get("isSidechain")), "records": 0},
    )
    bundle["records"] += 1
    for block in tool_uses:
        bundle["tools"].append((block.get("name"), block.get("input") or {}))
    if bundle["usage"] is None and message.get("usage"):
        bundle["usage"] = message["usage"]
        bundle["model"] = message.get("model")


def session_cost(turns: list[dict]) -> float:
    """記録された使用量から実測コストを求める。未登録モデルは加算しない。"""
    total = 0.0
    for t in turns:
        price = model_price(t["model"])
        if price:
            total += cost(price, t["input"], t["cache_read"], t["cache_write"], t["output"])
    return total


# --- タスク別の時間とトークン -------------------------------------------

def bundle_category(bundle: dict) -> tuple[str, bool]:
    """束のカテゴリと、複数カテゴリが混在したかを返す。"""
    categories = [
        classify_bash((inp or {}).get("command", "")) if name == "Bash" else TOOL_CATEGORY.get(name, "その他")
        for name, inp in bundle["tools"]
    ]
    return merge_categories(categories), len(set(categories)) > 1


def user_turn_windows(events: list[dict]) -> list[tuple[int, int]]:
    """user_prompt を境界に、各ターンの [開始index, 終端index] を返す。

    終端はそのターン最後の実レコード。そこから次のプロンプトまでの区間は
    ユーザー待機であり、タスク時間には入れない。tool_result が欠落した
    ターンでも離席時間がツール待ちへ流れ込まないようにするための境界。
    """
    starts = [i for i, e in enumerate(events) if e["kind"] == "user_prompt"]
    windows = []
    for n, start in enumerate(starts):
        stop = starts[n + 1] if n + 1 < len(starts) else len(events)
        last = max(
            (j for j in range(start + 1, stop) if events[j]["kind"] in ("assistant", "tool_result")),
            default=None,
        )
        if last is not None:
            windows.append((start, last))
    return windows


def label_intervals(events: list[dict], window: tuple[int, int]) -> tuple[list[tuple], dict]:
    """1ターンの区間を 生成 / ツール待ち / 未説明 に重複なく分ける。

    未完了の tool_use_id を集合で持ち、区間の開始時点でそれが空でなければ
    ツール待ちとする。並列ツールの結果が複数レコードに分かれて返っても、
    最後の結果が届くまでの各区間がツール待ちになり、過小計上しない。
    """
    start, end = window
    pending: dict[str, str | None] = {}
    human_pending: set[str] = set()
    labeled: list[tuple[str, float, str | None]] = []
    stats = {"negative_gaps": 0, "multi_owner": 0, "unfinished": 0}

    for i in range(start, end):
        cur, nxt = events[i], events[i + 1]
        if cur["kind"] == "assistant":
            human_pending |= cur.get("human_ids", set())
            for tool_id in cur.get("tool_use_ids", []):
                pending[tool_id] = cur.get("bundle")
        elif cur["kind"] == "tool_result":
            for tool_id in cur.get("tool_result_ids", []):
                pending.pop(tool_id, None)
                human_pending.discard(tool_id)

        gap = (nxt["ts"] - cur["ts"]).total_seconds()
        if gap < 0:
            stats["negative_gaps"] += 1
            gap = 0.0

        if pending and set(pending) <= human_pending:
            # 人間の応答を待っているだけの区間。機械の実行時間ではない
            labeled.append(("ユーザー確認待ち", gap, None))
        elif pending:
            if len(set(pending.values())) > 1:
                stats["multi_owner"] += 1
            labeled.append(("ツール待ち", gap, list(pending.values())[-1]))
        elif nxt["kind"] == "assistant":
            labeled.append(("生成", gap, nxt.get("bundle")))
        else:
            labeled.append(("未説明", gap, None))

    # 最後のレコードは区間の始点にならないが、そこで発行された tool_use も
    # 未完了として数える必要がある
    last = events[end]
    if last["kind"] == "assistant":
        for tool_id in last.get("tool_use_ids", []):
            pending[tool_id] = last.get("bundle")
    elif last["kind"] == "tool_result":
        for tool_id in last.get("tool_result_ids", []):
            pending.pop(tool_id, None)

    stats["unfinished"] = len(pending)
    return labeled, stats


def token_deltas(bundles: dict) -> tuple[dict[str, int | None], int]:
    """束ごとの入力増分（推定）を返す。破綻する条件では None にする。

    コンテキスト圧縮・モデル切替・初回は「新たに与えた量」と一致しないため
    数値を出さず、件数を警告に回す。
    """
    deltas: dict[str, int | None] = {}
    unknown = 0
    prev_ctx: dict[bool, int] = {}
    prev_model: dict[bool, str | None] = {}
    for key, bundle in bundles.items():
        usage = bundle["usage"]
        if not usage:
            continue
        series = bundle["is_sub"]
        ctx = (
            usage.get("input_tokens", 0)
            + usage.get("cache_read_input_tokens", 0)
            + usage.get("cache_creation_input_tokens", 0)
        )
        last_ctx, last_model = prev_ctx.get(series), prev_model.get(series)
        if last_ctx is None or bundle["model"] != last_model or ctx < last_ctx:
            deltas[key] = None
            unknown += 1
        else:
            deltas[key] = ctx - last_ctx
        prev_ctx[series] = ctx
        prev_model[series] = bundle["model"]
    return deltas, unknown


def verify_turn_durations(
    events: list[dict],
    windows: list[tuple[int, int]],
    durations: list[dict],
    human_windows: set[int] | None = None,
) -> dict:
    """turn_duration をターン単位で突合する。

    比較終端は turn_duration レコード自身ではなく、直前の実レコード
    （＝そのターン最後の assistant の完了時刻）。system の記録遅延を含めない。
    """
    skip = human_windows or set()
    result = {"matched": 0, "unmatched": 0, "skipped": 0, "max_abs": 0.0, "max_rel": 0.0, "errors": []}
    for record in durations:
        window = None
        chosen = None
        for index, (start, end) in enumerate(windows):
            if events[end]["ts"] <= record["ts"] and (window is None or events[end]["ts"] > events[window[1]]["ts"]):
                window, chosen = (start, end), index
        if window is None:
            result["unmatched"] += 1
            continue
        if chosen in skip:
            # ユーザーの応答待ちを含むターンは、durationMs と観測区間の意味が揃わない
            result["skipped"] += 1
            continue
        observed = (events[window[1]]["ts"] - events[window[0]]["ts"]).total_seconds()
        diff = abs(observed - record["duration_sec"])
        result["matched"] += 1
        result["errors"].append(diff)
        result["max_abs"] = max(result["max_abs"], diff)
        if record["duration_sec"] > 0:
            result["max_rel"] = max(result["max_rel"], diff / record["duration_sec"])
    return result


def analyze_tasks(session: dict) -> dict:
    """1セッションをカテゴリ別の時間・トークン・コストに落とす。"""
    events = [e for e in session["events"] if e["kind"] != "system"]
    bundles = session["bundles"]
    windows = user_turn_windows(events)
    deltas, unknown_deltas = token_deltas(bundles)

    categories: dict[tuple[bool, str], dict] = defaultdict(
        lambda: {"turns": 0, "gen": 0.0, "wait": 0.0, "out": 0, "delta": 0, "proc": 0, "cost": 0.0}
    )
    unexplained = 0.0
    human_windows: set[int] = set()
    broken_windows: set[int] = set()
    mixed_turns = 0
    stats = {"negative_gaps": 0, "multi_owner": 0, "unfinished": 0}
    orphan_results = 0
    unclassified_heads: dict[str, int] = defaultdict(int)

    cat_of: dict[str, tuple[bool, str]] = {}
    for key, bundle in bundles.items():
        category, mixed = bundle_category(bundle)
        cat_of[key] = (bundle["is_sub"], category)
        if mixed:
            mixed_turns += 1
        if category in ("その他", "解析不能"):
            for name, inp in bundle["tools"]:
                if name == "Bash":
                    heads = [
                        command_head(segment)
                        for segment in SEGMENT_SPLIT.split(strip_noise((inp or {}).get("command", "")))
                    ]
                    unknown = [h for h in heads if h and classify_command(h) is None]
                    if unknown:
                        unclassified_heads[os.path.basename(unknown[0][0])] += 1
                    elif not any(heads):
                        unclassified_heads["(コマンドなし)"] += 1

    for key, bundle in bundles.items():
        usage = bundle["usage"]
        if not usage:
            continue
        slot = categories[cat_of[key]]
        slot["turns"] += 1
        slot["out"] += usage.get("output_tokens", 0)
        proc = (
            usage.get("input_tokens", 0)
            + usage.get("cache_read_input_tokens", 0)
            + usage.get("cache_creation_input_tokens", 0)
        )
        slot["proc"] += proc
        if deltas.get(key) is not None:
            slot["delta"] += deltas[key]
        price = model_price(bundle["model"])
        if price:
            slot["cost"] += cost(
                price,
                usage.get("input_tokens", 0),
                usage.get("cache_read_input_tokens", 0),
                usage.get("cache_creation_input_tokens", 0),
                usage.get("output_tokens", 0),
            )

    for index, window in enumerate(windows):
        labeled, turn_stats = label_intervals(events, window)
        for field in stats:
            stats[field] += turn_stats[field]
        if turn_stats["negative_gaps"]:
            # 逆転があると区間の合計が壁時計時間を超えるので、検算の根拠にしない
            broken_windows.add(index)
        for label, seconds, owner in labeled:
            if label == "ユーザー確認待ち":
                # 人間の応答を待っているだけの区間。トークンを消費しないので計上しない
                human_windows.add(index)
                continue
            if label == "未説明" or owner is None or owner not in cat_of:
                unexplained += seconds
                continue
            categories[cat_of[owner]]["gen" if label == "生成" else "wait"] += seconds

    known_ids = {i for e in events for i in e.get("tool_use_ids", [])}
    orphan_results = sum(
        1 for e in events for i in e.get("tool_result_ids", []) if i not in known_ids
    )

    return {
        "project": session["project"],
        "session": session["session"],
        "categories": dict(categories),
        "unexplained": unexplained,
        "mixed_turns": mixed_turns,
        "unknown_deltas": unknown_deltas,
        "orphan_results": orphan_results,
        "unclassified_heads": dict(unclassified_heads),
        "verify": verify_turn_durations(
            events, windows, session["turn_durations"], human_windows | broken_windows
        ),
        **stats,
    }


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


def fmt_duration(seconds: float) -> str:
    total = int(round(seconds))
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m{total % 60:02d}s"
    return f"{total // 3600}h{total % 3600 // 60:02d}m"


def print_tasks(sessions: list[dict]) -> None:
    """カテゴリ別の時間・トークン・コストを出す。"""
    reports = [analyze_tasks(s) for s in sessions]
    totals: dict[tuple[bool, str], dict] = defaultdict(
        lambda: {"turns": 0, "gen": 0.0, "wait": 0.0, "out": 0, "delta": 0, "proc": 0, "cost": 0.0}
    )
    for report in reports:
        for key, slot in report["categories"].items():
            for field, value in slot.items():
                totals[key][field] += value

    print("\n=== タスク別の時間とトークン ===")
    header = (
        f"{'系列':<6} {'カテゴリ':<12} {'ターン':>6} {'生成':>8} {'ツール待ち':>10} "
        f"{'出力tok':>10} {'入力増分':>10} {'処理入力':>12} {'$':>8}"
    )
    print(header)
    print("-" * len(header))
    for (is_sub, category), slot in sorted(
        totals.items(), key=lambda x: (x[0][0], category_rank(x[0][1]), x[0][1])
    ):
        print(
            f"{'サブ' if is_sub else 'メイン':<6} {category:<12} {slot['turns']:>6} "
            f"{fmt_duration(slot['gen']):>8} {fmt_duration(slot['wait']):>10} "
            f"{slot['out']:>10,} {slot['delta']:>10,} {slot['proc']:>12,} {slot['cost']:>8.2f}"
        )

    labeled = sum(slot["gen"] + slot["wait"] for slot in totals.values())
    unexplained = sum(r["unexplained"] for r in reports)
    print(f"\n  未説明時間: {fmt_duration(unexplained)}")
    print(f"  作業時間の合計: {fmt_duration(labeled + unexplained)}")
    print("  ※ ユーザーの応答待ちは計測していない（待っている間はトークンを消費しないため）。")
    print("  ※ 時間は物理レコードの区間を重複なく分割した値。timestamp の逆転が無ければ")
    print("     カテゴリ別の合計は総時間に一致する（逆転があるターンは警告に出す）。")
    print("  ※ 入力増分は推定値。圧縮・モデル切替・初回のターンは加算していない。")
    print("  ※ 処理入力は過去のコンテキストを含む課金上の処理量で、タスク固有量ではない。")

    print_task_warnings(reports)


def print_task_warnings(reports: list[dict]) -> None:
    def total(field: str) -> int:
        return sum(r[field] for r in reports)

    heads: dict[str, int] = defaultdict(int)
    for report in reports:
        for head, n in report["unclassified_heads"].items():
            heads[head] += n

    if heads:
        classified = sum(
            slot["turns"]
            for r in reports
            for (_, category), slot in r["categories"].items()
            if category not in ("その他", "解析不能")
        )
        unclassified = sum(
            slot["turns"]
            for r in reports
            for (_, category), slot in r["categories"].items()
            if category in ("その他", "解析不能")
        )
        rate = classified / max(1, classified + unclassified) * 100
        print(f"\n警告: 分類できたターンは {rate:.1f}%（{classified} / {classified + unclassified}）")
        print("  未分類だった Bash コマンドの先頭:")
        for head, n in sorted(heads.items(), key=lambda x: -x[1])[:10]:
            print(f"    {n:>4}  {head}")

    if total("mixed_turns"):
        print(f"\n警告: 複数カテゴリが混在したターンが {total('mixed_turns')} 件（優先順位で1つに寄せた）")
    if total("unknown_deltas"):
        print(f"警告: 入力増分を推定できないターンが {total('unknown_deltas')} 件（圧縮・モデル切替・初回）")
    if total("unfinished"):
        print(f"警告: 対応する tool_result が無い tool_use が {total('unfinished')} 件（時間に計上していない）")
    if total("orphan_results"):
        print(f"警告: 対応する tool_use が無い tool_result が {total('orphan_results')} 件")
    if total("negative_gaps"):
        print(f"警告: timestamp が逆転した区間が {total('negative_gaps')} 件（0秒に丸めた）")
    if total("multi_owner"):
        print(f"警告: 複数の束が同時に未完了ツールを持つ区間が {total('multi_owner')} 件（最新の束へ寄せた）")

    verify = {"matched": 0, "unmatched": 0, "skipped": 0, "max_abs": 0.0, "max_rel": 0.0}
    errors: list[float] = []
    for report in reports:
        verify["matched"] += report["verify"]["matched"]
        verify["unmatched"] += report["verify"]["unmatched"]
        verify["skipped"] += report["verify"].get("skipped", 0)
        errors.extend(report["verify"].get("errors", []))
        verify["max_abs"] = max(verify["max_abs"], report["verify"]["max_abs"])
        verify["max_rel"] = max(verify["max_rel"], report["verify"]["max_rel"])
    if verify["matched"] or verify["unmatched"]:
        print(
            f"\n検算: turn_duration と突合できたターン {verify['matched']} 件 / "
            f"対応不能 {verify['unmatched']} 件 / 除外 {verify['skipped']} 件（ユーザー確認待ちを含む）"
        )
        if errors:
            errors.sort()
            median = errors[len(errors) // 2]
            p90 = errors[min(len(errors) - 1, int(len(errors) * 0.9))]
            print(f"  絶対誤差 中央値 {median:.1f}s / 90パーセンタイル {p90:.1f}s / 最大 {verify['max_abs']:.1f}s")
        print(f"  最大相対誤差 {verify['max_rel'] * 100:.1f}%（外れ値の有無は上の分布で判断する）")


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
    parser.add_argument("--tasks", action="store_true", help="タスク別の時間とトークンを出す")
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
    if args.tasks:
        print_tasks(sessions)
    if args.simulate:
        print_simulation(sessions, args.min_turns, params)
    print_warnings(sessions)


if __name__ == "__main__":
    main()
