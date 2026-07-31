#!/usr/bin/env python3
"""Exhaustive link/anchor checker for repository documentation.

Targets: *.md / *.html / llms.txt under the given root.
Checks: relative link resolution (file existence) and `#anchor` targets
(md anchors via GitHub-compatible heading slugs; HTML anchors via id attributes).

Usage:
    python3 check-doc-links.py <repo root> [--skip DIR]...

--skip excludes directory names from the walk (.git and node_modules are always
excluded; use it for e.g. fragment directories that only resolve after injection).
Exits non-zero with a listing if any link is broken.
Dependencies: Python 3 standard library only.
"""
import argparse
import os
import re
import sys
from html.parser import HTMLParser


def gh_anchor(heading):
    """GitHub-style heading-to-anchor conversion (approximate; keeps unicode)."""
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
    text = re.sub(r"```.*?```", "", text, flags=re.S)  # strip code blocks
    return [m.group(1) for m in re.finditer(r"\[[^\]]*\]\(([^)\s]+)\)", text)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--skip", action="append", default=[],
                    help="directory names to exclude (repeatable)")
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
                # in-page anchor
                if own_ids is not None:
                    if frag not in own_ids:
                        errors.append(f"{rel}: in-page anchor #{frag} not found")
                elif frag and gh_anchor(frag) not in md_anchors(path):
                    errors.append(f"{rel}: in-page anchor #{frag} not found")
                continue
            dest = os.path.normpath(os.path.join(base, target))
            if not os.path.exists(dest):
                errors.append(f"{rel}: broken link {link}")
                continue
            if frag and dest.endswith(".md"):
                if frag not in md_anchors(dest):
                    errors.append(f"{rel}: anchor {target}#{frag} not found")
            if frag and dest.endswith(".html"):
                ids, _ = html_ids_and_links(dest)
                if frag not in ids:
                    errors.append(f"{rel}: id {target}#{frag} not found")

    print(f"scanned {len(targets)} files / {checked} relative links")
    if errors:
        print(f"{len(errors)} problem(s):")
        for e in errors:
            print("  " + e)
        sys.exit(1)
    print("all links OK")


main()
