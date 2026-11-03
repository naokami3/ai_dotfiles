#!/usr/bin/env python3
"""ファイル分母をスライス（1サブエージェントが読む単位）に分割する（slices.json）。

- ディレクトリ境界を優先し、隣接する小さな単位は上限まで詰める（同じ文脈のコードを同じ読み手へ）
- 上限を超える単一ファイルは行範囲で分割する
- 重複ファイル（dup_of あり）は正規ファイル側だけを読む
- --outline-role の役割（既定: test）は全文ではなくアウトライン（定義行・テスト名）だけを読む
- 前回の slices.json がある場合、内容ハッシュが一致するスライスは抽出結果を引き継ぐ（差分再実行）

使い方:
    python3 plan_slices.py --work <作業ディレクトリ> [--max-lines 5000]
        [--skip-role doc] [--outline-role test] [--tokens-per-line 12] [--overhead 15000]
"""
import argparse
import hashlib
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import load_json, outline_lines, read_lines, save_json, work_paths  # noqa: E402


def new_node():
    return {"files": [], "dirs": {}}


def total(node):
    return sum(c for _, c in node["files"]) + sum(total(d) for d in node["dirs"].values())


def flatten(node):
    out = list(node["files"])
    for k in sorted(node["dirs"]):
        out += flatten(node["dirs"][k])
    return out


def pack(units, maxc):
    out, cur, c = [], [], 0
    for u in units:
        uc = sum(x for _, x in u)
        if cur and c + uc > maxc:
            out.append(cur)
            cur, c = [], 0
        cur += u
        c += uc
    if cur:
        out.append(cur)
    return out


def units_for(node, maxc):
    if total(node) <= maxc:
        return [flatten(node)]
    units, chunk, c = [], [], 0
    for item, cost in node["files"]:
        if cost > maxc and item["mode"] == "full":
            n = item["end"]
            for s in range(1, n + 1, maxc):
                e = min(n, s + maxc - 1)
                units.append([(dict(item, start=s, end=e), e - s + 1)])
            continue
        if chunk and c + cost > maxc:
            units.append(chunk)
            chunk, c = [], 0
        chunk.append((item, cost))
        c += cost
    if chunk:
        units.append(chunk)
    for k in sorted(node["dirs"]):
        units += units_for(node["dirs"][k], maxc)
    return pack(units, maxc)


def slice_hash(items, sha_by_path):
    key = [[i["path"], i["start"], i["end"], i["mode"], sha_by_path[i["path"]]] for i in items]
    return hashlib.sha1(json.dumps(key).encode()).hexdigest()[:16]


def relabel_extract(src, dst, old_id, new_id, new_hash):
    data = load_json(src)
    data["slice_id"] = new_id
    data["slice_hash"] = new_hash
    for f in data.get("features", []):
        if f.get("local_id", "").startswith(old_id + "-"):
            f["local_id"] = new_id + f["local_id"][len(old_id):]
    save_json(dst, data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--max-lines", type=int, default=5000)
    ap.add_argument("--skip-role", default="doc", help="読まない役割（カンマ区切り、空で全て読む）")
    ap.add_argument("--outline-role", default="test", help="アウトラインだけ読む役割（カンマ区切り）")
    ap.add_argument("--tokens-per-line", type=float, default=35.0,
                    help="1行あたりトークン（ツール呼び出しごとの文脈再処理を含む実測値。パイロットで補正）")
    ap.add_argument("--overhead", type=int, default=15000, help="サブエージェント1体あたりの固定トークン")
    a = ap.parse_args()

    wp = work_paths(a.work)
    manifest = load_json(wp["files"])
    repo = manifest["repo"]
    skip = set(filter(None, a.skip_role.split(",")))
    outline_roles = set(filter(None, a.outline_role.split(",")))
    inventory = load_json(wp["inventory"])["entries"] if os.path.exists(wp["inventory"]) else []

    root = new_node()
    sha_by_path = {}
    full_lines = outline_cost = 0
    for f in manifest["files"]:
        if f["role"] in skip or "dup_of" in f:
            continue
        sha_by_path[f["path"]] = f["sha1"]
        mode = "outline" if f["role"] in outline_roles else "full"
        if mode == "outline":
            cost = max(1, len(outline_lines(read_lines(repo, f["path"]))))
            outline_cost += cost
        else:
            cost = f["lines"]
            full_lines += cost
        item = {"path": f["path"], "start": 1, "end": f["lines"], "mode": mode}
        node = root
        for part in f["path"].split("/")[:-1]:
            node = node["dirs"].setdefault(part, new_node())
        node["files"].append((item, cost))

    groups = units_for(root, a.max_lines)
    ent_by_path = {}
    for e in inventory:
        ent_by_path.setdefault(e["path"], []).append(e)

    old = {}
    if os.path.exists(wp["slices"]):
        for s in load_json(wp["slices"])["slices"]:
            old[s["hash"]] = s["id"]

    slices, reused, todo_cost = [], 0, 0
    stash = os.path.join(a.work, ".extract_prev")
    if old and os.path.isdir(wp["extract_dir"]):
        if os.path.isdir(stash):
            shutil.rmtree(stash)
        shutil.move(wp["extract_dir"], stash)
    os.makedirs(wp["extract_dir"], exist_ok=True)
    # スライス ID が振り直されるので、前回の検証結果と作業票は破棄する（引き継いだ抽出結果は再検証する）
    for d in (wp["verify_dir"], os.path.join(a.work, "briefs")):
        if os.path.isdir(d):
            shutil.rmtree(d)

    for n, g in enumerate(groups, 1):
        sid = f"S{n:03d}"
        items = [i for i, _ in g]
        h = slice_hash(items, sha_by_path)
        entry_ids = [e["id"] for i in items for e in ent_by_path.get(i["path"], [])
                     if i["start"] <= e["line"] <= i["end"]]
        slices.append({"id": sid, "hash": h, "cost": sum(c for _, c in g), "items": items,
                       "entry_ids": entry_ids})
        prev = old.get(h)
        src = os.path.join(stash, f"{prev}.json") if prev else None
        if src and os.path.exists(src):
            relabel_extract(src, os.path.join(wp["extract_dir"], f"{sid}.json"), prev, sid, h)
            reused += 1
        else:
            todo_cost += slices[-1]["cost"]
    if os.path.isdir(stash):
        shutil.rmtree(stash)

    save_json(wp["slices"], {"max_lines": a.max_lines, "skip_roles": sorted(skip),
                             "outline_roles": sorted(outline_roles), "slices": slices})

    cost = sum(s["cost"] for s in slices)
    todo = len(slices) - reused
    est = int(cost * a.tokens_per_line + len(slices) * a.overhead)
    est_todo = int(todo_cost * a.tokens_per_line + todo * a.overhead)
    print(f"slices.json を出力: {wp['slices']}")
    print(f"スライス {len(slices)} 件（上限 {a.max_lines} 行、平均 {cost // max(1, len(slices))} 行）")
    print(f"全文読み {full_lines} 行 / アウトライン読み {outline_cost} 行（{','.join(sorted(outline_roles)) or 'なし'}）")
    print(f"入口の割り当て: {sum(len(s['entry_ids']) for s in slices)} / {len(inventory)} 件")
    if old:
        print(f"前回から内容が変わらず抽出結果を引き継いだスライス: {reused} 件（再実行が必要 {todo} 件）")
    print(f"概算トークン（全体）: 約 {est:,}（{a.tokens_per_line}/行 + {a.overhead:,}/体。パイロット実測で補正する）")
    if old:
        print(f"概算トークン（今回の再実行分）: 約 {est_todo:,}")


if __name__ == "__main__":
    main()
