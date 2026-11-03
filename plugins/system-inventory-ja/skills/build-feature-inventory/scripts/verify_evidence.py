#!/usr/bin/env python3
"""抽出結果（extract/<slice>.json）をスライス単位で機械検証する。

検証内容:
1. スキーマ（必須項目・確信度の値・local_id の形式）
2. 根拠の実在: evidence / missing_entries の path:line に quote が実際に書かれているか
   （空白差は無視。±2 行のずれは警告付きで許容、それ以上は不合格）
3. 入口の対応付け: スライスに割り当てた入口が全件 features か unmapped_entries に載っているか
4. 読了範囲: read がスライスの全項目（全文読みの行範囲）を覆っているか
5. 鮮度: slice_hash が現在のスライスと一致するか（コード変更後の古い結果を弾く）

結果は verify/<slice>.json に保存し、標準出力には要約だけを出す。1件でも不合格なら終了コード 1。

使い方:
    python3 verify_evidence.py --work <作業ディレクトリ> [--slice S001 ...]
    python3 verify_evidence.py --work <作業ディレクトリ> --review <review/xxx.json>  # 独立検証の根拠を検証
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import load_json, norm_ws, read_lines, save_json, work_paths  # noqa: E402

CONF = {"confirmed", "inferred", "unknown"}
KINDS = {"http_endpoint", "ui_route", "cli_command", "scheduled_job", "background_job",
         "event_consumer", "webhook", "data_entity", "graphql_operation", "rpc_method", "other"}
MIN_QUOTE = 6


class Ctx:
    def __init__(self, work):
        self.wp = work_paths(work)
        m = load_json(self.wp["files"])
        self.repo = m["repo"]
        self.known = {f["path"] for f in m["files"]}
        self.entries = {e["id"] for e in load_json(self.wp["inventory"])["entries"]} \
            if os.path.exists(self.wp["inventory"]) else set()
        self._cache = {}

    def lines(self, path):
        if path not in self._cache:
            self._cache[path] = [norm_ws(l) for l in read_lines(self.repo, path)]
        return self._cache[path]


def check_quote(ctx, ev, where, errors, warnings):
    path, line, quote = ev.get("path"), ev.get("line"), ev.get("quote")
    if not isinstance(path, str) or not isinstance(line, int) or not isinstance(quote, str):
        errors.append(f"{where}: path(str) / line(int) / quote(str) が必要")
        return
    q = norm_ws(quote)
    if len(q.replace(" ", "")) < MIN_QUOTE:
        errors.append(f"{where}: quote が短すぎる（{MIN_QUOTE}文字以上の特徴的な断片を引用する）: {quote!r}")
        return
    if path not in ctx.known:
        if not os.path.isfile(os.path.join(ctx.repo, path)):
            errors.append(f"{where}: ファイルが存在しない: {path}")
            return
        warnings.append(f"{where}: 分母外のファイルを根拠にしている: {path}")
    ls = ctx.lines(path)
    if not 1 <= line <= len(ls):
        errors.append(f"{where}: 行番号が範囲外: {path}:{line}（{len(ls)}行）")
        return
    if q in ls[line - 1]:
        return
    for d in (1, -1, 2, -2):
        n = line + d
        if 1 <= n <= len(ls) and q in ls[n - 1]:
            warnings.append(f"{where}: 行がずれている {path}:{line} → 実際は {n}")
            ev["line"] = n
            return
    # 複数行にまたがる引用（連続3行を空白で連結）も許す
    win = " ".join(ls[max(0, line - 2):line + 2])
    if q in win:
        return
    errors.append(f"{where}: 引用が {path}:{line} 付近に見つからない（推測で書いていないか）: {quote[:80]!r}")


def covered(ranges, start, end):
    pos = start
    for s, e in sorted(ranges):
        if s > pos:
            break
        pos = max(pos, e + 1)
        if pos > end:
            return True
    return pos > end


def verify_slice(ctx, s):
    errors, warnings = [], []
    path = os.path.join(ctx.wp["extract_dir"], f"{s['id']}.json")
    if not os.path.exists(path):
        return {"slice": s["id"], "ok": False, "missing": True, "errors": ["抽出結果が無い"], "warnings": []}
    try:
        d = load_json(path)
    except json.JSONDecodeError as e:
        return {"slice": s["id"], "ok": False, "errors": [f"JSON として読めない: {e}"], "warnings": []}

    if d.get("slice_id") != s["id"]:
        errors.append(f"slice_id が {s['id']} ではない: {d.get('slice_id')}")
    if d.get("slice_hash") != s["hash"]:
        errors.append(f"slice_hash が現在のスライスと一致しない（古い結果）: {d.get('slice_hash')} != {s['hash']}")

    mapped = set()
    ids = set()
    for k, f in enumerate(d.get("features") or []):
        lid = f.get("local_id", "")
        w = f"features[{k}]({lid or '?'})"
        if not lid.startswith(s["id"] + "-F"):
            errors.append(f"{w}: local_id は '{s['id']}-F<番号>' 形式にする")
        if lid in ids:
            errors.append(f"{w}: local_id が重複")
        ids.add(lid)
        for key in ("name", "summary"):
            if not (isinstance(f.get(key), str) and f[key].strip()):
                errors.append(f"{w}: {key} が空")
        if f.get("confidence") not in CONF:
            errors.append(f"{w}: confidence は {sorted(CONF)} のいずれか")
        for key in ("entry_ids", "data", "external", "actors", "open_questions"):
            if key in f and not isinstance(f[key], list):
                errors.append(f"{w}: {key} は配列にする")
        evs = f.get("evidence") or []
        if not evs:
            errors.append(f"{w}: evidence が無い（根拠の無い機能は書かない）")
        for j, ev in enumerate(evs):
            check_quote(ctx, ev, f"{w}.evidence[{j}]", errors, warnings)
        for eid in f.get("entry_ids") or []:
            if eid not in ctx.entries:
                errors.append(f"{w}: entry_ids に存在しない入口ID: {eid}")
            mapped.add(eid)

    for k, u in enumerate(d.get("unmapped_entries") or []):
        if u.get("entry_id") not in ctx.entries:
            errors.append(f"unmapped_entries[{k}]: 存在しない入口ID: {u.get('entry_id')}")
        if not (u.get("reason") or "").strip():
            errors.append(f"unmapped_entries[{k}]: reason が空")
        mapped.add(u.get("entry_id"))
    for k, m in enumerate(d.get("missing_entries") or []):
        check_quote(ctx, m, f"missing_entries[{k}]", errors, warnings)
        if m.get("kind") not in KINDS:
            errors.append(f"missing_entries[{k}]: kind は {sorted(KINDS)} のいずれか（該当が無ければ other）: {m.get('kind')}")
        if not m.get("label"):
            errors.append(f"missing_entries[{k}]: label が必要")

    for eid in s["entry_ids"]:
        if eid not in mapped:
            errors.append(f"入口が未対応: {eid}（features.entry_ids か unmapped_entries に載せる）")

    reads = {}
    for r in d.get("read") or []:
        try:
            reads.setdefault(r["path"], []).append((int(r["start"]), int(r["end"])))
        except (KeyError, TypeError, ValueError):
            errors.append(f"read の要素が不正: {r}")
    for it in s["items"]:
        if it["mode"] == "outline":
            continue
        if not covered(reads.get(it["path"], []), it["start"], it["end"]):
            errors.append(f"読了範囲が不足: {it['path']} L{it['start']}-{it['end']}")

    # 行ずれの自動補正を反映して保存し直す
    if any("行がずれている" in w for w in warnings):
        save_json(path, d)
    return {"slice": s["id"], "ok": not errors, "errors": errors, "warnings": warnings,
            "features": len(d.get("features") or [])}


def verify_review(ctx, path):
    errors, warnings = [], []
    d = load_json(path)
    for k, r in enumerate(d.get("results") or []):
        w = f"results[{k}]({r.get('feature_id')})"
        if r.get("verdict") not in {"correct", "partially_correct", "incorrect", "unverifiable"}:
            errors.append(f"{w}: verdict が不正")
        for j, ev in enumerate(r.get("evidence") or []):
            check_quote(ctx, ev, f"{w}.evidence[{j}]", errors, warnings)
        if r.get("verdict") in {"partially_correct", "incorrect"} and not r.get("evidence"):
            errors.append(f"{w}: 誤りの指摘には evidence が必要")
    return errors, warnings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--slice", nargs="*")
    ap.add_argument("--review")
    a = ap.parse_args()
    ctx = Ctx(a.work)

    if a.review:
        errors, warnings = verify_review(ctx, a.review)
        for w in warnings:
            print(f"警告: {w}")
        for e in errors:
            print(f"不合格: {e}")
        print("合格" if not errors else f"不合格 {len(errors)} 件")
        sys.exit(1 if errors else 0)

    slices = load_json(ctx.wp["slices"])["slices"]
    if a.slice:
        slices = [s for s in slices if s["id"] in set(a.slice)]
    passed, failed, missing = [], [], []
    for s in slices:
        res = verify_slice(ctx, s)
        save_json(os.path.join(ctx.wp["verify_dir"], f"{s['id']}.json"), res)
        if res.get("missing"):
            missing.append(s["id"])
        elif res["ok"]:
            passed.append(s["id"])
        else:
            failed.append(res)
    print(f"合格 {len(passed)} / 不合格 {len(failed)} / 未抽出 {len(missing)}（対象 {len(slices)} スライス）")
    for r in failed:
        print(f"- {r['slice']}: エラー {len(r['errors'])} 件（先頭: {r['errors'][0]}）")
    if missing:
        print("未抽出: " + " ".join(missing))
    sys.exit(0 if not failed and not missing else 1)


if __name__ == "__main__":
    main()
