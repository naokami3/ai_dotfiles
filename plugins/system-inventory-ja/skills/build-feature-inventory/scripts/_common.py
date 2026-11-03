"""build-feature-inventory の各スクリプトが共有する小さなユーティリティ。

依存: python3 標準ライブラリのみ。
"""
import hashlib
import json
import os
import re
import sys

# Windows のパイプ出力で日本語が化けないようにする
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


def glob_to_regex(glob):
    """`**` / `*` / `?` / `{a,b}` をサポートするパス用 glob → 正規表現。

    `**/` は 0 個以上のディレクトリ、`*` は `/` を跨がない任意文字列。
    """
    i, out = 0, ["^"]
    while i < len(glob):
        c = glob[i]
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "{":
            j = glob.find("}", i)
            if j == -1:
                out.append(re.escape(c))
                i += 1
            else:
                alts = glob[i + 1:j].split(",")
                out.append("(?:" + "|".join(re.escape(a) for a in alts) + ")")
                i = j + 1
        else:
            out.append(re.escape(c))
            i += 1
    out.append("$")
    return re.compile("".join(out))


class GlobSet:
    def __init__(self, globs):
        self.globs = list(globs or [])
        self._res = [glob_to_regex(g) for g in self.globs]

    def match(self, path):
        return any(r.match(path) for r in self._res)

    def __bool__(self):
        return bool(self._res)


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")


def read_text(repo, path):
    with open(os.path.join(repo, path), "rb") as f:
        raw = f.read()
    return raw.decode("utf-8", errors="replace")


def read_lines(repo, path):
    return read_text(repo, path).splitlines()


def sha1_bytes(data):
    return hashlib.sha1(data).hexdigest()


def norm_ws(s):
    """空白の差（インデント・連続空白）を無視して比較するための正規化"""
    return re.sub(r"\s+", " ", s).strip()


def work_paths(work):
    return {
        "files": os.path.join(work, "files.json"),
        "inventory": os.path.join(work, "inventory.json"),
        "slices": os.path.join(work, "slices.json"),
        "extract_dir": os.path.join(work, "extract"),
        "verify_dir": os.path.join(work, "verify"),
        "review_dir": os.path.join(work, "review"),
        "coverage": os.path.join(work, "coverage.json"),
        "features": os.path.join(work, "features.json"),
    }


def die(msg, code=2):
    print(f"エラー: {msg}", file=sys.stderr)
    sys.exit(code)


# 言語非依存のアウトライン抽出: 定義・テストケース・ルート宣言らしき行だけを拾う。
# 完全な構文解析ではない。テストファイルの「何をテストしているか」を安く読むための近似。
OUTLINE_RE = re.compile(
    r"""^\s*(?:
        (?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function|class|interface|enum|type)\b
      | (?:async\s+)?def\s
      | class\s
      | func\s
      | (?:pub\s+)?(?:fn|struct|trait|impl|mod)\s
      | (?:public|private|protected|internal|static|override|abstract)\b[^;=]*\(
      | @[\w.]+
      | (?:describe|context|it|test|scenario|feature|specify)(?:\.\w+)?\s*\(
      | (?:describe|context|it|test|scenario|feature|specify)\s+['"]
      | (?:export\s+)?const\s+\w+\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>
      | module\s
    )""",
    re.VERBOSE,
)


def outline_lines(lines):
    """(行番号, 行テキスト) のリストを返す（行番号は 1 始まり）"""
    return [(i + 1, l.rstrip()) for i, l in enumerate(lines) if OUTLINE_RE.match(l)]
