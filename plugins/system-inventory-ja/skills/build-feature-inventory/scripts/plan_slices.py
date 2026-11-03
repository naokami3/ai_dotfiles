#!/usr/bin/env python3
"""ファイル分母をスライス（1サブエージェントが読む単位）に分割する（slices.json）。

- ディレクトリ境界を優先し、隣接する小さな単位は上限まで詰める（同じ文脈のコードを同じ読み手へ）
- 上限を超える単一ファイルは行範囲で分割する
- 重複ファイル（dup_of あり）は正規ファイル側だけを読む（入口は正規ファイルのスライスに割り当てる）
- --outline-role の役割（既定: test）は全文ではなくアウトライン（定義行・テスト名）だけを読む
- スライス ID は内容ハッシュ由来（S + 6桁）。中身が同じなら ID も同じなので、再分割しても
  抽出結果・検証結果はそのまま有効。中身が変わったスライスは別 ID になり、古い参照は大きく失敗する
- 読了確認の窓: 全文読みの各ファイル（1000 行ごと）に、引用を求める小区間を決定的に選ぶ

使い方:
    python3 plan_slices.py --work <作業ディレクトリ> [--max-lines 5000]
        [--skip-role doc] [--outline-role test] [--tokens-per-line 35] [--overhead 15000] [--dry-run]
--dry-run は見積もりだけを出し、何も書き換えない（パイロット後の見積もり補正に使う）。
"""
import argparse
import hashlib
import json
import os
import random
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import load_json, outline_lines, read_lines, save_json, work_paths  # noqa: E402

CHECK_BLOCK = 1000   # この行数ごとに読了確認の窓を1つ置く
CHECK_WINDOW = 30    # 窓の行数


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
    return hashlib.sha1(json.dumps(key).encode()).hexdigest()


def read_checks(items, h, lines_by_path):
    """全文読みの各項目に、引用を求める窓を決定的に選ぶ（空行だけの窓は避ける）"""
    checks = []
    for it in items:
        if it["mode"] != "full":
            continue
        rnd = random.Random(f"{h}:{it['path']}:{it['start']}")
        ls = lines_by_path[it["path"]]
        for bs in range(it["start"], it["end"] + 1, CHECK_BLOCK):
            be = min(it["end"], bs + CHECK_BLOCK - 1)
            if be - bs + 1 <= CHECK_WINDOW:
                ws, we = bs, be
            else:
                for _ in range(10):
                    ws = rnd.randint(bs, be - CHECK_WINDOW + 1)
                    we = ws + CHECK_WINDOW - 1
                    if sum(1 for l in ls[ws - 1:we] if len(l.strip()) >= 10) >= 3:
                        break
            if any(len(l.strip()) >= 10 for l in ls[ws - 1:we]):
                checks.append({"path": it["path"], "start": ws, "end": we})
    return checks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--max-lines", type=int, default=5000)
    ap.add_argument("--skip-role", default="doc", help="読まない役割（カンマ区切り、空で全て読む）")
    ap.add_argument("--outline-role", default="test", help="アウトラインだけ読む役割（カンマ区切り）")
    ap.add_argument("--tokens-per-line", type=float, default=35.0,
                    help="1行あたりトークン（ツール呼び出しごとの文脈再処理を含む実測値。パイロットで補正）")
    ap.add_argument("--overhead", type=int, default=15000, help="サブエージェント1体あたりの固定トークン")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    wp = work_paths(a.work)
    manifest = load_json(wp["files"])
    repo = manifest["repo"]
    skip = set(filter(None, a.skip_role.split(",")))
    outline_roles = set(filter(None, a.outline_role.split(",")))
    inventory = load_json(wp["inventory"])["entries"] if os.path.exists(wp["inventory"]) else []

    root = new_node()
    sha_by_path, lines_by_path = {}, {}
    full_lines = outline_cost = 0
    for f in manifest["files"]:
        if f["role"] in skip or "dup_of" in f:
            continue
        sha_by_path[f["path"]] = f["sha1"]
        mode = "outline" if f["role"] in outline_roles else "full"
        ls = read_lines(repo, f["path"])
        if mode == "outline":
            cost = max(1, len(outline_lines(ls)))
            outline_cost += cost
        else:
            lines_by_path[f["path"]] = ls
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
        # 重複ファイルの入口は、内容が同じ正規ファイルの同じ行として割り当てる
        ent_by_path.setdefault(e.get("dup_of") or e["path"], []).append(e)

    slices, used = [], set()
    for g in groups:
        items = [i for i, _ in g]
        h = slice_hash(items, sha_by_path)
        n = 6
        while "S" + h[:n] in used:
            n += 2
        sid = "S" + h[:n]
        used.add(sid)
        entry_ids = [e["id"] for i in items for e in ent_by_path.get(i["path"], [])
                     if i["start"] <= e["line"] <= i["end"]]
        slices.append({"id": sid, "hash": h, "cost": sum(c for _, c in g), "items": items,
                       "entry_ids": entry_ids, "read_checks": read_checks(items, h, lines_by_path)})

    ids = {s["id"] for s in slices}
    done = {s["id"] for s in slices if os.path.exists(os.path.join(wp["extract_dir"], f"{s['id']}.json"))}
    todo_cost = sum(s["cost"] for s in slices if s["id"] not in done)
    todo = len(slices) - len(done)
    est = int(sum(s["cost"] for s in slices) * a.tokens_per_line + len(slices) * a.overhead)
    est_todo = int(todo_cost * a.tokens_per_line + todo * a.overhead)
    unassigned = len(inventory) - sum(len(s["entry_ids"]) for s in slices)

    if not a.dry_run:
        # 現在のスライスに無い ID の抽出結果は _stale へ退避（消さない）。検証結果と作業票は破棄
        stale_dir = os.path.join(wp["extract_dir"], "_stale")
        os.makedirs(wp["extract_dir"], exist_ok=True)
        moved = 0
        for fn in os.listdir(wp["extract_dir"]):
            if fn.endswith(".json") and fn[:-5] not in ids:
                os.makedirs(stale_dir, exist_ok=True)
                shutil.move(os.path.join(wp["extract_dir"], fn), os.path.join(stale_dir, fn))
                moved += 1
        if os.path.isdir(wp["verify_dir"]):
            for fn in os.listdir(wp["verify_dir"]):
                if fn.endswith(".json") and fn[:-5] not in ids:
                    os.remove(os.path.join(wp["verify_dir"], fn))
        briefs = os.path.join(a.work, "briefs")
        if os.path.isdir(briefs):
            shutil.rmtree(briefs)
        save_json(wp["slices"], {"max_lines": a.max_lines, "skip_roles": sorted(skip),
                                 "outline_roles": sorted(outline_roles), "slices": slices})
        print(f"slices.json を出力: {wp['slices']}")
        if moved:
            print(f"現在のスライスに対応しない抽出結果 {moved} 件を extract/_stale/ へ退避")
    else:
        print("（--dry-run: 何も書き換えていない）")

    print(f"スライス {len(slices)} 件（上限 {a.max_lines} 行、平均 {sum(s['cost'] for s in slices) // max(1, len(slices))} 行）")
    print(f"全文読み {full_lines} 行 / アウトライン読み {outline_cost} 行（{','.join(sorted(outline_roles)) or 'なし'}）")
    print(f"入口の割り当て: {len(inventory) - unassigned} / {len(inventory)} 件"
          + (f"（未割り当て {unassigned} 件: 読まない役割のファイルにある入口）" if unassigned else ""))
    print(f"抽出済み {len(done)} / 未抽出 {todo}")
    print(f"概算トークン（全体）: 約 {est:,}（{a.tokens_per_line}/行 + {a.overhead:,}/体）")
    print(f"概算トークン（未抽出分）: 約 {est_todo:,}")


if __name__ == "__main__":
    main()
