# Environment — Linux

Loaded only on a Linux machine, through `env-local.md`, which `hooks/select-env.mjs`
writes at session start.

Deliberately near-empty. The Windows file grew over months of running into things;
this one has to earn its entries the same way, and a plausible-sounding rule nobody
measured here would be worse than no rule. `/update-claude-md` is what fills it.

Anything that turns out to hold on every platform belongs in the **Tools and runtime**
section of `CLAUDE.md` instead, not here.

- **Closing the window does not end Claude Desktop, and settings are read only when a
  session starts.** Measured 2026-08-29, and it cost the better part of an hour before it
  was noticed: the Electron process had been up for two days while a restart was believed
  to have happened, so a rewritten `settings.json` — new hooks included — had never taken
  effect, and nothing anywhere said so. Quit from the app menu, or `kill` the PID of
  `/opt/claude-desktop/claude-desktop`; then resume the session, which re-reads every
  instruction file, so the conversation survives it. Two one-line checks settle it:
  `ps -o lstart= -p <pid>` for the process, and the mtime of `env-local.md`, which the
  SessionStart hook rewrites on every start and which therefore doubles as a witness that
  a session really began.

- **`systemctl show` of a unit systemd does not know FABRICATES success-shaped
  answers**: `Result=success`, `ExecMainStatus=0`, `ActiveState=inactive` — measured
  2026-09-01 on systemd 259 (user manager). A successful transient unit is collected
  the moment it exits, so reading its verdict afterwards gets the fabricated answers,
  not the real ones. Check `LoadState=loaded` before believing anything else, or run
  the unit with `-p RemainAfterExit=yes` and read the verdict while it still exists.
