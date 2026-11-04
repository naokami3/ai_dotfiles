#!/usr/bin/env python3
"""ファイル一覧・エントリーポイント一覧に対する網羅率を集計する（coverage.json）。

verify_evidence.py の結果を前提に、合格した担当範囲だけを「読了済み」として数える。
1ファイルが複数の担当範囲に分割されている場合は、全区間が合格して初めて網羅済みとする。
features.json と review/*.json があれば、確信度の内訳と独立検証の結果も集計する
（features.json に存在しない feature_key の検証結果は、merge し直す前の古いものとして数えない）。
ファイル網羅率が 100% 未満、または未対応のエントリーポイントが残っていれば終了コード 1。

使い方:
    python3 check_coverage.py --work <作業ディレクトリ>
"""
import argparse
import collections

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import load_json, load_reviews, save_json, work_paths  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    a = ap.parse_args()
    wp = work_paths(a.work)

    manifest = load_json(wp["files"])
    sl = load_json(wp["slices"])
    slices = sl["slices"]
    inv = load_json(wp["inventory"]) if os.path.exists(wp["inventory"]) else {"entries": []}
    ents = inv["entries"]

    status = {}
    for s in slices:
        vf = os.path.join(wp["verify_dir"], f"{s['id']}.json")
        v = load_json(vf) if os.path.exists(vf) else {"missing": True}
        status[s["id"]] = "missing" if v.get("missing") else ("passed" if v.get("ok") else "failed")
    passed = [s for s in slices if status[s["id"]] == "passed"]

    # ファイル・行の網羅（ファイルの全区間が合格した担当範囲にあるときだけ網羅済み）
    skip = set(sl["skip_roles"])
    target = [f for f in manifest["files"] if f["role"] not in skip]
    canon = {f["path"]: f for f in target if "dup_of" not in f}
    items_all = collections.defaultdict(list)
    items_ok = collections.defaultdict(list)
    for s in slices:
        for i in s["items"]:
            items_all[i["path"]].append(i)
            if status[s["id"]] == "passed":
                items_ok[i["path"]].append(i)
    read_paths = {p for p in items_all if len(items_ok[p]) == len(items_all[p])}
    covered = [f for f in target if (f.get("dup_of") or f["path"]) in read_paths]
    uncovered = [f["path"] for f in target if (f.get("dup_of") or f["path"]) not in read_paths]
    total_lines = sum(f["lines"] for f in canon.values())
    read_full = sum(i["end"] - i["start"] + 1 for p in read_paths for i in items_ok[p] if i["mode"] == "full")
    outline_files = sum(1 for p in read_paths if all(i["mode"] == "outline" for i in items_all[p]))

    # エントリーポイントの網羅
    mapped, unmapped, no_entry, missing, local_total = set(), {}, 0, [], 0
    for s in passed:
        d = load_json(os.path.join(wp["extract_dir"], f"{s['id']}.json"))
        for f in d.get("features", []):
            local_total += 1
            mapped.update(f.get("entry_ids") or [])
            if not f.get("entry_ids"):
                no_entry += 1
        for u in d.get("unmapped_entries", []):
            unmapped[u["entry_id"]] = u
        missing += [{**m, "slice": s["id"]} for m in d.get("missing_entries", [])]
    all_ids = {e["id"] for e in ents}
    assigned = {eid for s in slices for eid in s["entry_ids"]}
    open_entries = [e["id"] for e in ents if e["id"] not in mapped and e["id"] not in unmapped]
    unread_entries = [e["id"] for e in ents if e["id"] not in assigned]
    um_by_code = collections.Counter(u.get("reason_code", "?") for u in unmapped.values())
    um_by_kind = collections.Counter()
    for e in ents:
        if e["id"] in unmapped:
            um_by_kind[e["kind"]] += 1
    kind_total = collections.Counter(e["kind"] for e in ents)

    report = {
        "slices": {"total": len(slices), **collections.Counter(status.values())},
        "files": {"total": len(target), "covered": len(covered), "outline_only": outline_files,
                  "uncovered": uncovered[:200], "excluded": len(manifest["excluded"]),
                  "excluded_by_reason": dict(collections.Counter(e["reason"] for e in manifest["excluded"])),
                  "skipped_roles": sl["skip_roles"]},
        "lines": {"total_unique": total_lines, "read_full": read_full},
        "entries": {"total": len(ents), "in_features": len(mapped & all_ids), "unmapped_with_reason": len(unmapped),
                    "open": open_entries[:200], "in_unread_files": unread_entries[:200],
                    "unmapped_by_reason_code": dict(um_by_code),
                    "unmapped_rate_by_kind": {k: f"{um_by_kind[k]}/{kind_total[k]}" for k in kind_total if um_by_kind[k]}},
        "excluded_candidates": len(inv.get("excluded_candidates", [])),
        "local_features": {"total": local_total, "without_entry": no_entry},
        "missing_entries_by_kind": dict(collections.Counter(m.get("kind") for m in missing)),
        "missing_entries": [{k: m.get(k) for k in ("kind", "label", "path", "line", "slice")} for m in missing[:200]],
    }

    keys = set()
    if os.path.exists(wp["features"]):
        fd = load_json(wp["features"])
        feats = [f for d in fd["domains"] for f in d["features"]]
        keys = {f["key"] for f in feats}
        report["features"] = {"domains": len(fd["domains"]), "total": len(feats),
                              "by_confidence": dict(collections.Counter(f["confidence"] for f in feats)),
                              "without_entry": sum(1 for f in feats if not f["entries"]),
                              "unclassified_entries": len(fd.get("unclassified_entries", [])),
                              "partial": fd["system"].get("partial", False)}
    rf, re_, stale = load_reviews(wp, keys)
    if rf or re_ or stale:
        report["review"] = {"features": dict(collections.Counter(r.get("verdict") for r in rf.values())),
                            "unmapped_entries": dict(collections.Counter(r.get("verdict") for r in re_.values())),
                            "stale_ignored": stale}

    save_json(wp["coverage"], report)

    pct = lambda n, d: f"{(100.0 * n / d):.1f}%" if d else "-"  # noqa: E731
    print(f"coverage.json を出力: {wp['coverage']}")
    st = report["slices"]
    print(f"担当範囲: 合格 {st.get('passed', 0)} / 不合格 {st.get('failed', 0)} / 未抽出 {st.get('missing', 0)}（全 {st['total']}）")
    print(f"ファイル網羅: {len(covered)}/{len(target)} ({pct(len(covered), len(target))})"
          f"  うち抜粋読み {outline_files} / 除外 {len(manifest['excluded'])}")
    print(f"行（全文読み）: {read_full}/{total_lines} ({pct(read_full, total_lines)})")
    e = report["entries"]
    print(f"エントリーポイント: 機能に対応 {e['in_features']} / 理由付き対象外 {e['unmapped_with_reason']} / 未対応 {len(open_entries)}"
          f"（全 {e['total']}、読まない役割のファイル内 {len(unread_entries)}）")
    if um_by_code:
        print("  対象外の理由: " + ", ".join(f"{k} {n}" for k, n in um_by_code.most_common())
              + " / 種別ごとの対象外率: " + ", ".join(f"{k} {v}" for k, v in e["unmapped_rate_by_kind"].items()))
    if report["excluded_candidates"]:
        print(f"※ 除外ファイル内のエントリーポイント候補 {report['excluded_candidates']} 件（enumerate_entrypoints の警告を確認したか）")
    print(f"集約前の機能 {local_total} 件（エントリーポイントなし {no_entry}）")
    if missing:
        print("一覧に無かったエントリーポイントの報告（検出ルールの見直し候補）: "
              + ", ".join(f"{k} {n}" for k, n in report["missing_entries_by_kind"].items()))
        for m in missing[:20]:
            print(f"  {m.get('kind')}: {m.get('label')} @ {m.get('path')}:{m.get('line')}")
        if len(missing) > 20:
            print(f"  …ほか {len(missing) - 20} 件は coverage.json の missing_entries")
    if "features" in report:
        f = report["features"]
        print(f"features.json: ドメイン {f['domains']} / 機能 {f['total']} / 確信度 {f['by_confidence']}"
              + ("（途中経過）" if f["partial"] else ""))
    if "review" in report:
        r = report["review"]
        print(f"独立検証: 機能 {r['features']} / 対象外のエントリーポイント {r['unmapped_entries']}"
              + (f"（古い結果 {r['stale_ignored']} 件は無視）" if r["stale_ignored"] else ""))
    ok = not uncovered and not open_entries and not unread_entries and st.get("passed", 0) == st["total"]
    print("判定: 網羅完了" if ok else "判定: 未完了（上の不足を解消する）")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
