# Atherix Red — scope hardening + SimForge integration

## 1. Authorization scope enforcement  (the important one)

**New: `scope.py`** — a default-deny authorization boundary every network-capable
action path checks before it runs. Out of the box it permits only loopback (where
your Docker CTF labs listen); everything else must be added with
`scope.add_to_scope(target, authorized_by="<your RoE ref>")`.

- Central gate in `agent_tools.execute_tool()` covers every network tool at the
  one chokepoint all tool calls funnel through.
- Defense-in-depth inline gates inside `run_command()` and `scan_ip()` — there are
  direct callers (`atherix_red.py`, `atherix_red_app.py`, `templates.py`) that
  bypass `execute_tool`, so the tool bodies gate themselves too.
- Obfuscation-resistant: decimal/hex IP encodings are normalized; allowlisted
  hostnames are resolved and the RESOLVED ip is checked (defeats DNS repointing).
- Fails closed: a network tool with no identifiable target is denied, not allowed.
- Every allow/deny is written to `scope_audit.log`.

Verified against a bypass battery: external IPs, private-LAN IPs, obfuscated
decimal IPs, DNS-repointed allowlist hosts, and `nmap $VAR` are all denied;
loopback labs, authorized targets, and local file commands pass.

**Still TODO on your side:** three files have their own `run_command`/`tool_scan_ip`
implementations or direct calls — `atherix_red.py:442`, `atherix_red_app.py:583`,
`templates.py:339`. The inline gates in `agent_tools.py` cover the shared
functions; route those three through the gated versions (or `execute_tool`) so
there's no path left unguarded. Flagged in the code comments too.

## 2. memory.json cleaned

**New: `sanitize_memory.py`** — quarantines out-of-scope entries into
`memory_quarantine.json` (nothing deleted). Run against your file it quarantined
all 18 targets, including the external ad-network domains and the two public IPs
(71.239.44.98, 99.70.107.30). The private-LAN lab IPs were quarantined too under
default-deny; re-add your actual authorized lab host consciously, e.g.
`scope.add_to_scope("192.168.1.100", "my lab VM")`.

## 3. SimForge integration

- `simforge/` package + `atherix_modules/` dropped in.
- `run_simulation` tool registered in `agent_tools.py` (soccer/basketball/
  custom Monte Carlo/parameter sweep) — routes through the tested SimForge bridge.
- New Flask endpoints in `atherix_red_app.py`: `/api/scope`, `/api/skills`,
  `/api/connectors`, `/api/plugins`, `/api/instructions`, `/api/styles`,
  `/api/scheduled`.
- `_scheduler_loop` hooked into startup alongside `_curiosity_loop`.
- forecast routing (`atherix_modules/forecast_routing.py`) is ready to splice into
  your `forecast_engine.py` per INTEGRATION.md — I left that one as a documented
  splice since it depends on how your forecast_engine calls the LLM.

## What I did not touch
The offensive capability — payload generation, the arbitrary-command path itself,
the uncensored-model prompt in test_atherix.py — is unchanged except for being
brought inside the scope boundary. I added containment, not capability.
