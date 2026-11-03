#!/usr/bin/env python3
"""抽出担当エージェントが読むスライスの作業票を作る。

作業票の内容:
- 全文を読むファイルと行範囲（抽出担当が Read ツールで読む）
- アウトライン読みのファイルは、定義行・テスト名だけをここで展開済み（Read 不要）
- このスライスに割り当てられた入口（すべて features か unmapped_entries に対応付ける）
- 前回の検証で不合格だった場合は、そのエラー一覧（修正モード）

使い方:
    python3 slice_brief.py --work W --pending        # 未合格の全スライスの作業票を W/briefs/ に書く
    python3 slice_brief.py --work W --slice S001     # 1件を標準出力に出す（確認用）
--pending は書き出したスライス ID を「未抽出」「修正モード」に分けて出力する。
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import die, load_json, outline_lines, read_lines, work_paths  # noqa: E402


def brief(wp, repo, s, entries):
    L = [f"# スライス {s['id']}", "",
         f"- slice_id: {s['id']}", f"- slice_hash: {s['hash']}", f"- リポジトリ: {repo}",
         f"- 出力先: {os.path.join(wp['extract_dir'], s['id'] + '.json')}", ""]
    vf = os.path.join(wp["verify_dir"], f"{s['id']}.json")
    fix = None
    if os.path.exists(vf):
        v = load_json(vf)
        if not v.get("ok") and not v.get("missing"):
            fix = v.get("errors", [])
    if fix:
        L += ["## 修正モード", "",
              "前回の出力は検証で不合格だった。出力先の既存ファイルを読み、以下のエラーだけを直す。",
              "コードの再読は、エラーの箇所を確かめるのに必要な範囲だけにする。", ""]
        L += [f"- {e}" for e in fix] + [""]
    full = [i for i in s["items"] if i["mode"] == "full"]
    outl = [i for i in s["items"] if i["mode"] == "outline"]
    L += [f"## 全文を読むファイル（{len(full)} 件）", ""]
    L += [f"- {i['path']} L{i['start']}-{i['end']}" for i in full] + [""]
    if outl:
        L += [f"## アウトライン読みのファイル（{len(outl)} 件）", "",
              "以下が内容の要約（定義行・テスト名）。挙動を確かめたい箇所だけ Read してよい。", ""]
        for i in outl:
            L.append(f"### {i['path']}")
            L += [f"{n}: {t.strip()[:160]}" for n, t in outline_lines(read_lines(repo, i["path"]))]
            L.append("")
    L += [f"## このスライスの入口（{len(s['entry_ids'])} 件。全件を対応付ける）", ""]
    for eid in s["entry_ids"]:
        e = entries.get(eid, {})
        L.append(f"- `{eid}` [{e.get('kind')}] {e.get('label')}")
    return "\n".join(L) + "\n", bool(fix)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--slice")
    g.add_argument("--pending", action="store_true")
    a = ap.parse_args()

    wp = work_paths(a.work)
    repo = load_json(wp["files"])["repo"]
    slices = load_json(wp["slices"])["slices"]
    entries = {e["id"]: e for e in load_json(wp["inventory"])["entries"]} \
        if os.path.exists(wp["inventory"]) else {}

    if a.slice:
        s = next((x for x in slices if x["id"] == a.slice), None) or die(f"スライス {a.slice} が無い")
        print(brief(wp, repo, s, entries)[0], end="")
        return

    bdir = os.path.join(a.work, "briefs")
    os.makedirs(bdir, exist_ok=True)
    new, fixes = [], []
    for s in slices:
        vf = os.path.join(wp["verify_dir"], f"{s['id']}.json")
        if os.path.exists(vf) and load_json(vf).get("ok"):
            continue
        if os.path.exists(os.path.join(wp["extract_dir"], f"{s['id']}.json")) and not os.path.exists(vf):
            continue  # 抽出済み・未検証。先に verify_evidence.py を実行する
        text, is_fix = brief(wp, repo, s, entries)
        with open(os.path.join(bdir, f"{s['id']}.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        (fixes if is_fix else new).append(s["id"])
    print(f"作業票を出力: {bdir}")
    print(f"未抽出 {len(new)}: {' '.join(new)}")
    print(f"修正モード {len(fixes)}: {' '.join(fixes)}")


if __name__ == "__main__":
    main()
