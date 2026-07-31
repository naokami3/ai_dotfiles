#!/usr/bin/env python3
"""リポジトリ内ドキュメントのリンク・アンカー全数検証。

対象: 指定ルート配下の *.md / *.html / llms.txt。
検証: 相対リンクの解決（ファイル実在）と `#アンカー` の実在
（md は GitHub 互換の見出し→アンカー変換で、HTML は id 属性で照合）。

使い方:
    python3 check-doc-links.py <リポジトリルート> [--skip DIR]...

--skip は検査から除外するディレクトリ名（既定で .git / node_modules は除外。
生成前提のフラグメント置き場などを追加で除外するのに使う）。
リンク切れが 1 件でもあれば一覧を出力して非ゼロ終了する。
依存: python3 標準ライブラリのみ。
"""
import argparse
import os
import re
import sys
from html.parser import HTMLParser


def gh_anchor(heading):
    """GitHub 方式の見出し→アンカー変換（近似。unicode 文字は保持）"""
    s = heading.strip().lower()
    s = re.sub(r"[`*]", "", s)
    s = "".join(c for c in s if c.isalnum() or c in " -_")
    return s.replace(" ", "-")


def md_anchors(path):
    anchors = set()
    with open(path, encoding="utf-8") as f:
        in_code = False
        for line in f:
            if line.lstrip().startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                continue
            m = re.match(r"^(#{1,6})\s+(.+)$", line)
            if m:
                anchors.add(gh_anchor(m.group(2)))
    return anchors


class IdCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.links = []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if d.get("id"):
            self.ids.add(d["id"])
        if tag == "a" and d.get("href"):
            self.links.append(d["href"])


def html_ids_and_links(path):
    p = IdCollector()
    with open(path, encoding="utf-8") as f:
        p.feed(f.read())
    return p.ids, p.links


def md_links(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    text = re.sub(r"```.*?```", "", text, flags=re.S)  # コードブロックを除外
    return [m.group(1) for m in re.finditer(r"\[[^\]]*\]\(([^)\s]+)\)", text)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--skip", action="append", default=[],
                    help="除外するディレクトリ名（複数指定可）")
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    skip = {".git", "node_modules"} | set(args.skip)

    targets = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for fn in filenames:
            if fn.endswith(".md") or fn.endswith(".html") or fn == "llms.txt":
                targets.append(os.path.join(dirpath, fn))

    errors = []
    checked = 0
    for path in sorted(targets):
        base = os.path.dirname(path)
        rel = os.path.relpath(path, root)
        if path.endswith(".html"):
            own_ids, links = html_ids_and_links(path)
        else:
            own_ids, links = None, md_links(path)
        for link in links:
            if re.match(r"^(https?:|mailto:)", link):
                continue
            checked += 1
            target, frag = (link.split("#", 1) if "#" in link else (link, None))
            if target == "":
                # ページ内アンカー
                if own_ids is not None:
                    if frag not in own_ids:
                        errors.append(f"{rel}: ページ内アンカー #{frag} が無い")
                elif frag and gh_anchor(frag) not in md_anchors(path):
                    errors.append(f"{rel}: ページ内アンカー #{frag} が無い")
                continue
            dest = os.path.normpath(os.path.join(base, target))
            if not os.path.exists(dest):
                errors.append(f"{rel}: リンク切れ {link}")
                continue
            if frag and dest.endswith(".md"):
                if frag not in md_anchors(dest):
                    errors.append(f"{rel}: {target}#{frag} のアンカーが無い")
            if frag and dest.endswith(".html"):
                ids, _ = html_ids_and_links(dest)
                if frag not in ids:
                    errors.append(f"{rel}: {target}#{frag} の id が無い")

    print(f"検査対象 {len(targets)} ファイル / 相対リンク {checked} 件")
    if errors:
        print(f"NG {len(errors)} 件:")
        for e in errors:
            print("  " + e)
        sys.exit(1)
    print("全リンク OK")


main()
