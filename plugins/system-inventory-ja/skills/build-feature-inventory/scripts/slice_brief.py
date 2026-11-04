#!/usr/bin/env python3
"""抽出担当エージェントが読む担当範囲の指示書を作る。

指示書の内容:
- 全文を読むファイルと行範囲（抽出担当が Read ツールで読む）
- 読了確認の窓（各窓から1行ずつ引用させる。スクリプトが決めた区間なので、読まずには答えにくい）
- 抜粋読みのファイルは、定義行・テスト名だけをここで展開済み（Read 不要）
- この担当範囲に割り当てられた入口（すべて features か unmapped_entries に対応付ける）
- 修正依頼: 前回の自動検証のエラー、または独立検証の指摘

使い方:
    python3 slice_brief.py --work W --pending            # 未合格の全担当範囲の指示書を W/briefs/ に書く
    python3 slice_brief.py --work W --from-review W/review/b1.json   # 独立検証の指摘から修正の指示書を書く
    python3 slice_brief.py --work W --slice S1a2b3c      # 1件を標準出力に出す（確認用）
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import copy_schema, die, load_json, outline_lines, read_lines, work_paths  # noqa: E402


def brief(wp, repo, s, entries, fix_errors=None, review_notes=None):
    L = [f"# 担当範囲 {s['id']}", "",
         f"- slice_id: {s['id']}", f"- slice_hash: {s['hash']}", f"- リポジトリ: {repo}",
         f"- 出力先: {os.path.join(wp['extract_dir'], s['id'] + '.json')}", ""]
    if fix_errors:
        L += ["## 修正依頼（自動検証の不合格）", "",
              "出力先の既存ファイルを読み、以下のエラーだけを直す。コードの再読はエラーの確認に必要な範囲だけにする。",
              "既存の local_id を別の機能に使い回さない（機能を消したら番号は欠番のまま、新しい機能は新しい番号）。", ""]
        L += [f"- {e}" for e in fix_errors] + [""]
    if review_notes:
        L += ["## 修正依頼（独立検証の指摘）", "",
              "別の検証担当がコードと照合して、以下の集約前の機能の記述に誤りを見つけた。指摘の根拠の行を自分で読んで確かめ、",
              "正しければ該当の集約前の機能を直す（要約・actors・constraints・evidence）。指摘が誤りなら直さず notes に理由を書く。",
              "既存の local_id を別の機能に使い回さない。", ""]
        for n in review_notes:
            L.append(f"- 対象: {', '.join(n['local_ids'])}（{n['verdict']}）: {n['comment']}")
            for ev in n.get("evidence", []):
                L.append(f"  - 根拠: {ev['path']}:{ev['line']} `{ev['quote']}`")
        L.append("")
    full = [i for i in s["items"] if i["mode"] == "full"]
    outl = [i for i in s["items"] if i["mode"] == "outline"]
    L += [f"## 全文を読むファイル（{len(full)} 件）", "",
          "Read は 1 回あたり 2000 行までしか返らない。それを超える範囲は offset / limit で分けて読む。", ""]
    L += [f"- {i['path']} L{i['start']}-{i['end']}" for i in full] + [""]
    checks = s.get("read_checks", [])
    if checks:
        L += [f"## 読了確認（{len(checks)} 件）", "",
              "各区間から、10 文字以上ある行を1行選び、`read_checks` に path・line・quote（その行の文字列をそのまま）で書く。", ""]
        L += [f"- {c['path']} L{c['start']}-{c['end']}" for c in checks] + [""]
    if outl:
        L += [f"## 抜粋読みのファイル（{len(outl)} 件）", "",
              "以下が内容の要約（定義行・テスト名）。挙動を確かめたい箇所だけ Read してよい。", ""]
        for i in outl:
            L.append(f"### {i['path']}")
            L += [f"{n}: {t.strip()[:160]}" for n, t in outline_lines(read_lines(repo, i["path"]))]
            L.append("")
    L += [f"## この担当範囲の入口（{len(s['entry_ids'])} 件。全件を対応付ける）", ""]
    for eid in s["entry_ids"]:
        e = entries.get(eid, {})
        note = f"（{e['dup_of']} と同一内容）" if e.get("dup_of") else ""
        L.append(f"- `{eid}` [{e.get('kind')}] {e.get('label')}{note}")
    return "\n".join(L) + "\n"


def write(bdir, sid, text):
    os.makedirs(bdir, exist_ok=True)
    with open(os.path.join(bdir, f"{sid}.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--slice")
    g.add_argument("--pending", action="store_true")
    g.add_argument("--from-review", nargs="+")
    a = ap.parse_args()

    wp = work_paths(a.work)
    repo = load_json(wp["files"])["repo"]
    slices = load_json(wp["slices"])["slices"]
    by_id = {s["id"]: s for s in slices}
    entries = {e["id"]: e for e in load_json(wp["inventory"])["entries"]} \
        if os.path.exists(wp["inventory"]) else {}
    bdir = os.path.join(a.work, "briefs")
    copy_schema(a.work)

    if a.slice:
        s = by_id.get(a.slice) or die(f"担当範囲 {a.slice} が無い")
        print(brief(wp, repo, s, entries), end="")
        return

    if a.from_review:
        feats = {f["key"]: f for d in load_json(wp["features"])["domains"] for f in d["features"]}
        notes = {}
        stale = 0
        for rp in a.from_review:
            for r in load_json(rp).get("results", []):
                if r.get("verdict") not in ("partially_correct", "incorrect"):
                    continue
                f = feats.get(r.get("feature_key"))
                if not f:
                    stale += 1
                    continue
                for lid in f["sources"]:
                    sid = lid.rsplit("-F", 1)[0]
                    if sid in by_id:
                        notes.setdefault(sid, []).append({"local_ids": [x for x in f["sources"] if x.startswith(sid + "-")],
                                                          "verdict": r["verdict"], "comment": r.get("comment", ""),
                                                          "evidence": r.get("evidence", [])})
        for sid, ns in notes.items():
            uniq = {(n["comment"], tuple(n["local_ids"])): n for n in ns}.values()
            write(bdir, sid, brief(wp, repo, by_id[sid], entries, review_notes=list(uniq)))
        print(f"修正の指示書を出力: {bdir}（担当範囲 {len(notes)} 件: {' '.join(notes)}）")
        if stale:
            print(f"※ features.json に存在しない feature_key の指摘 {stale} 件は無視した（merge し直した後の古い検証結果）")
        return

    new, fixes = [], []
    for s in slices:
        vf = os.path.join(wp["verify_dir"], f"{s['id']}.json")
        v = load_json(vf) if os.path.exists(vf) else None
        if v and v.get("ok"):
            continue
        if os.path.exists(os.path.join(wp["extract_dir"], f"{s['id']}.json")) and not v:
            continue  # 抽出済み・未検証。先に verify_evidence.py を実行する
        errs = v.get("errors") if v and not v.get("missing") else None
        write(bdir, s["id"], brief(wp, repo, s, entries, fix_errors=errs))
        (fixes if errs else new).append(s["id"])
    print(f"指示書を出力: {bdir}")
    print(f"未抽出 {len(new)}: {' '.join(new)}")
    print(f"修正依頼 {len(fixes)}: {' '.join(fixes)}")


if __name__ == "__main__":
    main()
