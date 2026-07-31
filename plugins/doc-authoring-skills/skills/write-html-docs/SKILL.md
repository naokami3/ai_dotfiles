---
name: write-html-docs
description: >
  Create human-facing HTML documentation (diagram-rich overviews, rendered detailed specs)
  from canonical Markdown. Defines the two-tier model (humans read HTML / agents read md)
  and the requirements for generators, diagrams, and verification.
  html documentation / spec rendering / diagrams / two-tier docs.
  TRIGGER when: creating or updating human-facing HTML documents (overview pages,
  HTML renderings of detailed specs, diagrams) — e.g. "I want readable HTML docs",
  "I want diagrams that explain this".
  DO NOT TRIGGER when: Markdown-only documentation (use write-project-docs), ADRs
  (write-adr), agent instruction files (write-agent-instructions).
  HTML docs are an optional deliverable; skip them when Markdown alone is enough.
---

# Human-Facing HTML Documentation Guide

## Related Skills

| Target | Skill |
|---|---|
| Human-facing HTML docs (overview, detailed specs, diagrams) | `write-html-docs` (this skill) |
| architecture.md / roadmap.md and other docs/ content (md) | `write-project-docs` |
| Technical decision records | `write-adr` |
| AGENTS.md / CLAUDE.md | `write-agent-instructions` |
| Verification after authoring | `review-docs` |

## Premise: the Two-Tier Model

When you build HTML docs, structure the documentation in **two tiers**.

- **The canon is always Markdown (agent-facing).** Primary facts, contracts, and specs live in md.
- **HTML is a human-facing rendering.** HTML versions of detailed specs are **generated** from md;
  never hand-maintain both (hand-written copies always drift).
- Hand-written HTML is allowed only for **diagram-centric explainer pages** (overviews, comparison
  diagrams, flow diagrams — pages with no md canon of their own). Even then, link to md for factual
  detail instead of duplicating it.
- State the split ("humans read HTML / agents read md") in `llms.txt`.
- If HTML and md disagree, the canon (md) wins. Put a footer on HTML pages saying so.

## Deliverable Layout

```
docs/
├── overview.html   # Diagram-rich overview (hand-written OK). Big picture + link hub
├── <topic>.html    # Diagram-centric explainer pages (hand-written OK, if needed)
└── spec/           # HTML rendering of detailed specs (generated from md canon; never hand-edit)
    ├── index.html  # Table of contents + suggested reading order
    └── <topic>.html
```

Every generated page must carry a note — "generated from <canon path>; edit the md and
regenerate" — plus a direct link to its md canon.

## Requirements for a Home-Grown Generator (fail-closed checklist)

Write it with the repository's existing runtime (e.g. Python 3 standard library); add no external
dependencies. A generator that misses any of these silently emits broken or dangerous HTML.

- [ ] **Limit supported md syntax to what an inventory of the target files actually uses**
      (don't implement constructs that never appear)
- [ ] Never pass through input you can't handle: **list the errors and exit non-zero**. Make the
      conditions machine-checkable (e.g. unclosed fence / missing table separator / unclosed link
      parenthesis / disallowed constructs present)
- [ ] **Context-aware escaping**: text nodes (`& < >`) / attribute values (plus quotes) / code
      (no inline-syntax interpretation). Tokenize first, escape each piece, so double-escaping is
      structurally impossible
- [ ] **href allowlist**: only scheme-less relative paths and `https://`. Reject dangerous schemes
      (`javascript:` etc.), `http:`, scheme-relative (`//`), absolute paths, backslashes, and any
      path that escapes the repository after normalization
- [ ] Generate **GitHub-compatible heading anchor ids** (so `#anchor` links from md still work in HTML)
- [ ] Have explicit **link-rewriting rules** (recompute relative paths from the output directory;
      links between generated pages become .html)
- [ ] Output must be **deterministic** (no timestamps or randomness; identical input → byte-identical output)
- [ ] **Write unit tests alongside it** (each construct, escaping, href-rejection attack cases,
      fail conditions, determinism)

## Keeping Generated Output in Sync (prevent drift structurally)

- Commit the generated HTML (don't force viewers to build).
- Add a **non-mutating freshness check** to the verification gate (pre-commit / CI / verify script):
  regenerate into a temporary directory (mktemp) and compare against the committed output with a
  file-set check plus `cmp`. **The check must never write to the working tree** (the
  "regenerate and inspect git diff" approach mutates the tree during verification — don't use it).
- If the repository has a rule like "never commit generated/intermediate files", **amend the rule
  with an explicit exception** everywhere it is stated (CLAUDE.md, CONTRIBUTING, etc.). Omitting
  this gets flagged as a rule violation in independent review.

## Diagram Standards

- **Diagrams assert facts.** Command names, exit codes, step ordering, state transitions, and
  numbers in a diagram are all subject to cross-checking against the canon and the implementation
  (see `review-docs`). Treat diagrams as an alternative representation of the spec, not decoration.
- Use inline SVG and keep pages self-contained (no external images, CDNs, or scripts).
- Give every SVG `role="img"` and a `<title>` (a description of the figure). Never rely on color
  alone (combine labels and solid/dashed strokes).
- Support light/dark: drive colors with CSS variables plus `prefers-color-scheme`; use `var(--…)`
  for SVG `fill`/`stroke` too.
- **Never edit generated pages to add diagrams** (it breaks the freshness check). Give the
  generator a figure-injection mechanism (e.g. fragments named `<slug>--<heading-anchor>--NN.html`
  inserted after the matching heading). Fragments are injected as raw HTML, so validate them with
  an **explicit element/attribute allowlist** (reject `on*` attributes, `style` attributes,
  `script`/`foreignObject`, etc.; allow `url()` only as same-document references `url(#id)`;
  apply the same href rules as body links).
- Share one CSS class vocabulary (box / arrow / label, etc.) across hand-written pages, generated
  pages, and fragments so everything looks consistent.

## Verification (definition of done)

Perform all of the following, then submit to an independent `review-docs` pass.

1. **Exhaustive machine check of links and anchors** — use `scripts/check-doc-links.py` bundled
   with `review-docs` (resolves relative links and verifies anchors for both md and HTML).
2. **Machine check of tag balance** — e.g. via `html.parser`.
3. **Visual check in both light and dark modes** — screenshot every page with a headless browser
   and eyeball overflow, overlap, and readability. Note: headless Chrome **inherits the OS
   dark-mode setting**. To force light mode, screenshot a temporary copy with the
   `prefers-color-scheme: dark` media query disabled (e.g. sed it to `min-width: 99999px`).
4. Independent review via `review-docs` — make sure fact-checking of diagram content is in scope.
   Fix any must-fix findings before reporting completion.
