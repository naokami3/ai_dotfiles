#!/usr/bin/env python3
"""スライス横断の集約を支援する。サブコマンド:

digest  抽出済みの局所機能を 1 機能 1 行に圧縮したダイジェストを書き出す。
        集約担当はコードも抽出 JSON も読まず、これだけを見てグループ分けする。
            python3 features.py digest --work W [--prefix app/billing] [--out W/digest.txt]

merge   集約担当が書いた grouping.json（名前・要約・グループ分け・sources だけ）から features.json を作る。
        入口・データ・外部連携・根拠・確信度・要確認事項は sources の抽出結果から機械的に引き継ぐ
        （集約段階で新しい事実を書き足せないようにするため）。全局所機能の配置漏れは不合格。
            python3 features.py merge --work W --grouping W/grouping.json

sample  独立検証に回す機能をリスク順に抽出する（推定・不明、入口なし、多数の局所機能を束ねたもの優先）。
            python3 features.py sample --work W [--n 15] [--seed 0]
"""
import argparse
import collections
import os
import random
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import die, load_json, save_json, work_paths  # noqa: E402

CONF_RANK = {"unknown": 0, "inferred": 1, "confirmed": 2}


def load_extracts(wp):
    slices = load_json(wp["slices"])["slices"]
    out = []
    for s in slices:
        p = os.path.join(wp["extract_dir"], f"{s['id']}.json")
        if os.path.exists(p):
            out.append((s, load_json(p)))
    return slices, out


def entries_by_id(wp):
    if not os.path.exists(wp["inventory"]):
        return {}
    return {e["id"]: e for e in load_json(wp["inventory"])["entries"]}


def cmd_digest(a, wp):
    slices, extracts = load_extracts(wp)
    ents = entries_by_id(wp)
    lines, n = [], 0
    for s, d in extracts:
        if a.prefix and not any(i["path"].startswith(a.prefix) for i in s["items"]):
            continue
        dirs = sorted({i["path"].rsplit("/", 1)[0] if "/" in i["path"] else "." for i in s["items"]})
        lines.append(f"## {s['id']}  {', '.join(dirs[:4])}{' ...' if len(dirs) > 4 else ''}")
        for f in d.get("features", []):
            n += 1
            labels = [f'{ents[e]["label"]} @{ents[e]["path"].rsplit("/", 1)[-1]}'
                      for e in f.get("entry_ids", []) if e in ents]
            ent = ", ".join(labels[:5]) + (f" 他{len(labels) - 5}" if len(labels) > 5 else "")
            lines.append(" | ".join([
                f["local_id"], f["name"], (f.get("summary") or "")[:70],
                f"入口: {ent or 'なし'}", f"data: {', '.join(f.get('data', [])[:5]) or '-'}",
                f.get("confidence", "?")]))
    out = a.out or os.path.join(a.work, "digest.txt")
    with open(out, "w", encoding="utf-8", newline="\n") as fp:
        fp.write("\n".join(lines) + "\n")
    print(f"ダイジェストを出力: {out}（局所機能 {n} 件 / 抽出済み {len(extracts)} / 全 {len(slices)} スライス）")


def cmd_merge(a, wp):
    slices, extracts = load_extracts(wp)
    ents = entries_by_id(wp)
    manifest = load_json(wp["files"])
    local = {}
    unmapped = {}
    missing_entries = []
    for s, d in extracts:
        for f in d.get("features", []):
            local[f["local_id"]] = f
        for u in d.get("unmapped_entries", []):
            unmapped[u["entry_id"]] = u.get("reason", "")
        missing_entries += d.get("missing_entries", [])

    g = load_json(a.grouping)
    used = collections.Counter()
    errors = []
    domains = []
    fno = 0
    for di, dom in enumerate(g.get("domains", []), 1):
        feats = []
        for gf in dom.get("features", []):
            fno += 1
            fid = f"F{fno:03d}"
            srcs = gf.get("sources") or []
            if not srcs:
                errors.append(f"{fid} {gf.get('name')}: sources が空")
            src = []
            for sid in srcs:
                if sid not in local:
                    errors.append(f"{fid} {gf.get('name')}: 存在しない局所機能 {sid}")
                else:
                    used[sid] += 1
                    src.append(local[sid])

            def union(key):
                seen, out = set(), []
                for f in src:
                    for v in f.get(key) or []:
                        k = repr(v)
                        if k not in seen:
                            seen.add(k)
                            out.append(v)
                return out
            conf = min((f.get("confidence", "unknown") for f in src), key=lambda c: CONF_RANK.get(c, 0),
                       default="unknown")
            entry_ids = union("entry_ids")
            feats.append({
                "id": fid, "name": gf.get("name", ""), "summary": gf.get("summary", ""),
                "actors": gf.get("actors") or union("actors"),
                "sources": srcs, "confidence": conf,
                "entries": [{"id": e, "kind": ents.get(e, {}).get("kind"), "label": ents.get(e, {}).get("label")}
                            for e in entry_ids],
                "data": union("data"), "external": union("external"),
                "evidence": union("evidence"), "open_questions": union("open_questions"),
                "local_summaries": [f.get("summary", "") for f in src],
            })
        domains.append({"id": f"D{di:02d}", "name": dom.get("name", ""), "summary": dom.get("summary", ""),
                        "features": feats})

    unused = sorted(set(local) - set(used))
    for u in unused:
        errors.append(f"どの機能にも配置されていない局所機能: {u} {local[u]['name']}")
    multi = sorted(k for k, n in used.items() if n > 1)

    mapped = {e["id"] for d in domains for f in d["features"] for e in f["entries"]}
    unclassified = []
    for eid, e in ents.items():
        if eid in mapped:
            continue
        unclassified.append({"id": eid, "kind": e["kind"], "label": e["label"], "path": e["path"],
                             "line": e["line"], "reason": unmapped.get(eid, "どのスライスでも対応付けられていない")})

    if errors and not a.allow_partial:
        for e in errors[:50]:
            print(f"不合格: {e}")
        print(f"不合格 {len(errors)} 件。grouping.json を直して再実行する（features.json は出力していない）")
        sys.exit(1)

    save_json(wp["features"], {
        "system": {"name": g.get("system", {}).get("name", ""), "description": g.get("system", {}).get("description", ""),
                   "repo": manifest["repo"], "commit": manifest.get("commit"), "subdir": manifest.get("subdir"),
                   "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
        "domains": domains, "unclassified_entries": unclassified, "missing_entries": missing_entries,
    })
    print(f"features.json を出力: {wp['features']}")
    print(f"ドメイン {len(domains)} / 機能 {fno} / 局所機能 {len(local)}（未配置 {len(unused)}、重複配置 {len(multi)}）")
    print(f"未分類の入口 {len(unclassified)} 件 / 分母に無かった入口の報告 {len(missing_entries)} 件")
    if multi:
        print("※ 複数の機能に配置された局所機能（意図どおりか確認）: " + " ".join(multi[:30]))


def cmd_sample(a, wp):
    data = load_json(wp["features"])
    feats = [f for d in data["domains"] for f in d["features"]]
    rnd = random.Random(a.seed)

    def risk(f):
        r = 0
        if f["confidence"] == "unknown":
            r += 3
        elif f["confidence"] == "inferred":
            r += 2
        if not f["entries"]:
            r += 2
        if len(f["sources"]) >= 3:
            r += 1
        return r
    high = sorted([f for f in feats if risk(f) > 0], key=lambda f: -risk(f))
    low = [f for f in feats if risk(f) == 0]
    rnd.shuffle(low)
    k_high = min(len(high), (a.n + 1) // 2)
    pick = high[:k_high] + low[:a.n - k_high]
    if len(pick) < a.n:
        pick += high[k_high:k_high + a.n - len(pick)]
    out = os.path.join(a.work, "review-sample.json")
    save_json(out, [{"feature_id": f["id"], "name": f["name"], "summary": f["summary"],
                     "confidence": f["confidence"], "entries": [e["label"] for e in f["entries"]],
                     "data": f["data"], "evidence": f["evidence"][:8], "risk": risk(f)} for f in pick])
    print(f"独立検証の対象を出力: {out}（{len(pick)} 件 / 全 {len(feats)} 機能。高リスク {k_high} 件 + 無作為）")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("digest")
    p.add_argument("--work", required=True)
    p.add_argument("--prefix")
    p.add_argument("--out")
    p = sub.add_parser("merge")
    p.add_argument("--work", required=True)
    p.add_argument("--grouping", required=True)
    p.add_argument("--allow-partial", action="store_true")
    p = sub.add_parser("sample")
    p.add_argument("--work", required=True)
    p.add_argument("--n", type=int, default=15)
    p.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    wp = work_paths(a.work)
    {"digest": cmd_digest, "merge": cmd_merge, "sample": cmd_sample}[a.cmd](a, wp)


if __name__ == "__main__":
    main()
