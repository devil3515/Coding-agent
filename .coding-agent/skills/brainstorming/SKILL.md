---
name: brainstorming
description: "You MUST use this before any creative work - creating features, building components, adding functionality, or modifying behavior. Explores user intent, requirements and design before implementation."
---

# Brainstorming for Coding-Agent

Help turn ideas into fully formed designs and specs through natural collaborative dialogue.

Start by understanding the current project context, then ask questions one at a time to refine the idea. Once you understand what you're building, present the design and get user approval.

<HARD-GATE>
Do NOT invoke any implementation skill, write any code, scaffold any project, or take any implementation action until you have presented a design and the user has approved it. This applies to EVERY project regardless of perceived simplicity.
</HARD-GATE>

## Checklist

1. **Explore project context** — check files, docs, recent commits in `Coding-agent/`
2. **Offer the visual companion just-in-time** — if a question would be clearer shown than described, offer it then; on approval its browser tab opens
3. **Ask clarifying questions** — one at a time, understand purpose/constraints/success criteria
4. **Propose 2-3 approaches** — with trade-offs and your recommendation
5. **Present design** — in sections scaled to complexity, get user approval after each section
6. **Write design doc** — save to `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` and commit
7. **Spec self-review** — quick inline check for placeholders, contradictions, ambiguity, scope
8. **User reviews written spec** — ask user to review before proceeding
9. **Transition to implementation** — invoke writing-plans skill to create implementation plan

## Key Principles for Coding-Agent

- **One question at a time** - Don't overwhelm with multiple questions
- **Multiple choice preferred** - Easier to answer than open-ended when possible
- **YAGNI ruthlessly** - Remove unnecessary features from all designs
- **Explore alternatives** - Always propose 2-3 approaches before settling
- **Incremental validation** - Present design, get approval before moving on
- **Be flexible** - Go back and clarify when something doesn't make sense

## Project Context

This is a Python-based AI coding assistant that runs in the terminal with:
- LLM integration via OpenAI-compatible endpoints
- MongoDB for memory storage (short-term and long-term)
- Tool registry system for extensibility
- MCP servers support
- Safety/guardrails system

Source structure:
- `src/tools/` - Available tools
- `src/memory/` - Memory systems
- `src/llm/` - LLM provider integrations
- `src/safety/` - Guardrails

Build with: `pip install -e .`
Test with: `pytest`

## Visual Companion

A browser-based companion for showing mockups, diagrams, and visual options during brainstorming. Available as a tool — not a mode.

**Offering the companion (just-in-time):** Do NOT offer it upfront. Wait until a question would genuinely be clearer shown than told.

**This offer MUST be its own message.** Only the offer — no clarifying question, summary, or other content. Wait for the user's response.
