"""analyze.py のテスト。標準ライブラリのみで動く。

実行:
    python3 -m unittest discover -s tools/session-usage/tests
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import analyze  # noqa: E402


def rec(
    model="claude-opus-5",
    uuid: str | None = "u1",
    request_id: str | None = "r1",
    inp=0,
    cache_read=1000,
    cache_write=0,
    out=100,
    tools=None,
    is_sidechain=False,
    rec_type="assistant",
):
    """usage を持つアシスタントレコードを組み立てる。"""
    content = [{"type": "text", "text": "hello"}]
    if tools:
        content = [{"type": "tool_use", "name": name, "input": {}} for name in tools]
    record = {
        "type": rec_type,
        "isSidechain": is_sidechain,
        "message": {
            "model": model,
            "content": content,
            "usage": {
                "input_tokens": inp,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_write,
                "output_tokens": out,
            },
        },
    }
    if uuid is not None:
        record["uuid"] = uuid
    if request_id is not None:
        record["requestId"] = request_id
    return record


def write_session(dirpath, project, session, records, raw_lines=()):
    """<dirpath>/<project>/<session>.jsonl を作って絶対パスを返す。"""
    project_dir = os.path.join(dirpath, project)
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, f"{session}.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        for line in raw_lines:
            f.write(line + "\n")
    return path


class TempSessionRoot(unittest.TestCase):
    """一時ディレクトリをセッション記録のルートとして使う土台。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def run_main(self, *argv):
        """main() を実行して標準出力を返す。"""
        old = sys.argv
        sys.argv = ["analyze.py", "--root", self.root, *argv]
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                analyze.main()
        finally:
            sys.argv = old
        return buf.getvalue()


class TestDeduplication(TempSessionRoot):
    def test_同一uuidの重複を1回だけ数える(self):
        path = write_session(
            self.root,
            "proj",
            "aaaaaaaa",
            [
                rec(uuid="same", request_id="r1"),
                rec(uuid="same", request_id="r2"),
            ],
        )
        self.assertEqual(len(analyze.parse_session(path)["turns"]), 1)

    def test_同一requestIdの重複を1回だけ数える(self):
        path = write_session(
            self.root,
            "proj",
            "aaaaaaaa",
            [
                rec(uuid="u1", request_id="same"),
                rec(uuid="u2", request_id="same"),
                rec(uuid="u3", request_id="same"),
            ],
        )
        self.assertEqual(len(analyze.parse_session(path)["turns"]), 1)

    def test_uuid欠損レコードを複数件保持する(self):
        path = write_session(
            self.root,
            "proj",
            "aaaaaaaa",
            [
                rec(uuid=None, request_id="r1"),
                rec(uuid=None, request_id="r2"),
                rec(uuid=None, request_id="r3"),
            ],
        )
        result = analyze.parse_session(path)
        self.assertEqual(len(result["turns"]), 3)
        self.assertEqual(result["no_id_records"], 0)

    def test_requestId欠損でもuuidで処理できる(self):
        path = write_session(
            self.root,
            "proj",
            "aaaaaaaa",
            [
                rec(uuid="u1", request_id=None),
                rec(uuid="u2", request_id=None),
                rec(uuid="u1", request_id=None),  # 重複
            ],
        )
        result = analyze.parse_session(path)
        self.assertEqual(len(result["turns"]), 2)
        self.assertEqual(result["no_id_records"], 0)

    def test_両方欠損したレコードは残して数える(self):
        path = write_session(
            self.root,
            "proj",
            "aaaaaaaa",
            [rec(uuid=None, request_id=None), rec(uuid=None, request_id=None)],
        )
        result = analyze.parse_session(path)
        self.assertEqual(len(result["turns"]), 2)
        self.assertEqual(result["no_id_records"], 2)

    def test_壊れたJSON行を読み飛ばす(self):
        path = write_session(
            self.root,
            "proj",
            "aaaaaaaa",
            [rec(uuid="u1", request_id="r1")],
            raw_lines=["{壊れた", "", "not json at all"],
        )
        self.assertEqual(len(analyze.parse_session(path)["turns"]), 1)


class TestPricing(TempSessionRoot):
    def test_登録済みモデルの単価が正しい(self):
        self.assertEqual(analyze.model_price("claude-opus-5"), (5.0, 25.0))
        self.assertEqual(analyze.model_price("claude-opus-4-8"), (5.0, 25.0))
        self.assertEqual(analyze.model_price("claude-fable-5"), (10.0, 50.0))
        self.assertEqual(analyze.model_price("claude-sonnet-5"), (3.0, 15.0))
        self.assertEqual(analyze.model_price("claude-haiku-4-5"), (1.0, 5.0))

    def test_日付サフィックス付きのモデル名も前方一致で引ける(self):
        self.assertEqual(analyze.model_price("claude-haiku-4-5-20251001"), (1.0, 5.0))

    def test_価格帯名の部分一致では引かない(self):
        # 旧実装は "opus" の部分一致で単価を引いていたため、単価が異なる
        # 世代のモデルを黙って誤った単価で計算していた。
        self.assertIsNone(analyze.model_price("claude-opus-4-1"))

    def test_未登録モデルはコストに加算しない(self):
        turns = [
            {
                "model": "claude-unknown-9",
                "input": 0,
                "cache_read": 1_000_000,
                "cache_write": 0,
                "output": 1_000_000,
                "is_impl": False,
                "is_sub": False,
            }
        ]
        self.assertEqual(analyze.session_cost(turns), 0.0)

    def test_実測コストがモデル別単価で計算される(self):
        turns = [
            {
                "model": "claude-opus-5",
                "input": 0,
                "cache_read": 1_000_000,
                "cache_write": 0,
                "output": 1_000_000,
                "is_impl": False,
                "is_sub": False,
            }
        ]
        # キャッシュ読み込み 1M * $5 * 0.10 + 出力 1M * $25
        self.assertAlmostEqual(analyze.session_cost(turns), 0.5 + 25.0, places=6)


class TestWarnings(TempSessionRoot):
    def test_未知モデルを未計上として警告する(self):
        write_session(
            self.root,
            "proj",
            "aaaaaaaa",
            [
                rec(model="claude-opus-5", uuid="u1", request_id="r1"),
                rec(model="claude-mystery-7", uuid="u2", request_id="r2", out=42),
            ],
        )
        out = self.run_main()
        self.assertIn("価格未登録", out)
        self.assertIn("claude-mystery-7", out)

    def test_syntheticは未計上警告に含めない(self):
        write_session(
            self.root,
            "proj",
            "aaaaaaaa",
            [
                rec(model="claude-opus-5", uuid="u1", request_id="r1"),
                rec(model="<synthetic>", uuid="u2", request_id="r2", cache_read=0, out=0),
            ],
        )
        out = self.run_main()
        self.assertNotIn("価格未登録", out)
        self.assertNotIn("<synthetic>", out)


class TestSubMetric(TempSessionRoot):
    def test_sub列がサイドチェーンの課金ターン数になる(self):
        write_session(
            self.root,
            "proj",
            "aaaaaaaa",
            [
                rec(uuid="u1", request_id="r1", is_sidechain=False),
                rec(uuid="u2", request_id="r2", is_sidechain=True),
                rec(uuid="u3", request_id="r3", is_sidechain=True),
            ],
        )
        out = self.run_main()
        # プロジェクト / session / ターン数3 / sub数2
        row = next(line for line in out.splitlines() if line.startswith("proj "))
        self.assertEqual(row.split()[2:4], ["3", "2"])


class TestSimulation(TempSessionRoot):
    def _params(self, **overrides) -> dict[str, Any]:
        params: dict[str, Any] = {
            name.replace("-", "_"): default for name, (default, _, _) in analyze.SIM_PARAMS.items()
        }
        params.update(overrides)
        return params

    def _turn(self, ctx, is_sub=False, is_impl=False, out=100):
        return {
            "model": "claude-opus-5",
            "input": 0,
            "cache_read": ctx,
            "cache_write": 0,
            "output": out,
            "is_impl": is_impl,
            "is_sub": is_sub,
        }

    def test_simulationが既存サイドチェーンを除外する(self):
        main_only = [self._turn(1000), self._turn(2000)]
        with_side = [self._turn(1000), self._turn(9_000_000, is_sub=True), self._turn(2000)]
        params = self._params()
        a = analyze.simulate_split(main_only, params)
        b = analyze.simulate_split(with_side, params)
        self.assertEqual(b["skipped_sub_turns"], 1)
        self.assertEqual(b["main_turns"], 2)
        self.assertAlmostEqual(a["scenario_base"], b["scenario_base"], places=9)
        self.assertAlmostEqual(a["scenario_split"], b["scenario_split"], places=9)

    def test_mainとsideのコンテキスト増分が混ざらない(self):
        # サイドチェーンが巨大なコンテキストを挟むと、旧実装では prev_ctx が
        # 引き上げられ、後続の主系列ターンの増分が 0 に潰れていた。
        params = self._params()
        turns = [
            self._turn(1000),
            self._turn(5_000_000, is_sub=True),
            self._turn(2000, is_impl=True),
        ]
        result = analyze.simulate_split(turns, params)
        # 主系列だけで見れば 2番目の実装ターンの増分は 2000-1000=1000
        expected_sub_ctx = params["sub_initial_context"] + 1000
        expected_sub_cost = analyze.cost(
            analyze.PRICE[params["delegate_model"]], 0, expected_sub_ctx, 0, 100
        )
        self.assertAlmostEqual(result["sub"], expected_sub_cost, places=9)

    def test_実測額と比較基準額を別々に表示する(self):
        write_session(
            self.root,
            "proj",
            "aaaaaaaa",
            [
                rec(uuid=f"u{i}", request_id=f"r{i}", cache_read=10_000, cache_write=5_000)
                for i in range(12)
            ],
        )
        out = self.run_main("--simulate", "--min-turns", "1")
        self.assertIn("実測$", out)
        self.assertIn("比較基準$", out)
        self.assertIn("委譲案$", out)
        # キャッシュ書き込みを含む実測額と、全キャッシュ読み込み近似の
        # 比較基準額は一致しない
        row = next(line for line in out.splitlines() if "proj/aaaaaaaa" in line)
        observed, base = row.split()[3], row.split()[4]
        self.assertNotEqual(observed, base)

    def test_レビューターン数をCLIで上書きできる(self):
        params_10 = self._params(review_turns=10)
        params_5 = self._params(review_turns=5)
        turns = [self._turn(1000)]
        self.assertGreater(
            analyze.simulate_split(turns, params_10)["review"],
            analyze.simulate_split(turns, params_5)["review"],
        )


class TestProjectFilter(TempSessionRoot):
    def test_プロジェクト名だけを部分一致検索する(self):
        write_session(self.root, "-Users-someone-Works-xrev", "aaaaaaaa", [rec()])
        write_session(self.root, "-Users-someone-Works-other", "bbbbbbbb", [rec()])

        out = self.run_main("-p", "xrev")
        self.assertIn("aaaaaaaa", out)
        self.assertNotIn("bbbbbbbb", out)

        # ルートパスやセッションIDには一致させない
        leaf = os.path.basename(self.root)
        out = self.run_main("-p", leaf)
        self.assertIn("一致するプロジェクトがありません", out)


class TestEmptyInput(TempSessionRoot):
    def test_課金対象ターンがない場合の表示(self):
        write_session(
            self.root,
            "proj",
            "aaaaaaaa",
            [{"type": "user", "uuid": "u1", "message": {"content": "hi"}}],
        )
        out = self.run_main()
        self.assertIn("課金対象のターンを含むセッションがありません", out)

    def test_記録が1件も無い場合の表示(self):
        out = self.run_main()
        self.assertIn("セッション記録が見つかりません", out)


if __name__ == "__main__":
    unittest.main()


# --- タスク別の時間とトークン ---------------------------------------------

def ts(seconds: int) -> str:
    """2026-01-01T00:00:00Z から seconds 秒後のタイムスタンプ。"""
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"2026-01-01T{h:02d}:{m:02d}:{s:02d}.000Z"


def prompt(at: int, text="やって"):
    return {"type": "user", "timestamp": ts(at), "uuid": f"p{at}",
            "message": {"content": [{"type": "text", "text": text}]}}


def assistant(at: int, request_id="r1", tool_uses=(), out=100, model="claude-opus-5",
              cache_read=1000, with_usage=True, is_sidechain=False, uuid=None):
    """tool_uses は (id, name, input) の列。"""
    content: list[Any] = [{"type": "text", "text": "ok"}]
    if tool_uses:
        content = [
            {"type": "tool_use", "id": tid, "name": name, "input": inp}
            for tid, name, inp in tool_uses
        ]
    message: dict[str, Any] = {"model": model, "content": content}
    if with_usage:
        message["usage"] = {
            "input_tokens": 0,
            "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": 0,
            "output_tokens": out,
        }
    return {"type": "assistant", "timestamp": ts(at), "uuid": uuid or f"a{at}",
            "requestId": request_id, "isSidechain": is_sidechain, "message": message}


def tool_result(at: int, *tool_ids):
    return {"type": "user", "timestamp": ts(at), "uuid": f"t{at}",
            "message": {"content": [{"type": "tool_result", "tool_use_id": i} for i in tool_ids]}}


def bash(tid: str, command: str):
    return (tid, "Bash", {"command": command})


class TestBashClassification(unittest.TestCase):
    def test_実行位置のコマンドで分類する(self):
        self.assertEqual(analyze.classify_bash("pytest tests/"), "テスト実行")
        self.assertEqual(analyze.classify_bash("rubocop -a"), "lint実行")
        self.assertEqual(analyze.classify_bash("git status"), "バージョン管理")

    def test_先頭のcdや環境変数代入を剥がす(self):
        self.assertEqual(analyze.classify_bash("cd /tmp && pytest"), "テスト実行")
        self.assertEqual(analyze.classify_bash("RAILS_ENV=test bundle exec rspec"), "テスト実行")
        self.assertEqual(analyze.classify_bash("time npm run test"), "テスト実行")

    def test_引用やコメントの中のコマンド名で誤検出しない(self):
        # 引用の中の pytest / ファイル名の rubocop を実行と見なさない。
        # ls と wc 自体は中身を見るコマンドなので調査(コード)になる
        self.assertEqual(analyze.classify_bash('echo "pytest を実行する"'), "その他")
        self.assertEqual(analyze.classify_bash("ls test_analyze.py"), "調査(コード)")
        self.assertEqual(analyze.classify_bash("wc -l rubocop.md"), "調査(コード)")

    def test_ヒアドキュメント本文を無視する(self):
        # 本文中の pytest を実行と見なさない（cat 自体は調査(コード)）
        command = "cat > note.md <<'EOF'\npytest を後で実行する\nEOF"
        self.assertEqual(analyze.classify_bash(command), "調査(コード)")

    def test_限定文法で扱えない構文は解析不能にする(self):
        self.assertEqual(analyze.classify_bash("echo $(pytest --version)"), "解析不能")
        self.assertEqual(analyze.classify_bash("bash -c 'pytest'"), "解析不能")
        self.assertEqual(analyze.classify_bash("for f in *.py; do ruff $f; done"), "解析不能")

    def test_優先順位で1つに寄せる(self):
        self.assertEqual(analyze.classify_bash("rubocop && rspec"), "テスト実行")


class TestTaskTimeline(TempSessionRoot):
    def analyze(self, records):
        path = write_session(self.root, "proj", "aaaaaaaa", records)
        return analyze.analyze_tasks(analyze.parse_session(path))

    def test_生成とツール待ちを重複なく分ける(self):
        report = self.analyze([
            prompt(0),
            assistant(10, tool_uses=[bash("t1", "pytest")]),
            tool_result(40, "t1"),
            assistant(45, request_id="r2"),
        ])
        main_test = report["categories"][(False, "テスト実行")]
        self.assertEqual(main_test["gen"], 10)     # prompt -> assistant
        self.assertEqual(main_test["wait"], 30)    # assistant -> tool_result
        self.assertEqual(report["categories"][(False, "相談")]["gen"], 5)
        self.assertEqual(report["unexplained"], 0)

    def test_並列ツールの後続区間もツール待ちにする(self):
        report = self.analyze([
            prompt(0),
            assistant(10, tool_uses=[bash("t1", "pytest"), bash("t2", "pytest -k x")]),
            tool_result(20, "t1"),
            tool_result(50, "t2"),
        ])
        # 10->20 と 20->50 の両方がツール待ち。過小計上しない
        self.assertEqual(report["categories"][(False, "テスト実行")]["wait"], 40)
        self.assertEqual(report["unexplained"], 0)

    def test_ユーザー確認待ちをツール待ちに混ぜない(self):
        report = self.analyze([
            prompt(0),
            assistant(10, tool_uses=[("t1", "AskUserQuestion", {})]),
            tool_result(600, "t1"),
        ])
        # 生成時間は計上するが、応答待ちは計測しない（トークンを消費しないため）
        self.assertEqual(report["categories"][(False, "ユーザー確認")]["gen"], 10)
        self.assertEqual(report["categories"][(False, "ユーザー確認")]["wait"], 0)

    def test_未完了のtool_useは時間に計上せず警告する(self):
        report = self.analyze([
            prompt(0),
            assistant(10, tool_uses=[bash("t1", "pytest")]),
            prompt(3600),
            assistant(3610, request_id="r2"),
        ])
        self.assertEqual(report["unfinished"], 1)
        # 離席時間はツール待ちへ流れ込まない
        self.assertEqual(report["categories"][(False, "テスト実行")]["wait"], 0)

    def test_timestampの逆転を0に丸めて数える(self):
        report = self.analyze([prompt(30), assistant(10)])
        self.assertEqual(report["negative_gaps"], 1)
        self.assertEqual(report["categories"][(False, "相談")]["gen"], 0)

    def test_同一requestIdが分散しても分類できる(self):
        report = self.analyze([
            prompt(0),
            assistant(10, request_id="r1", tool_uses=[], with_usage=True, uuid="a1"),
            assistant(12, request_id="r1", tool_uses=[bash("t1", "rubocop")], with_usage=False, uuid="a2"),
            tool_result(20, "t1"),
        ])
        self.assertIn((False, "lint実行"), report["categories"])

    def test_サブエージェントを系列で分ける(self):
        report = self.analyze([
            prompt(0),
            assistant(10, request_id="r1"),
            assistant(20, request_id="r2", is_sidechain=True),
        ])
        self.assertIn((False, "相談"), report["categories"])
        self.assertIn((True, "相談"), report["categories"])

    def test_孤児のtool_resultを数える(self):
        report = self.analyze([prompt(0), assistant(10), tool_result(20, "missing")])
        self.assertEqual(report["orphan_results"], 1)

    def test_turn_durationと突合する(self):
        report = self.analyze([
            prompt(0),
            assistant(30),
            {"type": "system", "subtype": "turn_duration", "durationMs": 30000, "timestamp": ts(31)},
        ])
        self.assertEqual(report["verify"]["matched"], 1)
        self.assertLess(report["verify"]["max_abs"], 0.001)

    def test_入力増分はモデル切替や圧縮で推定しない(self):
        report = self.analyze([
            prompt(0),
            assistant(10, request_id="r1", cache_read=1000),
            assistant(20, request_id="r2", cache_read=3000),
            assistant(30, request_id="r3", cache_read=500),
        ])
        # 初回と減少（圧縮）の2件が推定不能
        self.assertEqual(report["unknown_deltas"], 2)
        self.assertEqual(report["categories"][(False, "相談")]["delta"], 2000)


class TestTasksOutput(TempSessionRoot):
    def test_tasksとsimulateを同時に指定しても壊れない(self):
        write_session(self.root, "proj", "aaaaaaaa", [
            prompt(0),
            assistant(10, tool_uses=[bash("t1", "pytest")]),
            tool_result(20, "t1"),
        ] + [rec(uuid=f"u{i}", request_id=f"rr{i}") for i in range(12)])
        out = self.run_main("--tasks", "--simulate")
        self.assertIn("タスク別の時間とトークン", out)
        self.assertIn("分担した場合の試算", out)


class TestTaskEdgeCases(TempSessionRoot):
    def analyze(self, records):
        path = write_session(self.root, "proj", "aaaaaaaa", records)
        return analyze.analyze_tasks(analyze.parse_session(path))

    def test_systemレコードは区間を分断しない(self):
        # system が user と assistant の間に入っても生成時間を取りこぼさない
        report = self.analyze([
            prompt(0),
            {"type": "system", "subtype": "other", "timestamp": ts(5), "uuid": "s1"},
            assistant(10),
        ])
        self.assertEqual(report["categories"][(False, "相談")]["gen"], 10)
        self.assertEqual(report["unexplained"], 0)

    def test_逆転を含むターンは検算から除外する(self):
        report = self.analyze([
            prompt(0),
            assistant(30, request_id="r1"),
            assistant(20, request_id="r2"),
            {"type": "system", "subtype": "turn_duration", "durationMs": 30000, "timestamp": ts(40)},
        ])
        self.assertEqual(report["negative_gaps"], 1)
        self.assertEqual(report["verify"]["matched"], 0)
        self.assertEqual(report["verify"]["skipped"], 1)

    def test_ユーザー確認待ちを含むターンも検算から除外する(self):
        report = self.analyze([
            prompt(0),
            assistant(10, tool_uses=[("t1", "AskUserQuestion", {})]),
            tool_result(600, "t1"),
            {"type": "system", "subtype": "turn_duration", "durationMs": 20000, "timestamp": ts(601)},
        ])
        self.assertEqual(report["verify"]["skipped"], 1)

    def test_ツール結果が同一レコードに複数あっても取りこぼさない(self):
        report = self.analyze([
            prompt(0),
            assistant(10, tool_uses=[bash("t1", "rubocop"), bash("t2", "rubocop -a")]),
            tool_result(30, "t1", "t2"),
        ])
        self.assertEqual(report["categories"][(False, "lint実行")]["wait"], 20)
        self.assertEqual(report["unfinished"], 0)


class TestScriptClassification(unittest.TestCase):
    def test_言語名つきで分類する(self):
        self.assertEqual(analyze.classify_bash("python3 analyze.py"), "スクリプト実行(Python)")
        self.assertEqual(analyze.classify_bash("ruby -e 'puts 1'"), "スクリプト実行(Ruby)")
        self.assertEqual(analyze.classify_bash("node build.js"), "スクリプト実行(Node)")
        self.assertEqual(analyze.classify_bash("cd /tmp && bash setup.sh"), "スクリプト実行(Shell)")

    def test_テスト実行の方が優先される(self):
        self.assertEqual(analyze.classify_bash("python3 -m pytest"), "テスト実行")

    def test_優先順位表を言語名つきでも引ける(self):
        self.assertEqual(
            analyze.category_rank("スクリプト実行(Python)"),
            analyze.CATEGORY_PRIORITY.index("スクリプト実行"),
        )

    def test_中身を見るコマンドは調査に寄せる(self):
        self.assertEqual(analyze.classify_bash("cat README.md"), "調査(コード)")
        self.assertEqual(analyze.classify_bash("ls -la app/"), "調査(コード)")
        self.assertEqual(analyze.classify_bash("grep -rn TODO src/"), "調査(コード)")
        self.assertEqual(analyze.classify_bash("find . -name '*.py' | wc -l"), "調査(コード)")

    def test_調査より実行系を優先する(self):
        self.assertEqual(analyze.classify_bash("cat setup.cfg && pytest"), "テスト実行")
        self.assertEqual(analyze.classify_bash("ls && python3 build.py"), "スクリプト実行(Python)")
