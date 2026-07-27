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
