#!/usr/bin/env python3
"""抽出結果（extract/<slice>.json）を担当範囲ごとに自動検証する。

検証内容:
1. スキーマ（必須項目・確信度・local_id の形式。推定/不明には要確認事項が必須）
2. 根拠の実在: evidence / missing_entries / read_checks の path:line に quote が実際に書かれているか
   （空白差は無視。±2 行のずれは自動補正して警告、それ以上は不合格）
3. 高リスクの主張: actors と constraints は evidence の番号を必須にする。要約に制約表現
   （〜のみ・〜できない等）があるのに constraints が空なら不合格
4. エントリーポイントの対応付け: 担当範囲のエントリーポイントが全件 features か unmapped_entries（理由コード付き）に載っているか
5. 読了確認: 指示書が指定した全区間に、区間内の行の引用があるか（自己申告ではなく照合で読了を確かめる）
6. 鮮度と ID の安定: slice_hash が現在と一致するか。前回合格時と同じ local_id が、根拠の重ならない
   別の機能に使い回されていないか

結果は verify/<slice>.json に保存し、標準出力には要約だけを出す。1件でも不合格なら終了コード 1。

使い方:
    python3 verify_evidence.py --work W [--slice S1a2b3c ...]
    python3 verify_evidence.py --work W --review W/review/b1.json   # 独立検証の結果を検証
    python3 verify_evidence.py --work W --answers W/answers/q01.json  # 要確認事項への回答を検証
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import (ANSWER_STATUS, load_json, norm_question, norm_ws, question_id, read_lines,  # noqa: E402
                     save_json, work_paths)

CONF = {"confirmed", "inferred", "unknown"}
KINDS = {"http_endpoint", "ui_route", "cli_command", "scheduled_job", "background_job",
         "event_consumer", "webhook", "data_entity", "graphql_operation", "rpc_method", "other"}
UNMAPPED_CODES = {"health_check", "dev_tool", "ops_script", "test_support", "framework_internal",
                  "data_definition", "duplicate", "dead_code", "other"}
CONSTRAINT_WORDS = re.compile(r"のみ|だけが|だけ[がをに]|できない|不可|拒否|禁止|以外は|限る|限定")
MIN_QUOTE = 8
MAX_ATTEMPTS = 3


class Ctx:
    def __init__(self, work):
        self.wp = work_paths(work)
        m = load_json(self.wp["files"])
        self.repo = m["repo"]
        self.known = {f["path"] for f in m["files"]}
        self.entries = {e["id"] for e in load_json(self.wp["inventory"])["entries"]} \
            if os.path.exists(self.wp["inventory"]) else set()
        self._cache = {}

    def lines(self, path):
        if path not in self._cache:
            self._cache[path] = [norm_ws(l) for l in read_lines(self.repo, path)]
        return self._cache[path]


def check_quote(ctx, ev, where, errors, warnings, window=None):
    """ev の quote が path:line にあるか照合する。window=(start, end) なら行がその区間内であることも求める"""
    path, line, quote = ev.get("path"), ev.get("line"), ev.get("quote")
    if not isinstance(path, str) or not isinstance(line, int) or not isinstance(quote, str):
        errors.append(f"{where}: path(str) / line(int) / quote(str) が必要")
        return False
    q = norm_ws(quote)
    n_chars = len(q.replace(" ", ""))
    if n_chars < 4:
        errors.append(f"{where}: quote が短すぎる: {quote!r}")
        return False
    if path not in ctx.known:
        if not os.path.isfile(os.path.join(ctx.repo, path)):
            errors.append(f"{where}: ファイルが存在しない: {path}")
            return False
        warnings.append(f"{where}: 一覧外のファイルを根拠にしている: {path}")
    ls = ctx.lines(path)
    if not 1 <= line <= len(ls):
        errors.append(f"{where}: 行番号が範囲外: {path}:{line}（{len(ls)}行）")
        return False
    found = None
    if q in ls[line - 1]:
        found = line
    else:
        for d in (1, -1, 2, -2):
            n = line + d
            if 1 <= n <= len(ls) and q in ls[n - 1]:
                found = n
                warnings.append(f"{where}: 行がずれている {path}:{line} → 実際は {n}（自動補正）")
                ev["line"] = n
                break
    if found is None:
        errors.append(f"{where}: 引用が {path}:{line} 付近に見つからない（推測で書いていないか）: {quote[:80]!r}")
        return False
    # 短い引用は、行全体と一致する場合だけ認める（`return` のような断片で照合をすり抜けないように）
    if n_chars < MIN_QUOTE and q != ls[found - 1]:
        errors.append(f"{where}: quote が短すぎる（{MIN_QUOTE}文字以上の断片か、行全体を引用する）: {quote!r}")
        return False
    if window and not window[0] <= found <= window[1]:
        errors.append(f"{where}: 指定区間 L{window[0]}-{window[1]} の外の行を引用している（{found}行目）")
        return False
    return True


def check_index(ref, n, where, errors):
    if not isinstance(ref, int) or not 0 <= ref < n:
        errors.append(f"{where}: evidence の番号（0 始まり）が不正: {ref!r}")


def verify_slice(ctx, s, prev):
    errors, warnings = [], []
    path = os.path.join(ctx.wp["extract_dir"], f"{s['id']}.json")
    if not os.path.exists(path):
        return {"slice": s["id"], "ok": False, "missing": True, "errors": ["抽出結果が無い"], "warnings": []}
    try:
        d = load_json(path)
    except json.JSONDecodeError as e:
        return {"slice": s["id"], "ok": False, "errors": [f"JSON として読めない: {e}"], "warnings": []}

    if d.get("slice_id") != s["id"]:
        errors.append(f"slice_id が {s['id']} ではない: {d.get('slice_id')}")
    if d.get("slice_hash") != s["hash"]:
        errors.append(f"slice_hash が現在の担当範囲と一致しない（古い結果）: {d.get('slice_hash')} != {s['hash']}")
    slice_paths = {i["path"] for i in s["items"]}

    mapped, ids, id_paths = set(), set(), {}
    for k, f in enumerate(d.get("features") or []):
        lid = f.get("local_id", "")
        w = f"features[{k}]({lid or '?'})"
        if not re.fullmatch(re.escape(s["id"]) + r"-F\d+", lid):
            errors.append(f"{w}: local_id は '{s['id']}-F<番号>' 形式にする")
        if lid in ids:
            errors.append(f"{w}: local_id が重複")
        ids.add(lid)
        for key in ("name", "summary"):
            if not (isinstance(f.get(key), str) and f[key].strip()):
                errors.append(f"{w}: {key} が空")
        conf = f.get("confidence")
        if conf not in CONF:
            errors.append(f"{w}: confidence は {sorted(CONF)} のいずれか")
        if conf in ("inferred", "unknown") and not f.get("open_questions"):
            errors.append(f"{w}: confidence が {conf} なら、推定で補った点・断定できない点を open_questions に書く")
        for key in ("entry_ids", "data", "external", "open_questions", "actors", "constraints"):
            if key in f and not isinstance(f[key], list):
                errors.append(f"{w}: {key} は配列にする")
        oq = f.get("open_questions")
        for j, q in enumerate(oq if isinstance(oq, list) else []):
            if isinstance(q, str):
                warnings.append(f"{w}.open_questions[{j}]: 旧形式（文字列）。question と how_to_check に分けて書く")
            elif not isinstance(q, dict):
                errors.append(f"{w}.open_questions[{j}]: {{\"question\", \"how_to_check\"}} の形にする")
            else:
                for k in ("question", "how_to_check"):
                    if len(str(q.get(k) or "").strip()) < 8:
                        errors.append(f"{w}.open_questions[{j}].{k} が無いか短すぎる（何が未確認か・どう確かめるかを具体的に書く）")
        evs = f.get("evidence") or []
        if not evs:
            errors.append(f"{w}: evidence が無い（根拠の無い機能は書かない）")
        for j, ev in enumerate(evs):
            check_quote(ctx, ev, f"{w}.evidence[{j}]", errors, warnings)
            if isinstance(ev.get("path"), str) and ev["path"] not in slice_paths:
                warnings.append(f"{w}.evidence[{j}]: 担当範囲外のファイル {ev['path']}")
        id_paths[lid] = sorted({ev.get("path") for ev in evs if isinstance(ev.get("path"), str)})
        for j, a in enumerate(f.get("actors") or []):
            if not isinstance(a, dict) or not (a.get("name") or "").strip():
                errors.append(f"{w}.actors[{j}]: {{\"name\": ..., \"evidence\": 番号}} の形にする")
                continue
            check_index(a.get("evidence"), len(evs), f"{w}.actors[{j}]", errors)
        cons = f.get("constraints") or []
        for j, c in enumerate(cons):
            if not isinstance(c, dict) or not (c.get("text") or "").strip():
                errors.append(f"{w}.constraints[{j}]: {{\"text\": ..., \"evidence\": 番号}} の形にする")
                continue
            check_index(c.get("evidence"), len(evs), f"{w}.constraints[{j}]", errors)
        if not cons and isinstance(f.get("summary"), str) and CONSTRAINT_WORDS.search(f["summary"]):
            errors.append(f"{w}: 要約に制約（〜のみ・〜できない等）があるのに constraints が空。"
                          "制約ごとに根拠の番号を付けて constraints に書く")
        for eid in f.get("entry_ids") or []:
            if eid not in ctx.entries:
                errors.append(f"{w}: entry_ids に存在しないエントリーポイントID: {eid}")
            mapped.add(eid)

    # 前回合格時と同じ local_id が、根拠の重ならない別の機能に使い回されていないか
    for lid, paths in (prev or {}).get("id_paths", {}).items():
        if lid in id_paths and paths and id_paths[lid] and not set(paths) & set(id_paths[lid]):
            errors.append(f"{lid}: 前回と根拠ファイルが重ならない（番号の使い回し）。新しい機能には新しい番号を使う")

    for k, u in enumerate(d.get("unmapped_entries") or []):
        if u.get("entry_id") not in ctx.entries:
            errors.append(f"unmapped_entries[{k}]: 存在しないエントリーポイントID: {u.get('entry_id')}")
        if u.get("reason_code") not in UNMAPPED_CODES:
            errors.append(f"unmapped_entries[{k}]: reason_code は {sorted(UNMAPPED_CODES)} のいずれか")
        if len((u.get("reason") or "").strip()) < 8:
            errors.append(f"unmapped_entries[{k}]: reason に、なぜ機能でないかを具体的に書く")
        mapped.add(u.get("entry_id"))
    for k, m in enumerate(d.get("missing_entries") or []):
        check_quote(ctx, m, f"missing_entries[{k}]", errors, warnings)
        if m.get("kind") not in KINDS:
            errors.append(f"missing_entries[{k}]: kind は {sorted(KINDS)} のいずれか（該当が無ければ other）")
        if not m.get("label"):
            errors.append(f"missing_entries[{k}]: label が必要")

    for eid in s["entry_ids"]:
        if eid not in mapped:
            errors.append(f"エントリーポイントが未対応: {eid}（features.entry_ids か unmapped_entries に載せる）")

    # 読了確認: 指定区間ごとに、その区間内の行の引用が1件以上
    answers = d.get("read_checks") or []
    for c in s.get("read_checks", []):
        ok = False
        for j, ans in enumerate(answers):
            if ans.get("path") == c["path"] and isinstance(ans.get("line"), int) and c["start"] <= ans["line"] <= c["end"]:
                e2, w2 = [], []
                if check_quote(ctx, ans, f"read_checks[{j}]", e2, w2, window=(c["start"], c["end"])):
                    ok = True
                    break
                errors.extend(e2)
        if not ok:
            errors.append(f"読了確認が無い・不一致: {c['path']} L{c['start']}-{c['end']} から1行引用する")

    if any("自動補正" in w for w in warnings):
        save_json(path, d)
    attempts = (prev or {}).get("attempts", 0) + (1 if errors else 0)
    res = {"slice": s["id"], "ok": not errors, "errors": errors, "warnings": warnings,
           "features": len(d.get("features") or []), "attempts": attempts}
    res["id_paths"] = id_paths if not errors else (prev or {}).get("id_paths", {})
    return res


def verify_review(ctx, path):
    errors, warnings = [], []
    d = load_json(path)
    keys = set()
    if os.path.exists(ctx.wp["features"]):
        keys = {f["key"] for dm in load_json(ctx.wp["features"])["domains"] for f in dm["features"]}
    for k, r in enumerate(d.get("results") or []):
        w = f"results[{k}]({r.get('feature_key')})"
        if r.get("feature_key") not in keys:
            errors.append(f"{w}: features.json に無い feature_key（merge し直した後の古い対象ではないか）")
        if r.get("verdict") not in {"correct", "partially_correct", "incorrect", "unverifiable"}:
            errors.append(f"{w}: verdict が不正")
        for j, ev in enumerate(r.get("evidence") or []):
            check_quote(ctx, ev, f"{w}.evidence[{j}]", errors, warnings)
        if r.get("verdict") in {"partially_correct", "incorrect"} and not r.get("evidence"):
            errors.append(f"{w}: 誤りの指摘には evidence が必要")
    for k, r in enumerate(d.get("entry_results") or []):
        if r.get("verdict") not in {"correct", "should_be_feature", "unverifiable"}:
            errors.append(f"entry_results[{k}]: verdict が不正")
    return errors, warnings


def verify_answers(ctx, path):
    """要確認事項への回答を検証する。解消・一部解消・記述との矛盾には根拠の引用を必須にする"""
    errors, warnings = [], []
    d = load_json(path)
    qids = set()
    if os.path.exists(ctx.wp["features"]):
        for dm in load_json(ctx.wp["features"])["domains"]:
            for f in dm["features"]:
                for q in f.get("open_questions") or []:
                    qids.add(question_id(f["key"], norm_question(q)["question"]))
    for k, r in enumerate(d.get("answers") or []):
        w = f"answers[{k}]({r.get('question_id')})"
        if r.get("question_id") not in qids:
            errors.append(f"{w}: features.json に無い question_id（merge し直した後の古い対象ではないか）")
        st = r.get("status")
        if st not in ANSWER_STATUS:
            errors.append(f"{w}: status は {sorted(ANSWER_STATUS)} のいずれか")
        if len(str(r.get("answer") or "").strip()) < 8:
            errors.append(f"{w}: answer が無いか短すぎる（分かったこと・分からなかった理由を書く）")
        for j, ev in enumerate(r.get("evidence") or []):
            check_quote(ctx, ev, f"{w}.evidence[{j}]", errors, warnings)
        if (st in ("resolved", "partially_resolved") or r.get("contradicts_summary")) and not r.get("evidence"):
            errors.append(f"{w}: 解消・一部解消・記述との矛盾には evidence（根拠の引用）が必要")
    return errors, warnings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--slice", nargs="*")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--review")
    g.add_argument("--answers")
    a = ap.parse_args()
    ctx = Ctx(a.work)

    if a.review or a.answers:
        errors, warnings = verify_review(ctx, a.review) if a.review else verify_answers(ctx, a.answers)
        for w in warnings:
            print(f"警告: {w}")
        for e in errors:
            print(f"不合格: {e}")
        print("合格" if not errors else f"不合格 {len(errors)} 件")
        sys.exit(1 if errors else 0)

    slices = load_json(ctx.wp["slices"])["slices"]
    if a.slice:
        slices = [s for s in slices if s["id"] in set(a.slice)]
    passed, failed, missing, stuck = [], [], [], []
    for s in slices:
        vf = os.path.join(ctx.wp["verify_dir"], f"{s['id']}.json")
        prev = load_json(vf) if os.path.exists(vf) else None
        res = verify_slice(ctx, s, prev)
        save_json(vf, res)
        if res.get("missing"):
            missing.append(s["id"])
        elif res["ok"]:
            passed.append(s["id"])
        else:
            failed.append(res)
            if res["attempts"] >= MAX_ATTEMPTS:
                stuck.append(s["id"])
    print(f"合格 {len(passed)} / 不合格 {len(failed)} / 未抽出 {len(missing)}（担当範囲 {len(slices)} 件）")
    for r in failed:
        print(f"- {r['slice']}: エラー {len(r['errors'])} 件・不合格 {r['attempts']} 回目（先頭: {r['errors'][0]}）")
    if missing:
        print("未抽出: " + " ".join(missing))
    if stuck:
        print(f"※ {MAX_ATTEMPTS} 回以上不合格: {' '.join(stuck)} → エラー内容をユーザーに見せて判断を仰ぐ")
    sys.exit(0 if not failed and not missing else 1)


if __name__ == "__main__":
    main()
