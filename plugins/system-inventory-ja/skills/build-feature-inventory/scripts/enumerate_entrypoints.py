#!/usr/bin/env python3
"""入口分母（inventory.json）を作る。検出器 YAML の正規表現を機械的に実行するだけで、推測はしない。

使い方:
    python3 enumerate_entrypoints.py --work <作業ディレクトリ> --detectors <yaml> [<yaml>...]
        [--roles source,config]

検出器 YAML の書式は ../references/detectors.md を参照。
既定では role が source / config のファイルだけを対象にする（テスト内の URL 文字列等を拾わないため）。
依存: PyYAML（pip install pyyaml）。
"""
import argparse
import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import GlobSet, die, load_json, read_text, save_json, work_paths  # noqa: E402

try:
    import yaml
except ImportError:
    die("PyYAML が必要です: pip install pyyaml")

KINDS = {"http_endpoint", "ui_route", "cli_command", "scheduled_job", "background_job",
         "event_consumer", "webhook", "data_entity", "graphql_operation", "rpc_method", "other"}
TEMPLATE_RE = re.compile(r"\{(\w+)(?:\|(\w+))?\}")


def render_label(template, groups):
    def sub(m):
        v = groups.get(m.group(1)) or ""
        f = m.group(2)
        if f == "upper":
            v = v.upper()
        elif f == "lower":
            v = v.lower()
        return v
    return TEMPLATE_RE.sub(sub, template)


def load_rules(paths):
    rules = []
    for p in paths:
        if not os.path.exists(p):
            if any(c in p for c in "*?["):
                continue  # シェルで展開されなかった glob（該当ファイルなし）
            die(f"検出器ファイルが無い: {p}")
        with open(p, encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        det = doc.get("name") or os.path.splitext(os.path.basename(p))[0]
        for r in doc.get("rules", []):
            rid = r.get("id")
            if not rid:
                die(f"{p}: id の無いルールがある")
            if r.get("kind") not in KINDS:
                die(f"{p}:{rid}: kind が不正（{sorted(KINDS)} のいずれか）")
            if not r.get("pattern") and not r.get("path_pattern"):
                die(f"{p}:{rid}: pattern か path_pattern のどちらかが必要")
            try:
                rules.append({
                    "detector": det, "id": rid, "kind": r["kind"],
                    "files": GlobSet(r.get("files") or ["**"]),
                    "exclude": GlobSet(r.get("exclude") or []),
                    "path_re": re.compile(r["path_pattern"]) if r.get("path_pattern") else None,
                    "re": re.compile(r["pattern"], re.MULTILINE) if r.get("pattern") else None,
                    "label": r.get("label") or "{match}",
                    "normalize": [(re.compile(x[0]), x[1]) for x in r.get("normalize") or []],
                })
            except re.error as e:
                die(f"{p}:{rid}: 正規表現エラー: {e}")
    return rules


def scan(repo, path, rules):
    """1ファイルに全ルールを適用し、(rule, line, label) のリストを返す"""
    text, out = None, []
    for r in rules:
        if not r["files"].match(path) or r["exclude"].match(path):
            continue
        pgroups = {}
        if r["path_re"]:
            pm = r["path_re"].search(path)
            if not pm:
                continue
            pgroups = {k: v for k, v in pm.groupdict().items() if v is not None}
        hits = []
        if r["re"]:
            if text is None:
                text = read_text(repo, path)
            for m in r["re"].finditer(text):
                line = text.count("\n", 0, m.start()) + 1  # split_lines と同じ数え方（\n のみ）
                g = dict(pgroups)
                g.update({k: v for k, v in m.groupdict().items() if v is not None})
                g["match"] = m.group(0).strip().split("\n")[0][:120] if m.group(0).strip() else ""
                hits.append((line, g))
        else:
            hits.append((1, dict(pgroups, match=path)))
        for line, g in hits:
            g["file"] = path
            label = render_label(r["label"], g)
            for rx, rep in r["normalize"]:
                label = rx.sub(rep, label)
            out.append((r, line, label.strip()))
    return out


SCAN_EXCLUDED_REASONS = {"default_exclude", "generated_marker", "minified_or_long_lines", "large_data",
                         "user_exclude"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--detectors", nargs="+", required=True)
    ap.add_argument("--roles", default="source,config,doc",
                    help="対象にする役割（既定: test 以外。テスト内の URL 文字列を拾わないため）")
    a = ap.parse_args()

    wp = work_paths(a.work)
    manifest = load_json(wp["files"])
    repo = manifest["repo"]
    roles = set(a.roles.split(","))
    rules = load_rules(a.detectors)
    ids = collections.Counter(r["id"] for r in rules)
    dup_ids = [k for k, n in ids.items() if n > 1]
    if dup_ids:
        die(f"ルール id が重複している: {dup_ids}")
    # 重複ファイル（dup_of）も対象にする: ファイルベースルーティングでは URL がパスに宿るため
    targets = [f for f in manifest["files"] if f["role"] in roles]

    entries, seen = [], collections.Counter()
    counts = collections.Counter()
    for f in targets:
        for r, line, label in scan(repo, f["path"], rules):
            base = f"{r['id']}@{f['path']}:{line}"
            seen[base] += 1
            eid = base if seen[base] == 1 else f"{base}#{seen[base]}"
            counts[(r["detector"], r["id"], r["kind"])] += 1
            e = {"id": eid, "kind": r["kind"], "label": label, "path": f["path"], "line": line,
                 "detector": r["detector"], "rule": r["id"]}
            if f.get("dup_of"):
                e["dup_of"] = f["dup_of"]
            entries.append(e)

    # 除外したファイルにも検出器をかけ、入口候補があれば警告する（業務コードの誤除外の検知）
    excluded_hits = []
    for e in manifest["excluded"]:
        if e["reason"] not in SCAN_EXCLUDED_REASONS:
            continue
        try:
            hits = scan(repo, e["path"], rules)
        except OSError:
            continue
        for r, line, label in hits:
            excluded_hits.append({"path": e["path"], "line": line, "kind": r["kind"], "label": label,
                                  "reason": e["reason"]})

    rule_stats = [{"detector": r["detector"], "rule": r["id"], "kind": r["kind"],
                   "count": counts[(r["detector"], r["id"], r["kind"])]} for r in rules]
    save_json(wp["inventory"], {"detectors": [os.path.abspath(p) for p in a.detectors if os.path.exists(p)],
                                "rule_stats": rule_stats, "entries": entries,
                                "excluded_candidates": excluded_hits})

    print(f"inventory.json を出力: {wp['inventory']}（入口 {len(entries)} 件 / 対象 {len(targets)} ファイル）")
    by_kind = collections.Counter(e["kind"] for e in entries)
    print("種別: " + ", ".join(f"{k} {n}" for k, n in by_kind.most_common()))
    print("ルール別（1件以上）:")
    for st in rule_stats:
        if st["count"]:
            print(f"  {st['detector']}/{st['rule']} ({st['kind']}): {st['count']}")
    zero = [st["rule"] for st in rule_stats if st["count"] == 0]
    if zero:
        print(f"0件のルール {len(zero)} 件（このスタックで使っていないか、パターンが合っていない）: {' '.join(zero)}")
    if excluded_hits:
        by_dir = collections.Counter((h["path"].rsplit("/", 1)[0] if "/" in h["path"] else "(root)", h["reason"])
                                     for h in excluded_hits)
        print(f"※ 除外したファイルの中に入口候補が {len(excluded_hits)} 件ある。業務コードを除外していないか確認し、"
              "必要なら build_file_manifest.py --include で戻す:")
        for (d, rsn), n in by_dir.most_common(20):
            print(f"  {d}/ ({rsn}) {n}件")


if __name__ == "__main__":
    main()
