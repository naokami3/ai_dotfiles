#!/usr/bin/env python3
"""分母（ファイル・入口）に対する網羅率を集計する（coverage.json）。

verify_evidence.py の結果を前提に、合格スライスだけを「読了済み」として数える。
features.json と review/*.json があれば、確信度の内訳と独立検証の結果も集計する。
ファイル網羅率が 100% 未満、または未対応の入口が残っていれば終了コード 1。

使い方:
    python3 check_coverage.py --work <作業ディレクトリ>
"""
import argparse
import collections
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import load_json, save_json, work_paths  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    a = ap.parse_args()
    wp = work_paths(a.work)

    manifest = load_json(wp["files"])
    sl = load_json(wp["slices"])
    slices = sl["slices"]
    ents = load_json(wp["inventory"])["entries"] if os.path.exists(wp["inventory"]) else []

    status = {}
    for s in slices:
        vf = os.path.join(wp["verify_dir"], f"{s['id']}.json")
        v = load_json(vf) if os.path.exists(vf) else {"missing": True}
        status[s["id"]] = "missing" if v.get("missing") else ("passed" if v.get("ok") else "failed")
    passed = [s for s in slices if status[s["id"]] == "passed"]

    # ファイル・行の網羅
    target = [f for f in manifest["files"] if f["role"] not in set(sl["skip_roles"])]
    canon = {f["path"]: f for f in target if "dup_of" not in f}
    read_paths = {i["path"] for s in passed for i in s["items"]}
    full_lines = collections.defaultdict(int)
    for s in passed:
        for i in s["items"]:
            if i["mode"] == "full":
                full_lines[i["path"]] += i["end"] - i["start"] + 1
    covered_files = [f for f in target if (f.get("dup_of") or f["path"]) in read_paths]
    uncovered = [f["path"] for f in target if (f.get("dup_of") or f["path"]) not in read_paths]
    total_lines = sum(f["lines"] for f in canon.values())
    read_full = sum(min(full_lines[p], canon[p]["lines"]) for p in full_lines if p in canon)
    outline_files = sum(1 for p in read_paths if p in canon and p not in full_lines)

    # 入口の網羅
    mapped, unmapped_reasons, no_entry, missing = set(), {}, 0, []
    local_total = 0
    for s in passed:
        d = load_json(os.path.join(wp["extract_dir"], f"{s['id']}.json"))
        for f in d.get("features", []):
            local_total += 1
            mapped.update(f.get("entry_ids") or [])
            if not f.get("entry_ids"):
                no_entry += 1
        for u in d.get("unmapped_entries", []):
            unmapped_reasons[u["entry_id"]] = u.get("reason", "")
        missing += d.get("missing_entries", [])
    open_entries = [e["id"] for e in ents if e["id"] not in mapped and e["id"] not in unmapped_reasons]

    report = {
        "slices": {"total": len(slices), **collections.Counter(status.values())},
        "files": {"total": len(target), "covered": len(covered_files), "outline_only": outline_files,
                  "uncovered": uncovered[:200], "excluded": len(manifest["excluded"]),
                  "excluded_by_reason": dict(collections.Counter(e["reason"] for e in manifest["excluded"])),
                  "skipped_roles": sl["skip_roles"]},
        "lines": {"total_unique": total_lines, "read_full": read_full},
        "entries": {"total": len(ents), "in_features": len(mapped & {e["id"] for e in ents}),
                    "unmapped_with_reason": len(unmapped_reasons), "open": open_entries[:200]},
        "local_features": {"total": local_total, "without_entry": no_entry},
        "missing_entries_by_kind": dict(collections.Counter(m.get("kind") for m in missing)),
    }

    if os.path.exists(wp["features"]):
        fd = load_json(wp["features"])
        feats = [f for d in fd["domains"] for f in d["features"]]
        report["features"] = {"domains": len(fd["domains"]), "total": len(feats),
                              "by_confidence": dict(collections.Counter(f["confidence"] for f in feats)),
                              "without_entry": sum(1 for f in feats if not f["entries"]),
                              "unclassified_entries": len(fd.get("unclassified_entries", []))}
    verdicts = collections.Counter()
    for rp in glob.glob(os.path.join(wp["review_dir"], "*.json")):
        for r in load_json(rp).get("results", []):
            verdicts[r.get("verdict")] += 1
    if verdicts:
        report["review"] = dict(verdicts)

    save_json(wp["coverage"], report)

    pct = lambda n, d: f"{(100.0 * n / d):.1f}%" if d else "-"  # noqa: E731
    print(f"coverage.json を出力: {wp['coverage']}")
    st = report["slices"]
    print(f"スライス: 合格 {st.get('passed', 0)} / 不合格 {st.get('failed', 0)} / 未抽出 {st.get('missing', 0)}（全 {st['total']}）")
    print(f"ファイル網羅: {len(covered_files)}/{len(target)} ({pct(len(covered_files), len(target))})"
          f"  うちアウトライン読み {outline_files}  / 除外 {len(manifest['excluded'])}")
    print(f"行（全文読み）: {read_full}/{total_lines} ({pct(read_full, total_lines)})")
    e = report["entries"]
    print(f"入口: 機能に対応 {e['in_features']} / 理由付き対象外 {e['unmapped_with_reason']} / 未対応 {len(open_entries)}（全 {e['total']}）")
    print(f"局所機能 {local_total} 件（入口なし {no_entry}）")
    if missing:
        print("分母に無かった入口の報告（検出器の見直し候補）: "
              + ", ".join(f"{k} {n}" for k, n in report["missing_entries_by_kind"].items()))
    if "features" in report:
        f = report["features"]
        print(f"features.json: ドメイン {f['domains']} / 機能 {f['total']} / 確信度 {f['by_confidence']}")
    if verdicts:
        print(f"独立検証: {dict(verdicts)}")
    ok = not uncovered and not open_entries and st.get("passed", 0) == st["total"]
    print("判定: 網羅完了" if ok else "判定: 未完了（上の不足を解消する）")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
