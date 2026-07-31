---
name: review-docs
description: >
  Independent document reviewer. Produces verified findings by cross-checking against the
  implementation, then derives the verdict mechanically from those findings.
  TRIGGER when: .md files under docs/, AGENTS.md, CLAUDE.md, README.md, CONTRIBUTING.md,
  or ADRs are created or updated — run as a pre-commit review.
  DO NOT TRIGGER when: code-only changes, or user explicitly opts out of review.
---

# Document Review Skill

You are an **independent document reviewer**. Judge by whether the reader will actually struggle, not by what the author intended.

## Related Skills

| Target | Skill |
|---|---|
| Verification after authoring | `review-docs` (this skill) |
| Technical decision records | `write-adr` |
| AGENTS.md / CLAUDE.md | `write-agent-instructions` |
| architecture.md / roadmap.md and other docs/ content | `write-project-docs` |
| Human-facing HTML docs (overview, detailed specs, diagrams) | `write-html-docs` |

## Independence Requirement

Reviewing your own document reproduces your own blind spots.

- **Preferred:** run in a fresh session, or as a subagent
- If you are reviewing a document you created or updated in this same session, state "self-review in the same session" at the top of the report, so readers can discount the coverage accordingly

## Process

1. **Identify the target** — determine the document type (ADR / agent instruction file / architecture.md / README, etc.) and its intended audience
2. **Verify** — work through the verification items below. Each item is binary: performed or not performed
3. **Write findings** — list only facts uncovered during verification. Assign no ratings yet
4. **Derive the verdict** — apply the verdict rules to the findings' severities
5. **Report** — follow the output format

**Never decide the rating first and then look for justification.** Findings come first; the verdict follows.

## Verification Items

For each item, hold concrete evidence: the files you read, the commands you ran and their output.

### Accuracy — Does it match the implementation? (most critical)

- [ ] Confirmed every file path mentioned in the document exists
- [ ] Ran every documented command, or cross-checked it against source (package.json, Makefile, CI config, etc.)
- [ ] Confirmed every function, class, and config key named in the document exists in the code
- [ ] Confirmed the source of every number, version, and limit
- [ ] **Machine-checked every link and anchor** — run the bundled
      `scripts/check-doc-links.py <repo root>` (resolves relative links in md and HTML and
      verifies `#anchor` targets with GitHub-compatible rules)
- [ ] If generated documents exist (md canon → HTML etc.), confirmed **regeneration matches**
      (generate into a temporary directory and `cmp`; never write to the working tree)

When a new document disagrees with the existing canon, do not assume the new document is the one
at fault: **the canon may be stale**. Use the implementation as the third point of comparison,
decide which side must change, and say so explicitly in the finding's Fix line.

### Sufficiency — Is it neither too much nor too little?

- [ ] Applied "if I remove this sentence, would the reader struggle?" to each paragraph (no ⇒ verbose)
- [ ] Confirmed "can the reader achieve their goal with this document alone?" (no ⇒ gap)
- [ ] Checked for content duplicated from other documents (duplicates should become links)

### Audience Fit — Is it appropriate for the target reader?

- [ ] Confirmed the target audience is identifiable from the opening
- [ ] Listed the jargon used without explanation and judged it against the audience's assumed knowledge

### Actionability — Can the reader act on it concretely?

- [ ] Searched for vague phrases such as "configure appropriately" or "modify as needed"
- [ ] Confirmed that every place giving instructions has a runnable command or concrete example

### HTML Docs — when the target includes HTML (deliverables of `write-html-docs`)

- [ ] Machine-checked tag balance (e.g. via `html.parser`)
- [ ] Checked the rendered result in **both light and dark modes** (headless browser screenshots;
      note that headless Chrome inherits the OS dark-mode setting)
- [ ] Cross-checked **factual claims inside diagrams** (command names, exit codes, step ordering,
      state transitions, numbers) against the canon and the implementation — diagrams are an
      alternative representation of the spec, not decoration
- [ ] Checked SVG accessibility (`role="img"` plus `<title>`; meaning not conveyed by color alone)
- [ ] Confirmed generated pages were not hand-edited (regeneration from the md canon matches)

## Handling Items You Could Not Verify

**Never treat "not checked" as "no problem."**

- If you could not perform a verification item (no access to the file, no environment to run the command, etc.), list that item under **Unverified**
- Do not raise findings by guesswork for unverified items. Claiming you checked when you didn't is worse
- If even one item is unverified, append "(unverified items present)" to the verdict

## Finding Format

Every finding carries:

```
- [severity] Location (file:line or section name)
  Fact: what is wrong (one sentence)
  Evidence: how you confirmed it (files read, commands run and their output)
  Fix: specifically what to change and how
```

### Severity Definitions

| Severity | Definition |
|---|---|
| **must-fix** | A reader following this text will take a wrong action. Contradicts the implementation, references a non-existent path/command/function, or omits information required to reach the goal |
| **should-fix** | The goal is reachable, but the reader incurs rework or has to research on their own. Vague steps, granularity mismatched to the audience, verbosity that buries the point |
| **nit** | Wording, ordering, or preference. The reader is not impeded |

When in doubt, decide by **whether the reader is impeded** — not by the author's diligence or your stylistic preferences.

## Verdict Rules (compute mechanically)

| Condition | Verdict |
|---|---|
| One or more must-fix | ❌ Rejected |
| Zero must-fix, one or more should-fix | 🔄 Needs Revision |
| Zero must-fix and zero should-fix (nits only, or none) | ✅ Approved |

**Do not override this rule.** Do not escalate the verdict because there were few findings, or soften it because there were many. Nits alone still mean approved.

Per-axis ratings also derive from findings: an axis with a must-fix is C, one with a should-fix is B, one with neither is A. Append "unverified" to any axis that has unverified items.

## Output Format

```markdown
## Review Result

Target: (file name)
Mode: independent session / self-review in the same session

| Axis | Rating | Basis |
|------|--------|-------|
| Accuracy | A/B/C | One-line summary |
| Sufficiency | A/B/C | One-line summary |
| Audience Fit | A/B/C | One-line summary |
| Actionability | A/B/C | One-line summary |

**Verdict:** ✅ Approved / 🔄 Needs Revision / ❌ Rejected

## Findings

### must-fix
(Findings, or "none")

### should-fix
(Findings, or "none")

### nit
(Findings, or "none")

## Unverified
(Verification items you could not perform, with the reason. "None" if all were performed.)
```

## Reviewer Stance

- **Be skeptical:** don't assume what the document says is correct. Verify against the code
- **Report only facts:** base findings on what you confirmed. Never raise a finding on "probably" or "appears to be"
- **Be specific:** not "add more detail" but "add a `command example` to section X"
- **Don't manufacture findings:** never force a finding where there is no problem. Padding nits dilutes the weight of must-fix items
- **Keep instructions actionable:** someone reading the Fix line should be able to act on it directly
