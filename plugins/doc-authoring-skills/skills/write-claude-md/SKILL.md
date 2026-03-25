---
name: write-claude-md
description: >
  Create or update CLAUDE.md following Anthropic's recommended structure. Use at project start or when adding rules.
  TRIGGER when: creating or updating CLAUDE.md, or adding new entries to sections
  like rules, pitfalls, or commands.
  DO NOT TRIGGER when: changes to files other than CLAUDE.md, code-only changes.
---

# CLAUDE.md Authoring Guide

Create or update the project's CLAUDE.md following Anthropic's best practices.

## Structure (in this order)

1. **Project overview** — 1-2 sentences. Include the tech stack
2. **Commands** — Build, test, lint, run commands. Prioritize what Claude cannot guess
3. **Coding conventions** — Only rules that differ from defaults. Don't duplicate linter/formatter rules
4. **Mandatory rules** — Constraints that cause breakage if violated. Use numbered lists
5. **Known pitfalls** — Non-obvious issues that aren't apparent from reading code alone
6. **Related documentation** — Links to docs/, CONTRIBUTING.md, etc.

## What to Include

- Project-specific information Claude cannot infer
- Rules that immediately cause bugs if violated
- Past pitfalls (DLL conflicts, license restrictions, etc.)
- Build/test/deploy commands

## What NOT to Include

- Anything derivable from reading the code (file structure, function listings)
- Style rules enforced by linters/formatters
- Long explanations or tutorials (split to docs/)
- Marketing copy or differentiators (belongs in README)
- Obvious practices ("write clean code")

## Quality Criteria

- **Under 60 lines** is ideal. Do not exceed 200 lines. Effectiveness drops significantly beyond 300 lines
- "If I remove this, will Claude make a mistake?" — If no, remove it
- Review monthly and prune unnecessary instructions
- Put details in docs/ and keep CLAUDE.md to links only

## Rule Patterns

```markdown
## Mandatory Rules

1. **What not to do** — Why (one line)
2. **What to do** — In which file/module
```

- Add a one-line reason (so future developers can make judgment calls)
- Include specific file paths
- Use "must not" for prohibitions, "define in" for requirements

## Pitfall Patterns

```markdown
## Known Pitfalls

- **Problem name**: Workaround. Details at [link]
```

- Bold the name for scannability
- Write the workaround in one line, link to ADR or docs for details
