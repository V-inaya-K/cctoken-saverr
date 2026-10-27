#!/usr/bin/env python3
"""
cctoken-saverr hooks for Claude Code.

Events (pass as the first argument):
  stop        Stop hook: records when Claude finished and how big the context was
  prompt      UserPromptSubmit hook: warns if you were idle longer than the cache TTL
  precompact  PreCompact hook: backs up the full transcript before compaction (guardrail)
  session     SessionStart hook: re-injects the project notes file after /clear or /compact (guardrail)

Environment variables (all optional):
  CCTOKEN_SAVERR_TTL_MINUTES      cache lifetime to assume (default 5; use 60 with promptCacheTtl "1h")
  CCTOKEN_SAVERR_MIN_TOKENS       don't warn for contexts smaller than this (default 20000)
  CCTOKEN_SAVERR_MODE             "warn" (default), "block", or "off" for the idle warning
  CCTOKEN_SAVERR_BACKUP           "1" (default) back up transcripts before compaction, "0" to disable
  CCTOKEN_SAVERR_BACKUP_KEEP      how many backups to keep (default 20)
  CCTOKEN_SAVERR_NOTES_FILE       notes path relative to the project (default .claude/cctoken-saverr-notes.md)
  CCTOKEN_SAVERR_NOTES_ON         when to inject notes: comma list of startup,resume,clear,compact
                                (default clear,compact; "none" to disable)
  CCTOKEN_SAVERR_NOTES_MAX_CHARS  cap on injected notes (default 4000)

Any error exits 0 silently so the hooks can never break your session.
"""
import glob, json, os, shutil, sys, time

BASE = os.path.join(os.path.expanduser("~"), ".claude", "cctoken-saverr")
STATE_DIR = os.path.join(BASE, "state")
BACKUP_DIR = os.path.join(BASE, "backups")


def env(name, default):
    return os.environ.get(name, default)


def safe_id(session_id):
    return "".join(c for c in (session_id or "") if c.isalnum() or c in "-_") or "unknown"


def state_path(session_id):
    return os.path.join(STATE_DIR, safe_id(session_id) + ".json")


def context_tokens(transcript_path):
    """Size of the last request's prompt (input + cache read + cache write), from the transcript tail."""
    if not transcript_path or not os.path.exists(transcript_path):
        return 0
    with open(transcript_path, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 512_000))
        lines = f.read().decode("utf-8", "ignore").splitlines()
    for line in reversed(lines):
        try:
            usage = json.loads(line).get("message", {}).get("usage")
        except Exception:
            continue
        if usage:
            return (usage.get("input_tokens", 0)
                    + usage.get("cache_read_input_tokens", 0)
                    + usage.get("cache_creation_input_tokens", 0))
    return 0


def prune(directory, keep=None, max_age_days=None):
    files = sorted(glob.glob(os.path.join(directory, "*")), key=os.path.getmtime, reverse=True)
    cutoff = time.time() - max_age_days * 86400 if max_age_days else None
    for i, p in enumerate(files):
        if (keep is not None and i >= keep) or (cutoff and os.path.getmtime(p) < cutoff):
            os.remove(p)


# ---------- idle warning ----------

def on_stop(data):
    os.makedirs(STATE_DIR, exist_ok=True)
    state = {"last_stop": time.time(),
             "tokens": context_tokens(data.get("transcript_path")),
             "warned": False}
    with open(state_path(data.get("session_id")), "w") as f:
        json.dump(state, f)
    prune(STATE_DIR, max_age_days=7)


def on_prompt(data):
    mode = env("CCTOKEN_SAVERR_MODE", "warn").lower()
    if mode == "off":
        return
    path = state_path(data.get("session_id"))
    if not os.path.exists(path):
        return
    with open(path) as f:
        state = json.load(f)
    ttl = float(env("CCTOKEN_SAVERR_TTL_MINUTES", "5"))
    min_tokens = int(env("CCTOKEN_SAVERR_MIN_TOKENS", "20000"))
    idle_min = (time.time() - state["last_stop"]) / 60
    tokens = state.get("tokens", 0)
    if idle_min < ttl or tokens < min_tokens or state.get("warned"):
        return

    state["warned"] = True
    with open(path, "w") as f:
        json.dump(state, f)

    msg = (f"cctoken-saverr: idle {idle_min:.0f} min (cache TTL ~{ttl:.0f} min). "
           f"~{tokens/1000:.0f}k tokens of context will be re-written to the cache. "
           "To keep important context, run /cctoken-saverr:handoff first, then /clear (cheapest) "
           "or /compact (keeps a summary).")
    if mode == "block":
        print(msg + " Send your prompt again to continue anyway.", file=sys.stderr)
        sys.exit(2)  # blocks this prompt only; the next one goes through
    print(json.dumps({"systemMessage": msg}))


# ---------- guardrail: transcript backup before compaction ----------

def on_precompact(data):
    if env("CCTOKEN_SAVERR_BACKUP", "1") != "1":
        return
    src = data.get("transcript_path")
    if not src or not os.path.exists(src):
        return
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    trigger = data.get("trigger", "compact")
    dest = os.path.join(BACKUP_DIR, f"{stamp}-{trigger}-{safe_id(data.get('session_id'))}.jsonl")
    shutil.copy2(src, dest)
    prune(BACKUP_DIR, keep=int(env("CCTOKEN_SAVERR_BACKUP_KEEP", "20")))
    print(json.dumps({"systemMessage": f"cctoken-saverr: full transcript backed up to {dest}"}))


# ---------- guardrail: re-inject project notes after /clear or /compact ----------

def on_session(data):
    sources = [s.strip().lower() for s in env("CCTOKEN_SAVERR_NOTES_ON", "clear,compact").split(",")]
    if "none" in sources or data.get("source", "startup").lower() not in sources:
        return
    cwd = data.get("cwd") or os.getcwd()
    notes = os.path.join(cwd, env("CCTOKEN_SAVERR_NOTES_FILE", ".claude/cctoken-saverr-notes.md"))
    if not os.path.isfile(notes):
        return
    with open(notes, encoding="utf-8", errors="ignore") as f:
        text = f.read().strip()
    if not text:
        return
    cap = int(env("CCTOKEN_SAVERR_NOTES_MAX_CHARS", "4000"))
    if len(text) > cap:
        text = text[:cap] + "\n[...notes truncated by cctoken-saverr; keep the notes file shorter]"
    context = ("Project notes saved from an earlier session by cctoken-saverr "
               f"({os.path.relpath(notes, cwd)}). They may be stale; verify against the code:\n\n" + text)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                             "additionalContext": context}}))


def main():
    try:
        data = json.load(sys.stdin)
        event = (sys.argv[1] if len(sys.argv) > 1 else data.get("hook_event_name", "")).lower()
        handlers = {"stop": on_stop, "prompt": on_prompt, "userpromptsubmit": on_prompt,
                    "precompact": on_precompact, "session": on_session, "sessionstart": on_session}
        if event in handlers:
            handlers[event](data)
    except SystemExit:
        raise
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
