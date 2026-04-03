# code-review-harness

A Claude Code plugin implementing the **Generator-Evaluator harness pattern** for code review.

Inspired by [Anthropic's harness design research](https://www.anthropic.com/engineering/harness-design-long-running-apps), this plugin provides an independent Evaluator that finds bugs by **actually running the code** — not just reading it.

## The Core Problem

When an agent reviews code it has context about, it evaluates leniently.
The same model that says "this might be a security risk" when reading code
will say "HTTP 200 returned — User B modified User A's data" when it actually tries.

## Skill

| Skill | Description |
|-------|-------------|
| `harness-review` | Independent Evaluator — discovers the project environment from scratch, runs the code, and reports only confirmed findings |

## Usage
```bash
/code-review-harness:harness-review
```

⚠️ **Must be run in a fresh Claude Code session.**
Running in a session that has previously worked on this codebase contaminates
the evaluation context and defeats the purpose of the harness.

## How It Works

**Phase 1 — Project Understanding**
The Evaluator reads the codebase to discover project type, start commands, auth mechanism,
and resource ownership — without any prior assumptions or context.

**Phase 2 — Verification**
The Evaluator runs the app using only what it discovered in Phase 1,
then systematically tests authorization, authentication, data integrity,
pagination, and input validation.

**Phase 3 — Report**
Only confirmed findings are reported. "This might be an issue" is not accepted.
Each finding includes what was tested, what was returned, and a recommended fix.

## Project-Agnostic Design

This skill works for REST APIs, CLI tools, batch processors, libraries, and frontends.
Phase 1 discovers the environment from the project's own files — no assumptions about
Docker, Rails, npm, or any specific framework.

## Install
```bash
# From GitHub
/plugin marketplace add naokami3/ai-dotfiles

# Local test
claude --plugin-dir ./plugins/code-review-harness
```

## Reference

- [harness_review_example](https://github.com/naokami3/harness_review_example) — experiment comparing standard review vs harness-review on a Rails API with intentional bugs
