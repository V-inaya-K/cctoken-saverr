---
description: Save the important context of this session to the cctoken-saverr notes file so it survives /clear or /compact
---

Update `.claude/cctoken-saverr-notes.md` in the project root (create the `.claude` folder and file if missing) so that a fresh session could continue this work without the current conversation.

Write short bullets under these headings, and replace outdated content rather than appending to it:

- **Goal**: what we are working on and why
- **Decisions & constraints**: requirements the user stated, choices we made, things to avoid
- **Findings**: root causes, important file paths and line numbers, gotchas discovered
- **Status**: what is done, what is in progress, uncommitted changes
- **Next steps**: the concrete next actions

Keep the whole file under 40 lines. Leave out anything that can be cheaply rediscovered from the code. Don't paste code blocks; reference paths instead.

When done, show the user the file in a few lines and tell them it is now safe to run `/clear` (fresh start, notes re-injected) or `/compact` (keeps a summary).
$ARGUMENTS
