# doc-authoring-skills

A Claude Code plugin for authoring and reviewing technical documents.

## Skills

| Skill | Description |
|-------|-------------|
| `write-adr` | Create Architecture Decision Records with structured format |
| `write-claude-md` | Create or update CLAUDE.md following Anthropic's best practices |
| `write-project-docs` | Standards for project documentation (architecture.md, roadmap.md, etc.) |
| `review-docs` | Independent document reviewer with 4-axis evaluation (Accuracy, Sufficiency, Audience Fit, Actionability) |

## Design Philosophy

Inspired by the Generator-Evaluator pattern from [Anthropic's harness design research](https://www.anthropic.com/engineering/harness-design-long-running-apps), this plugin separates document **creation** (write-*) from **evaluation** (review-docs). The independent reviewer provides critical feedback that a generator agent cannot give to its own output.

## Install

```bash
# From GitHub marketplace
/plugin marketplace add naokami3/ai_dotfiles
/plugin install doc-authoring-skills@ai-dotfiles

# Or test locally
claude --plugin-dir ./plugins/doc-authoring-skills
```

## Usage

```
/doc-authoring-skills:write-adr
/doc-authoring-skills:review-docs
```

## Japanese Version

A Japanese version is available as a separate plugin: `doc-authoring-skills-ja`

## License

MIT
