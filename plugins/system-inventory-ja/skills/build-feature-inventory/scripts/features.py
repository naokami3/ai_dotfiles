#!/usr/bin/env python3
"""担当範囲横断の集約を支援する。自動検証に合格した抽出結果だけを使う。サブコマンド:

digest  合格済みの集約前の機能を 1 機能 1 行に圧縮した要約一覧を書き出す。
        集約担当はコードも抽出 JSON も読まず、これだけを見てグループ分けする。
            python3 features.py digest --work W [--prefix app/billing] [--out W/digest.txt]
        --prefix は集約前の機能の根拠ファイルのパスで絞る（同じ集約前の機能が複数の要約一覧に重複しない）

merge   集約担当が書いた grouping（名前・グループ分け・sources・actor_map、複数 sources の統合要約だけ）
        から features.json を作る。入口・データ・根拠・制約・確信度・要確認事項は sources から機械的に
        引き継ぐ。sources が1件の機能は集約前の要約をそのまま使う（統合文を書かせない）。
        grouping は複数ファイルを渡せる（ドメインごとに分けて作った場合）。
            python3 features.py merge --work W --grouping W/grouping.json [W/grouping-2.json ...]

sample  独立検証の対象をリスク順に選び、検証担当に渡すバッチファイルを書く。
        対象外にした入口（unmapped）の抜き取りも含める。
            python3 features.py sample --work W [--n 15] [--entries 10] [--batch-size 5] [--seed 0]
"""
import argparse
import collections
import hashlib
import os
import random
import shutil
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import copy_schema, die, load_json, save_json, work_paths  # noqa: E402

CONF_RANK = {"unknown": 0, "inferred": 1, "confirmed": 2}


def load_verified(wp, allow_partial=False):
    """自動検証に合格し、slice_hash が現在と一致する抽出結果だけを返す"""
    slices = load_json(wp["slices"])["slices"]
    ok, ng = [], []
    for s in slices:
        p = os.path.join(wp["extract_dir"], f"{s['id']}.json")
        vf = os.path.join(wp["verify_dir"], f"{s['id']}.json")
        v = load_json(vf) if os.path.exists(vf) else {}
        if os.path.exists(p) and v.get("ok"):
            d = load_json(p)
            if d.get("slice_hash") == s["hash"]:
                ok.append((s, d))
                continue
        ng.append(s["id"])
    if ng and not allow_partial:
        die(f"未検証・不合格・未抽出の担当範囲が {len(ng)} 件ある（{' '.join(ng[:10])}）。"
            "verify_evidence.py を通してから実行する（途中経過を見るだけなら --allow-partial）", 1)
    return slices, ok, ng


def entries_by_id(wp):
    if not os.path.exists(wp["inventory"]):
        return {}
    return {e["id"]: e for e in load_json(wp["inventory"])["entries"]}


def actor_names(f):
    return [a["name"] if isinstance(a, dict) else str(a) for a in f.get("actors") or []]


def cmd_digest(a, wp):
    slices, extracts, ng = load_verified(wp, a.allow_partial)
    ents = entries_by_id(wp)
    lines, n = [], 0
    for s, d in extracts:
        feats = d.get("features", [])
        if a.prefix:
            feats = [f for f in feats if any((ev.get("path") or "").startswith(a.prefix) for ev in f.get("evidence", []))]
        if not feats:
            continue
        dirs = sorted({i["path"].rsplit("/", 1)[0] if "/" in i["path"] else "." for i in s["items"]})
        lines.append(f"## {s['id']}  {', '.join(dirs[:4])}{' ...' if len(dirs) > 4 else ''}")
        for f in feats:
            n += 1
            labels = [f'{ents[e]["label"]} @{ents[e]["path"].rsplit("/", 1)[-1]}'
                      for e in f.get("entry_ids", []) if e in ents]
            ent = ", ".join(labels[:5]) + (f" 他{len(labels) - 5}" if len(labels) > 5 else "")
            cons = [c.get("text", "") for c in f.get("constraints") or [] if isinstance(c, dict)]
            lines.append(" | ".join([
                f["local_id"], f["name"], f.get("summary") or "",
                f"利用者: {', '.join(actor_names(f)) or '-'}",
                f"制約: {'; '.join(cons) or '-'}",
                f"入口: {ent or 'なし'}", f"data: {', '.join(f.get('data', [])[:5]) or '-'}",
                f.get("confidence", "?")]))
    out = a.out or os.path.join(a.work, "digest.txt")
    with open(out, "w", encoding="utf-8", newline="\n") as fp:
        fp.write("\n".join(lines) + "\n")
    print(f"要約一覧を出力: {out}（集約前の機能 {n} 件 / 合格した担当範囲 {len(extracts)} / 全 {len(slices)}）")
    actors = collections.Counter(x for _, d in extracts for f in d.get("features", []) for x in actor_names(f))
    print("集約前の利用者表記（actor_map で統一語彙に写像する）: "
          + ", ".join(f"{k}({v})" for k, v in actors.most_common()))


def feature_key(sources):
    return hashlib.sha1("\n".join(sorted(sources)).encode()).hexdigest()[:10]


def cmd_merge(a, wp):
    slices, extracts, ng = load_verified(wp, a.allow_partial)
    ents = entries_by_id(wp)
    manifest = load_json(wp["files"])
    local, unmapped, missing_entries = {}, {}, []
    for s, d in extracts:
        for f in d.get("features", []):
            local[f["local_id"]] = f
        for u in d.get("unmapped_entries", []):
            unmapped[u["entry_id"]] = u
        missing_entries += d.get("missing_entries", [])

    system, domains_in, actor_map = {}, [], {}
    for gp in a.grouping:
        g = load_json(gp)
        system = system or g.get("system", {})
        domains_in += g.get("domains", [])
        actor_map.update(g.get("actor_map", {}))

    used = collections.Counter()
    errors, warns = [], []
    domains, fno = [], 0
    all_actor_names = {x for f in local.values() for x in actor_names(f)}
    unmapped_actors = sorted(all_actor_names - set(actor_map))
    if unmapped_actors:
        errors.append(f"actor_map に無い集約前の利用者表記: {', '.join(unmapped_actors)}（統一語彙への写像を書く）")
    for di, dom in enumerate(domains_in, 1):
        feats = []
        if not (dom.get("name") or "").strip():
            errors.append(f"domains[{di - 1}]: name が空")
        for gf in dom.get("features", []):
            fno += 1
            fid = f"F{fno:03d}"
            srcs = gf.get("sources") or []
            if not srcs:
                errors.append(f"{fid} {gf.get('name')}: sources が空")
            src = []
            for sid in srcs:
                if sid not in local:
                    errors.append(f"{fid} {gf.get('name')}: 存在しない（または未合格の）集約前の機能 {sid}")
                else:
                    used[sid] += 1
                    src.append(local[sid])
            if not src:
                continue
            if len(src) == 1:
                if gf.get("summary"):
                    warns.append(f"{fid}: sources が1件なので grouping の summary は使わず集約前の要約を使った")
                summary = src[0].get("summary", "")
                name = gf.get("name") or src[0].get("name", "")
            else:
                summary = (gf.get("summary") or "").strip()
                name = (gf.get("name") or "").strip()
                if not summary or not name:
                    errors.append(f"{fid}: sources が複数の機能は name と summary（集約前の要約の統合）が必須")

            def union(items):
                seen, out = set(), []
                for v in items:
                    k = repr(v)
                    if k not in seen:
                        seen.add(k)
                        out.append(v)
                return out
            evidence, constraints, actors = [], [], []
            for f in src:
                evs = f.get("evidence") or []
                evidence += evs
                for c in f.get("constraints") or []:
                    i = c.get("evidence")
                    constraints.append({"text": c.get("text", ""), "evidence": evs[i] if isinstance(i, int) and i < len(evs) else None})
                actors += [actor_map.get(x, x) for x in actor_names(f)]
            conf = min((f.get("confidence", "unknown") for f in src), key=lambda c: CONF_RANK.get(c, 0))
            entry_ids = union(e for f in src for e in f.get("entry_ids") or [])
            feats.append({
                "id": fid, "key": feature_key(srcs), "name": name, "summary": summary,
                "actors": union(actors), "constraints": union(constraints), "sources": srcs, "confidence": conf,
                "entries": [{"id": e, "kind": ents.get(e, {}).get("kind"), "label": ents.get(e, {}).get("label"),
                             "path": ents.get(e, {}).get("path"), "line": ents.get(e, {}).get("line")}
                            for e in entry_ids],
                "data": union(x for f in src for x in f.get("data") or []),
                "external": union(x for f in src for x in f.get("external") or []),
                "evidence": union(evidence), "open_questions": union(q for f in src for q in f.get("open_questions") or []),
                "local_summaries": [{"local_id": f["local_id"], "name": f.get("name", ""), "summary": f.get("summary", "")}
                                    for f in src],
            })
        domains.append({"id": f"D{di:02d}", "name": dom.get("name", ""), "summary": dom.get("summary", ""),
                        "features": feats})

    for u in sorted(set(local) - set(used)):
        errors.append(f"どの機能にも配置されていない集約前の機能: {u} {local[u]['name']}")
    multi = sorted(k for k, n in used.items() if n > 1)
    if multi and not a.allow_multi:
        errors.append(f"複数の機能に配置された集約前の機能: {' '.join(multi[:20])}（意図的なら --allow-multi）")

    mapped = {e["id"] for d in domains for f in d["features"] for e in f["entries"]}
    unclassified = []
    for eid, e in ents.items():
        if eid in mapped:
            continue
        u = unmapped.get(eid, {})
        unclassified.append({"id": eid, "kind": e["kind"], "label": e["label"], "path": e["path"], "line": e["line"],
                             "reason_code": u.get("reason_code", "unassigned"),
                             "reason": u.get("reason", "どの担当範囲でも対応付けられていない")})

    for w in warns[:20]:
        print(f"警告: {w}")
    if errors:
        for e in errors[:50]:
            print(f"不合格: {e}")
        print(f"不合格 {len(errors)} 件。grouping を直して再実行する（features.json は出力していない）")
        sys.exit(1)

    save_json(wp["features"], {
        "system": {"name": system.get("name", ""), "description": system.get("description", ""),
                   "repo": manifest["repo"], "commit": manifest.get("commit"), "subdir": manifest.get("subdir"),
                   "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "partial": bool(ng)},
        "actor_map": actor_map,
        "domains": domains, "unclassified_entries": unclassified, "missing_entries": missing_entries,
    })
    print(f"features.json を出力: {wp['features']}")
    print(f"ドメイン {len(domains)} / 機能 {fno} / 集約前の機能 {len(local)}（重複配置 {len(multi)}）"
          + ("（途中経過: 未合格の担当範囲あり）" if ng else ""))
    print(f"未分類の入口 {len(unclassified)} 件 / 一覧に無かった入口の報告 {len(missing_entries)} 件")


def cmd_sample(a, wp):
    data = load_json(wp["features"])
    repo = data["system"]["repo"]
    feats = [f for d in data["domains"] for f in d["features"]]
    rnd = random.Random(a.seed)

    def risk(f):
        r = {"unknown": 3, "inferred": 2}.get(f["confidence"], 0)
        r += 2 if not f["entries"] else 0
        r += 1 if len(f["sources"]) >= 2 else 0   # 集約側で統合文を書いた機能
        r += 1 if f["constraints"] else 0          # 権限・制約の主張がある
        return r
    high = sorted([f for f in feats if risk(f) > 0], key=lambda f: -risk(f))
    low = [f for f in feats if risk(f) == 0]
    rnd.shuffle(low)
    k_high = min(len(high), (a.n + 1) // 2)
    pick = high[:k_high] + low[:a.n - k_high]
    if len(pick) < a.n:
        pick += high[k_high:k_high + a.n - len(pick)]
    un = [e for e in data.get("unclassified_entries", []) if e.get("reason_code") != "unassigned"]
    rnd.shuffle(un)
    ent_pick = un[:a.entries]

    bdir = os.path.join(a.work, "review-batches")
    copy_schema(a.work)
    if os.path.isdir(bdir):
        shutil.rmtree(bdir)
    items = [{"type": "feature", "feature_key": f["key"], "feature_id": f["id"], "name": f["name"],
              "summary": f["summary"], "actors": f["actors"],
              "constraints": [c["text"] for c in f["constraints"]], "data": f["data"],
              "entries": [f"{e['label']} ({e['path']}:{e['line']})" for e in f["entries"]],
              "evidence": [f"{ev['path']}:{ev['line']}" for ev in f["evidence"][:8]]} for f in pick]
    items += [{"type": "unmapped_entry", "entry_id": e["id"], "label": e["label"],
               "location": f"{e['path']}:{e['line']}", "reason_code": e["reason_code"], "reason": e["reason"]}
              for e in ent_pick]
    nb = 0
    for i in range(0, len(items), a.batch_size):
        nb += 1
        save_json(os.path.join(bdir, f"b{nb:02d}.json"), {"repo": repo, "output": os.path.join(wp["review_dir"], f"b{nb:02d}.json"),
                                                          "items": items[i:i + a.batch_size]})
    print(f"独立検証のバッチを出力: {bdir}（{nb} バッチ / 機能 {len(pick)} 件（高リスク {k_high}）+ 対象外の入口 {len(ent_pick)} 件 / 全 {len(feats)} 機能）")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("digest")
    p.add_argument("--work", required=True)
    p.add_argument("--prefix")
    p.add_argument("--out")
    p.add_argument("--allow-partial", action="store_true")
    p = sub.add_parser("merge")
    p.add_argument("--work", required=True)
    p.add_argument("--grouping", nargs="+", required=True)
    p.add_argument("--allow-partial", action="store_true")
    p.add_argument("--allow-multi", action="store_true")
    p = sub.add_parser("sample")
    p.add_argument("--work", required=True)
    p.add_argument("--n", type=int, default=15)
    p.add_argument("--entries", type=int, default=10)
    p.add_argument("--batch-size", type=int, default=5)
    p.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    wp = work_paths(a.work)
    {"digest": cmd_digest, "merge": cmd_merge, "sample": cmd_sample}[a.cmd](a, wp)


if __name__ == "__main__":
    main()
