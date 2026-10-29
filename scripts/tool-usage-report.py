#!/usr/bin/env python3
"""tool-usage-report — which tools, skills and agents were offered to Claude Code but never used (2026-10-29).

Read-only. Parses ~/.claude/projects/**/*.jsonl (subagent logs count towards their parent session):
  offered = deferred_tools_delta / skill_listing / agent_listing_delta attachments the session saw
  used    = tool_use blocks (incl. Skill.skill, Agent.subagent_type) + user /slash commands
Output is evidence for hand-editing permissions.deny / skillOverrides / enabledPlugins; it writes nothing.
Run once per machine:  python3 ~/.claude/scripts/tool-usage-report.py [--days 90] [--min-sessions 20] [--json]
Caveats: "never used" is only as good as the window; a tool offered in few sessions is flagged low-evidence.
"""
import argparse, collections, json, re, sys, time
from pathlib import Path

SLASH = re.compile(r"<command-name>/?([^<\s]+)</command-name>")
SKILL_LINE = re.compile(r"^- (\S+?): ", re.M)  # plugin skills are "plugin:skill: description"


def session_key(p: Path, root: Path) -> str:
    parts = p.relative_to(root).parts  # <project>/<session>.jsonl or <project>/<session>/subagents/x.jsonl
    return parts[0] + "/" + parts[1].removesuffix(".jsonl")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path.home() / ".claude" / "projects"))
    ap.add_argument("--days", type=float, default=0, help="only files modified in the last N days (0 = all)")
    ap.add_argument("--min-sessions", type=int, default=20,
                    help="an unused item offered in fewer sessions is marked low-evidence")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    root = Path(a.root)
    cutoff = time.time() - a.days * 86400 if a.days else 0

    used = collections.Counter()            # (kind, name) -> calls
    used_sessions = collections.defaultdict(set)
    offered_sessions = collections.defaultdict(set)  # (kind, name) -> sessions
    sessions = set()
    skill_chars, mcp_chars, deferred_n = [], [], []
    bad_lines = 0

    for p in sorted(root.glob("*/**/*.jsonl")):
        if cutoff and p.stat().st_mtime < cutoff:
            continue
        sk = session_key(p, root)
        sessions.add(sk)
        deferred = set()
        try:
            fh = p.open(encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except ValueError:
                    bad_lines += 1
                    continue
                t = o.get("type")
                if t == "attachment":
                    at = o.get("attachment") or {}
                    ty = at.get("type")
                    if ty == "deferred_tools_delta":
                        deferred |= set(at.get("addedNames") or [])
                        deferred -= set(at.get("removedNames") or [])
                    elif ty == "skill_listing":
                        c = at.get("content") or ""
                        skill_chars.append(len(c))
                        for n in SKILL_LINE.findall(c):
                            offered_sessions[("skill", n.strip())].add(sk)
                    elif ty == "agent_listing_delta":
                        for n in at.get("addedTypes") or []:
                            offered_sessions[("agent", n)].add(sk)
                    elif ty == "mcp_instructions_delta":
                        mcp_chars.append(sum(len(b) for b in at.get("addedBlocks") or []))
                elif t == "assistant":
                    m = o.get("message") or {}
                    for b in m.get("content") or [] if isinstance(m.get("content"), list) else []:
                        if b.get("type") != "tool_use":
                            continue
                        name, inp = b.get("name", "?"), b.get("input") or {}
                        used[("tool", name)] += 1
                        used_sessions[("tool", name)].add(sk)
                        if name == "Skill" and inp.get("skill"):
                            k = ("skill", str(inp["skill"]).lstrip("/"))
                            used[k] += 1; used_sessions[k].add(sk)
                        if name in ("Agent", "Task"):
                            k = ("agent", inp.get("subagent_type") or "general-purpose")
                            used[k] += 1; used_sessions[k].add(sk)
                elif t == "user":
                    m = o.get("message") or {}
                    c = m.get("content")
                    text = c if isinstance(c, str) else " ".join(
                        x.get("text", "") for x in c if isinstance(x, dict)) if isinstance(c, list) else ""
                    for n in SLASH.findall(text):
                        k = ("skill", n)
                        used[k] += 1; used_sessions[k].add(sk)
        for n in deferred:
            offered_sessions[("tool", n)].add(sk)
        deferred_n.append(len(deferred))

    def server(name: str) -> str:
        return name.split("__")[1] if name.startswith("mcp__") else ""

    unused = []
    for (kind, name), ss in offered_sessions.items():
        if (kind, name) in used:
            continue
        unused.append({"kind": kind, "name": name, "server": server(name), "offered_sessions": len(ss),
                       "low_evidence": len(ss) < a.min_sessions})
    unused.sort(key=lambda r: (r["kind"], r["server"], -r["offered_sessions"], r["name"]))

    avg = lambda xs: round(sum(xs) / len(xs)) if xs else 0
    summary = {"sessions": len(sessions), "bad_json_lines": bad_lines,
               "avg_deferred_tool_names": avg(deferred_n), "avg_skill_listing_chars": avg(skill_chars),
               "avg_mcp_instruction_chars": avg(mcp_chars)}
    rows_used = [{"kind": k, "name": n, "calls": c, "sessions": len(used_sessions[(k, n)])}
                 for (k, n), c in used.most_common()]

    if a.json:
        json.dump({"summary": summary, "used": rows_used, "unused": unused}, sys.stdout, indent=1)
        return 0

    print(f"sessions: {summary['sessions']}  (unparsable lines: {bad_lines})")
    print(f"avg per session: {summary['avg_deferred_tool_names']} deferred tool names, "
          f"skill listing {summary['avg_skill_listing_chars']} chars, "
          f"MCP instructions {summary['avg_mcp_instruction_chars']} chars\n")
    for kind in ("tool", "skill", "agent"):
        print(f"== USED {kind}s (calls / sessions)")
        for r in rows_used:
            if r["kind"] == kind:
                print(f"  {r['calls']:6d} {r['sessions']:5d}  {r['name']}")
        print()
    for kind in ("tool", "skill", "agent"):
        print(f"== OFFERED BUT NEVER USED {kind}s (offered in N sessions; ? = fewer than {a.min_sessions})")
        by_server = collections.defaultdict(list)
        for r in unused:
            if r["kind"] == kind:
                by_server[r["server"]].append(r)
        for srv, rs in by_server.items():
            if srv:
                print(f"  [mcp server {srv}] {len(rs)} tools, offered in up to {max(r['offered_sessions'] for r in rs)} sessions")
            else:
                for r in rs:
                    print(f"  {r['offered_sessions']:5d}{'?' if r['low_evidence'] else ' '} {r['name']}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
