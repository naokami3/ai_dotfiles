#!/usr/bin/env python3
"""features.json（元データ）から人間向けの機能一覧を生成する。出力は3形式:

- feature-inventory.xlsx : Excel で読む表（シート: 概要 / 機能一覧 / API一覧 / 画面一覧 / エントリーポイント一覧 / 要確認）
- feature-inventory.html : ブラウザで読む1ファイル完結の表（検索・絞り込み・詳細展開）
- feature-inventory.md   : テキストで差分を追う・エージェントが読むための版

内容はすべて features.json / inventory.json / coverage.json / review/*.json の値から組み立てる。
出力を手で書き換えない（直すなら grouping.json か抽出結果を直して再生成する）。

使い方:
    python3 render_inventory.py --work <作業ディレクトリ> [--out-dir <出力先>] [--formats xlsx,html,md]
依存: python3 標準ライブラリのみ。
"""
import argparse
import collections
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import load_json, load_reviews, work_paths  # noqa: E402
from _xlsx import write_xlsx  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CONF_LABEL = {"confirmed": "確認済み", "inferred": "推定", "unknown": "不明"}
KIND_LABEL = {"http_endpoint": "API", "ui_route": "画面", "cli_command": "CLI", "scheduled_job": "定期実行",
              "background_job": "非同期ジョブ", "event_consumer": "イベント購読", "webhook": "Webhook",
              "data_entity": "データ", "graphql_operation": "GraphQL", "rpc_method": "RPC", "other": "その他"}
VERDICT_LABEL = {"correct": "正確", "partially_correct": "一部誤り", "incorrect": "誤り", "unverifiable": "検証不能"}
ENTRY_VERDICT_LABEL = {"correct": "対象外で正しい", "should_be_feature": "機能にすべき", "unverifiable": "検証不能"}
REASON_LABEL = {"health_check": "死活監視", "dev_tool": "開発用", "ops_script": "運用", "test_support": "テスト支援",
                "framework_internal": "基盤", "data_definition": "データ定義", "duplicate": "重複",
                "dead_code": "未使用の疑い", "other": "その他", "unassigned": "未割り当て"}


def pct(n, d):
    return f"{100.0 * n / d:.1f}%" if d else "-"


def build_model(wp):
    fd = load_json(wp["features"])
    cov = load_json(wp["coverage"]) if os.path.exists(wp["coverage"]) else {}
    inv = load_json(wp["inventory"])["entries"] if os.path.exists(wp["inventory"]) else []

    sysi = dict(fd["system"])
    sysi["name"] = sysi.get("name") or os.path.basename(sysi["repo"].rstrip("/\\"))
    domains = fd["domains"]
    feats = [f for d in domains for f in d["features"]]
    # 検証結果は feature_key（sources から決まる）で結び付ける。merge し直して消えた機能の結果は無視
    reviews, entry_reviews, stale = load_reviews(wp, {f["key"] for f in feats})
    for d in domains:
        for f in d["features"]:
            f["domain_id"], f["domain_name"] = d["id"], d["name"]
            r = reviews.get(f["key"])
            f["review"] = (VERDICT_LABEL.get(r["verdict"], r["verdict"])
                           + (f" — {r['comment']}" if r.get("comment") else "")) if r else ""
            f["constraint_texts"] = [c["text"] + (f"（{c['evidence']['path']}:{c['evidence']['line']}）"
                                                  if c.get("evidence") else "") for c in f.get("constraints", [])]

    by_entry = collections.defaultdict(list)
    for f in feats:
        for e in f["entries"]:
            by_entry[e["id"]].append({"id": f["id"], "name": f["name"], "domain": f["domain_name"]})
    reasons = {u["id"]: f"[{REASON_LABEL.get(u.get('reason_code'), u.get('reason_code'))}] {u['reason']}"
               for u in fd.get("unclassified_entries", [])}
    entries = [{"id": e["id"], "kind": e["kind"], "label": e["label"], "path": e["path"], "line": e["line"],
                "features": by_entry.get(e["id"], []), "reason": reasons.get(e["id"], "")} for e in inv]
    for m in fd.get("missing_entries", []):
        entries.append({"id": "", "kind": m.get("kind", "other"), "label": m.get("label", "") + "（抽出時に報告・検出ルール外）",
                        "path": m["path"], "line": m["line"], "features": [], "reason": "検出ルールで拾えなかったエントリーポイント"})

    conf = collections.Counter(f["confidence"] for f in feats)
    overview = [("対象", sysi["repo"] + (f" / {sysi['subdir']}" if sysi.get("subdir") else "")),
                ("コミット", sysi.get("commit") or "不明"), ("生成日時", sysi["generated_at"]),
                ("ドメイン数", len(domains)), ("機能数", len(feats)),
                ("確信度", " / ".join(f"{CONF_LABEL[k]} {conf.get(k, 0)}" for k in CONF_LABEL)),
                ("エントリーポイントを持たない機能", sum(1 for f in feats if not f["entries"]))]
    stats = [("機能", len(feats)), ("ドメイン", len(domains)),
             ("確認済み", pct(conf.get("confirmed", 0), len(feats)))]
    if cov:
        fc, lc, ec = cov["files"], cov["lines"], cov["entries"]
        overview += [("ファイル網羅", f"{fc['covered']} / {fc['total']}（{pct(fc['covered'], fc['total'])}）"),
                     ("うち抜粋読み", fc["outline_only"]),
                     ("全文読みした行", f"{lc['read_full']} / {lc['total_unique']}"),
                     ("対象外とした役割", ", ".join(fc["skipped_roles"]) or "なし"),
                     ("除外ファイル", f"{fc['excluded']}（" + ", ".join(f"{k} {n}" for k, n in fc["excluded_by_reason"].items()) + "）"),
                     ("エントリーポイント", f"全 {ec['total']}（機能に対応 {ec['in_features']} / 対象外 {ec['unmapped_with_reason']} / 未対応 {len(ec['open'])}）")]
        stats += [("ファイル網羅", pct(fc["covered"], fc["total"])),
                  ("エントリーポイントの対応", pct(ec["in_features"] + ec["unmapped_with_reason"], ec["total"]))]
    if reviews:
        vc = collections.Counter(r["verdict"] for r in reviews.values())
        overview.append(("独立検証（機能・抜き取り）", f"{len(reviews)} 件中 " + " / ".join(
            f"{VERDICT_LABEL[k]} {vc[k]}" for k in VERDICT_LABEL if vc.get(k))))
        stats.append(("独立検証 正確", pct(vc.get("correct", 0), len(reviews))))
    if entry_reviews:
        ec2 = collections.Counter(r.get("verdict") for r in entry_reviews.values())
        overview.append(("独立検証（対象外のエントリーポイント・抜き取り）", f"{len(entry_reviews)} 件中 "
                         + " / ".join(f"{ENTRY_VERDICT_LABEL.get(k, k)} {n}" for k, n in ec2.items())))
    if sysi.get("partial"):
        overview.insert(0, ("注意", "途中経過: 未合格・未抽出の担当範囲があり、網羅していない"))
    questions = [(f["id"], f["name"], q["question"], q["how_to_check"] or "（未記載）")
                 for f in feats for q in f["open_questions"]]

    # API一覧・画面一覧: エントリーポイントのうち API と画面を、対応する機能名（＝概要・画面名）と並べる
    def listing(kind):
        return [{"label": re.sub(r"\s*\([^()]*\)$", "", e["label"]), "path": e["path"], "line": e["line"],
                 "features": e["features"], "reason": e["reason"]} for e in entries if e["kind"] == kind]
    return {"system": sysi, "domains": domains, "feats": feats, "entries": entries, "overview": overview,
            "apis": listing("http_endpoint"), "screens": listing("ui_route"),
            "stats": stats, "questions": questions, "cov": cov}


def write_xlsx_out(m, path):
    frows = []
    for f in m["feats"]:
        frows.append([
            f["domain_id"], f["domain_name"], f["id"], f["name"], f["summary"], ", ".join(f["actors"]),
            "\n".join(f["constraint_texts"]),
            CONF_LABEL.get(f["confidence"], f["confidence"]), len(f["entries"]),
            "\n".join(f"[{KIND_LABEL.get(e['kind'], e['kind'])}] {e['label']}" for e in f["entries"]),
            "\n".join(f["data"]), "\n".join(f["external"]),
            "\n".join(f"{q['question']}（確認方法: {q['how_to_check'] or '未記載'}）" for q in f["open_questions"]),
            "\n".join(f"{e['path']}:{e['line']}" for e in f["evidence"][:10]), f["review"],
            "\n".join(f"{x['local_id']}: {x['summary']}" for x in f.get("local_summaries", [])) if len(f["sources"]) > 1 else "",
            f["key"]])
    erows = [[KIND_LABEL.get(e["kind"], e["kind"]), e["label"], e["path"], e["line"],
              "\n".join(x["id"] for x in e["features"]), "\n".join(x["name"] for x in e["features"]),
              "" if e["features"] else e["reason"], e["id"]] for e in m["entries"]]

    def lrows(rows, name_first):
        out = []
        for r in rows:
            names = "\n".join(x["name"] for x in r["features"]) or f"（機能に対応しない: {r['reason']}）"
            pair = [names, r["label"]] if name_first else [r["label"], names]
            out.append(pair + [f"{r['path']}:{r['line']}", "\n".join(x["domain"] for x in r["features"]),
                               "\n".join(x["id"] for x in r["features"])])
        return out
    write_xlsx(path, [
        ("概要", ["項目", "値"], [list(r) for r in m["overview"]], [22, 90]),
        ("機能一覧", ["ドメインID", "ドメイン", "機能ID", "機能名", "概要", "利用者", "制約（根拠）", "確信度", "エントリーポイント数",
                   "エントリーポイント", "データ", "外部連携", "要確認", "根拠（ファイル:行）", "独立検証",
                   "統合前の要約（統合した機能のみ）", "機能キー"],
         frows, [9, 16, 8, 26, 60, 16, 44, 9, 7, 44, 22, 16, 40, 40, 16, 60, 12]),
        ("API一覧", ["API", "概要", "ソースコード（ファイル:行）", "ドメイン", "機能ID"],
         lrows(m["apis"], False), [40, 40, 56, 18, 9]),
        ("画面一覧", ["画面名", "URL", "ソースコード（ファイル:行）", "ドメイン", "機能ID"],
         lrows(m["screens"], True), [40, 30, 56, 18, 9]),
        ("エントリーポイント一覧", ["種別", "エントリーポイント", "ファイル", "行", "機能ID", "機能名", "未分類の理由", "エントリーポイントID"],
         erows, [11, 40, 50, 7, 9, 26, 30, 40]),
        ("要確認", ["機能ID", "機能名", "未確認の点", "確認方法"], [list(q) for q in m["questions"]], [9, 26, 60, 60]),
    ])


def write_html_out(m, path):
    data = {"system": m["system"], "kindLabels": KIND_LABEL, "stats": m["stats"], "overview": m["overview"],
            "questions": m["questions"], "entries": m["entries"], "apis": m["apis"], "screens": m["screens"],
            "domains": [{"id": d["id"], "name": d["name"], "summary": d["summary"],
                         "features": [{k: f.get(k) for k in ("id", "key", "name", "summary", "actors", "constraint_texts",
                                                             "entries", "data", "external", "evidence", "open_questions",
                                                             "confidence", "sources", "review", "local_summaries")}
                                      for f in d["features"]]} for d in m["domains"]]}
    # <script> 内に埋め込むので < を全部エスケープする（引用に <!-- や <script が含まれても壊れないように）
    blob = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    with open(os.path.join(HERE, "_inventory_template.html"), encoding="utf-8") as f:
        tpl = f.read()
    html = tpl.replace("__TITLE__", m["system"]["name"].replace("<", "&lt;")).replace("__DATA__", blob)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)


def cell(s):
    return str(s or "").replace("|", "\\|").replace("\n", " ")


def write_md_out(m, path):
    L = []
    w = L.append
    w(f"# 機能一覧: {m['system']['name']}")
    w("")
    w("> 元データは `features.json`。根拠（`ファイル:行`）は自動検証済みの引用にもとづく。")
    w("> 確信度「推定」「不明」と「要確認」は人間による確認が必要。")
    w("")
    w("## 概要")
    w("")
    w("| 項目 | 値 |")
    w("|---|---|")
    for k, v in m["overview"]:
        w(f"| {k} | {cell(v)} |")
    w("")
    for d in m["domains"]:
        w(f"## {d['id']} {d['name']}")
        w("")
        if d["summary"]:
            w(d["summary"])
            w("")
        for f in d["features"]:
            w(f"### {f['id']} {f['name']}（{CONF_LABEL.get(f['confidence'], f['confidence'])}）")
            w("")
            w(f["summary"])
            w("")
            if f["actors"]:
                w(f"- 利用者: {', '.join(f['actors'])}")
            for c in f["constraint_texts"]:
                w(f"- 制約: {c}")
            for e in f["entries"]:
                w(f"- エントリーポイント[{KIND_LABEL.get(e['kind'], e['kind'])}]: `{e['label']}`")
            if f["data"]:
                w(f"- データ: {', '.join(f['data'])}")
            if f["external"]:
                w(f"- 外部連携: {', '.join(f['external'])}")
            w("- 根拠: " + ", ".join(f"`{e['path']}:{e['line']}`" for e in f["evidence"][:10]))
            for q in f["open_questions"]:
                w(f"- 要確認: {q['question']}（確認方法: {q['how_to_check'] or '未記載'}）")
            if f["review"]:
                w(f"- 独立検証: {f['review']}")
            w("")
    for title, rows, head in (("API一覧", m["apis"], "| API | 概要 | ソースコード | 機能ID |"),
                              ("画面一覧", m["screens"], "| URL | 画面名 | ソースコード | 機能ID |")):
        w(f"## {title}")
        w("")
        w(head)
        w("|---|---|---|---|")
        for r in rows:
            names = " / ".join(x["name"] for x in r["features"]) or f"（機能に対応しない: {r['reason']}）"
            w(f"| `{cell(r['label'])}` | {cell(names)} | `{r['path']}:{r['line']}` | {' '.join(x['id'] for x in r['features'])} |")
        if not rows:
            w("| なし | | | |")
        w("")
    w("## 未分類のエントリーポイント")
    w("")
    un = [e for e in m["entries"] if not e["features"]]
    for e in un:
        w(f"- [{KIND_LABEL.get(e['kind'], e['kind'])}] `{e['label']}` `{e['path']}:{e['line']}` — {e['reason']}")
    if not un:
        w("なし")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--out-dir")
    ap.add_argument("--formats", default="xlsx,html,md")
    a = ap.parse_args()
    wp = work_paths(a.work)
    m = build_model(wp)
    out = a.out_dir or a.work
    os.makedirs(out, exist_ok=True)
    writers = {"xlsx": write_xlsx_out, "html": write_html_out, "md": write_md_out}
    for fmt in a.formats.split(","):
        p = os.path.join(out, f"feature-inventory.{fmt}")
        writers[fmt](m, p)
        print(f"出力: {p}")
    print(f"機能 {len(m['feats'])} / エントリーポイント {len(m['entries'])} / 要確認 {len(m['questions'])}")


if __name__ == "__main__":
    main()
