---
name: cctoken-saverr
description: Keeps Claude Code's context window small so every turn costs fewer cache-read and cache-write tokens, without losing important context. Use this skill at the start of any coding session, and whenever exploring a codebase, reading files, running commands with long output, debugging, doing multi-step work in a large repo, or when the user returns after a break, even if the user never mentions tokens, cost, or caching.
---

# cctoken-saverr working style

## Why this matters
Every turn, Claude Code resends the whole conversation (system prompt, tools, CLAUDE.md, every file read, every command output). Most of it is served from the prompt cache, but cache reads are still billed on every turn, and anything new gets billed as a cache write. A 5,000-line file read early in a session keeps costing money on every later turn until the session is compacted or cleared. The goal: put less into the context, keep the stable part stable, and never lose what matters.

## Guardrails: correctness comes first
Saving tokens is never worth a wrong answer or a broken edit. These override everything below:
- **Always read the code you are about to change**, plus enough surrounding lines (callers, imports, the whole function) to edit it safely. Never edit blind to save a read.
- **Errors live at the end.** When trimming command output, use `tail` for build/test failures so the actual error and stack trace are kept. If the trimmed output doesn't explain the failure, rerun with more output rather than guessing.
- **If a search result is ambiguous or incomplete, read more.** A second targeted read is cheaper than a wrong fix.
- **Don't drop the user's requirements.** Constraints, decisions, and preferences the user stated stay in force even after compaction; that's what the notes file is for.
- **Don't suggest `/clear` mid-task** while there's unfinished work, uncommitted changes you haven't told the user about, or open decisions. Finish or save state first.

## The notes file (protects important context)
The project file `.claude/cctoken-saverr-notes.md` survives `/clear` and `/compact`; the cctoken-saverr hooks re-inject it into the new context automatically.
- When something important is decided or learned (a user requirement, an architecture decision, the root cause of a bug, the current task's next steps), add a short bullet to the notes file.
- Keep it short: under ~40 lines. It is resent every turn after being injected, so it must stay lean. Replace stale bullets rather than appending forever.
- Before suggesting `/clear` or `/compact`, update the notes file first (or suggest the user run `/cctoken-saverr:handoff`).
- If the notes file was injected at session start, treat it as context from an earlier session that may be stale; verify against the code before relying on details.

## Reading code
- Locate before you read. Use `grep -n`, `rg`, `glob`, or `ls` to find the exact file and line range, then read that range (Read tool offset/limit).
- Avoid reading whole files over ~300 lines unless the task truly needs all of it.
- Don't re-read a file you already have in context unless it has changed since.
- Skip generated and vendored files: lockfiles, `dist/`, `build/`, `node_modules/`, minified bundles, snapshots, large fixtures, binary data.

## Running commands
- Cap output: `| head -50`, `| tail -80` (for errors), or `| grep` for what you need.
- Use quiet flags: `npm install --silent`, `pip install -q`, `pytest -q --tb=short`, `git log --oneline -20`, `git diff --stat` before a full diff.
- Redirect big output to a file and grep the file instead of dumping it into context.

## Exploration and research
- For broad searches across many files, delegate to a subagent (Task/Explore). Its reads stay in its own context; only its summary comes back.
- Ask the subagent for file paths, line numbers, and a few sentences, not pasted code.

## Writing and editing
- Edit with targeted replacements rather than rewriting whole files.
- Don't echo large blocks of code in replies; reference file paths and line numbers.

## Keeping the cache stable
These break the cache prefix and force a full rewrite: switching models mid-session, enabling or disabling MCP servers or tools mid-session, editing CLAUDE.md and reloading it. If one is needed, suggest doing it at the start of a fresh session.

## The 5-minute idle problem
The prompt cache lives for 5 minutes by default, refreshed on every turn. After a longer pause the next message rewrites the entire context as a cache write (1.25x base input price) instead of a cache read (0.1x).
- If the user returns after a long break and the old context is not needed, suggest saving notes and then `/clear`.
- If they still need the context, suggest `/compact` with a focus that names what must be kept, e.g. `/compact keep the auth bug root cause and the API contract we agreed`.
- If the user often steps away 5 to 60 minutes and uses an API key or cloud provider, suggest `"promptCacheTtl": "1h"` in settings. One-hour writes cost 2x instead of 1.25x, so it pays off only when sessions are reused after pauses.
- If the idle hook prints a "cache likely expired" warning, mention these options briefly.

## Session hygiene (suggest these to the user)
- Unrelated next task → save notes, then `/clear`.
- Long session, context still needed → `/compact` with a focus.
- `/context` shows what is using space; `/usage` or `/cost` shows spend and cache hit rate.
- Many unused MCP servers → suggest disabling them; their tool definitions are sent every turn.
