"""
scope.py — Authorization scope enforcement for Atherix Red.

The single most important control this codebase was missing: a hard, default-deny
authorization boundary that EVERY network-capable action path checks before it
runs. Today only lab_manager gates targets; run_command / scan_ip / http_request
et al. can hit any host on the internet. This module fixes that centrally.

Design principles:
  * DEFAULT DENY. If a target can't be positively shown to be in authorized
    scope, it is blocked. Ambiguity is denial, never permission.
  * ONE policy, ALL paths. execute_tool() calls check_command()/check_target()
    for every network-capable tool, so a new offensive tool can't accidentally
    ship without scope enforcement.
  * Fail closed on obfuscation. Decimal/hex/octal IP encodings are normalized;
    hostnames are resolved and the RESOLVED IP is what's checked, so
    `nmap sneaky.example.com` can't smuggle you to an out-of-scope address.
  * Auditable. Every allow/deny decision is appended to an audit log with the
    target, the command, and the reason — so scope can be reviewed after the fact.

Scope is authorization, not capability. Being in scope means you have written
permission to test that target. This module can't verify that permission exists;
it only makes sure the agent stays inside the list of targets YOU declared
authorized, and refuses everything else. Keeping that list honest is on you.
"""
from __future__ import annotations
import ipaddress
import json
import os
import re
import socket
from datetime import datetime, timezone

BASE_DIR = os.environ.get("ATHERIX_BASE", r"C:\atherix-red")
SCOPE_FILE = os.path.join(BASE_DIR, "scope.json")
AUDIT_LOG = os.path.join(BASE_DIR, "scope_audit.log")

# Network-capable binaries. If a shell command invokes one of these, its targets
# must be in scope. (Recon and exploitation tooling — the stuff that reaches out.)
NETWORK_BINARIES = {
    "nmap", "masscan", "rustscan", "zmap", "gobuster", "ffuf", "dirb", "dirbuster",
    "feroxbuster", "wfuzz", "nikto", "sqlmap", "hydra", "medusa", "ncrack",
    "curl", "wget", "nc", "ncat", "netcat", "telnet", "ssh", "scp", "sftp",
    "ftp", "smbclient", "crackmapexec", "cme", "enum4linux", "wpscan", "whatweb",
    "msfconsole", "msfvenom", "metasploit", "responder", "hping3", "ping",
    "traceroute", "tracert", "dig", "nslookup", "host", "amass", "subfinder",
    "httpx", "nuclei", "katana", "aquatone", "eyewitness",
}

# Tools (by registered name) that take a target and must be scope-checked.
# Maps tool name -> the arg(s) that carry the target.
NETWORK_TOOLS = {
    "run_command": ("command",),           # parsed for targets
    "run_command_in_lab": ("command",),
    "scan_ip": ("ip",),
    "http_request": ("url",),
    "fetch_url": ("url",),
    "fetch_and_analyze_url": ("url",),
    "whois_lookup": ("domain",),
    "run_arcsim_view": ("base_url",),   # only relevant if you override base_url
    "list_arcsim_modules": ("base_url",),
}


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------
def _default_policy() -> dict:
    # Out of the box: ONLY loopback (which is where the local Docker CTF labs
    # listen — DVWA on 127.0.0.1:8080, etc.). Nothing else until you add it.
    return {
        "enabled": True,
        "allowed_hosts": [],          # exact hostnames you're authorized to test
        "allowed_cidrs": ["127.0.0.0/8", "::1/128"],
        "notes": "Add targets ONLY with written authorization. Default-deny.",
    }


def load_policy() -> dict:
    if not os.path.exists(SCOPE_FILE):
        p = _default_policy()
        save_policy(p)
        return p
    try:
        with open(SCOPE_FILE, encoding="utf-8") as f:
            p = json.load(f)
        # never let a malformed file silently open scope
        p.setdefault("enabled", True)
        p.setdefault("allowed_hosts", [])
        p.setdefault("allowed_cidrs", ["127.0.0.0/8", "::1/128"])
        return p
    except Exception:
        # a broken policy file must fail CLOSED, not open
        return {"enabled": True, "allowed_hosts": [], "allowed_cidrs": [], "broken": True}


def save_policy(p: dict) -> None:
    os.makedirs(BASE_DIR, exist_ok=True)
    with open(SCOPE_FILE, "w", encoding="utf-8") as f:
        json.dump(p, f, indent=2)


def add_to_scope(target: str, authorized_by: str = "") -> dict:
    """Add a host or CIDR to scope. Records who authorized it in the audit log."""
    p = load_policy()
    tgt = target.strip()
    try:
        ipaddress.ip_network(tgt, strict=False)
        if tgt not in p["allowed_cidrs"]:
            p["allowed_cidrs"].append(tgt)
        kind = "cidr"
    except ValueError:
        if tgt not in p["allowed_hosts"]:
            p["allowed_hosts"].append(tgt)
        kind = "host"
    save_policy(p)
    _audit("SCOPE_ADD", tgt, f"kind={kind} authorized_by={authorized_by or 'unspecified'}", True)
    return {"ok": True, "added": tgt, "kind": kind}


# ---------------------------------------------------------------------------
# Target normalization + extraction
# ---------------------------------------------------------------------------
_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_HOST_RE = re.compile(r"\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}\b")
_URL_RE = re.compile(r"https?://([^/\s:]+)")
_DECIMAL_IP_RE = re.compile(r"\b\d{8,10}\b")  # e.g. curl http://2130706433/  (=127.0.0.1)

# Final labels that mean "this is a local file, not a host". Bare tokens ending in
# these are NOT treated as targets (so `cat notes.txt` isn't read as a hostname).
# URL-embedded hosts are captured separately and are NOT subject to this filter,
# so `curl http://evil.sh` is still scope-checked.
_FILE_EXTS = {
    "txt", "py", "json", "log", "md", "csv", "xml", "html", "htm", "js", "ts",
    "sh", "conf", "cfg", "yaml", "yml", "ini", "db", "sqlite", "png", "jpg",
    "jpeg", "gif", "pdf", "zip", "tar", "gz", "bak", "tmp", "lock", "toml",
    "env", "pem", "key", "crt", "cert", "pcap", "bin", "exe", "dll", "so",
}


def _looks_like_filename(token: str) -> bool:
    return token.rsplit(".", 1)[-1].lower() in _FILE_EXTS


def normalize_ip(token: str) -> str | None:
    """Return a canonical dotted IP for a token, or None. Catches decimal/hex/octal
    obfuscation (http://2130706433 == 127.0.0.1) that a naive dotted-quad check misses."""
    token = token.strip()
    # dotted quad
    try:
        return str(ipaddress.ip_address(token))
    except ValueError:
        pass
    # bare integer / hex integer forms
    try:
        if token.lower().startswith("0x"):
            val = int(token, 16)
        elif token.isdigit():
            val = int(token)
        else:
            return None
        if 0 <= val <= 0xFFFFFFFF:
            return str(ipaddress.ip_address(val))
    except ValueError:
        pass
    return None


def extract_targets(text: str) -> list[str]:
    """Pull candidate targets (IPs, hostnames, URL hosts, obfuscated IPs) out of a
    command string or URL. Over-collects on purpose — better to check too many."""
    targets: set[str] = set()
    url_hosts = set(_URL_RE.findall(text))
    for m in url_hosts:
        targets.add(m)                       # URL hosts always kept & checked
    for m in _IP_RE.findall(text):
        targets.add(m)
    for m in _HOST_RE.findall(text):
        # a bare token that looks like a local filename is not a network target,
        # unless it also appeared inside a URL (then it stays, via url_hosts)
        if m in url_hosts or not _looks_like_filename(m):
            targets.add(m)
    for m in _DECIMAL_IP_RE.findall(text):
        ip = normalize_ip(m)
        if ip:
            targets.add(m)
    return sorted(targets)


def _uses_network_binary(command: str) -> bool:
    tokens = re.split(r"[\s|;&(){}<>]+", command.lower())
    for tok in tokens:
        base = os.path.basename(tok)
        if base in NETWORK_BINARIES:
            return True
    return False


# ---------------------------------------------------------------------------
# The core check
# ---------------------------------------------------------------------------
def is_in_scope(target: str, policy: dict | None = None, resolver=None) -> tuple[bool, str]:
    """Is a single target authorized? Returns (allowed, reason). Default deny.

    resolver: injectable hostname->ip function (socket.gethostbyname by default),
    so this is testable offline and so DNS behavior is explicit.
    """
    p = policy or load_policy()
    resolver = resolver or (lambda h: socket.gethostbyname(h))
    allowed_nets = []
    for c in p.get("allowed_cidrs", []):
        try:
            allowed_nets.append(ipaddress.ip_network(c, strict=False))
        except ValueError:
            continue

    def ip_allowed(ipstr: str) -> bool:
        try:
            ip = ipaddress.ip_address(ipstr)
        except ValueError:
            return False
        return any(ip in net for net in allowed_nets)

    # 1. direct / obfuscated IP
    norm = normalize_ip(target)
    if norm is not None:
        if ip_allowed(norm):
            return True, f"IP {norm} in allowed CIDRs"
        return False, f"IP {norm} not in authorized scope"

    # 2. hostname — must be explicitly allowlisted AND resolve into an allowed net
    host = target.lower().rstrip(".")
    allowed_hosts = {h.lower() for h in p.get("allowed_hosts", [])}
    host_listed = host in allowed_hosts or any(
        host == h or host.endswith("." + h) for h in allowed_hosts)
    if not host_listed:
        return False, f"host {host!r} not on authorized allowlist"
    # even if listed, confirm it resolves into an allowed network (defends against
    # an allowlisted name being repointed at an out-of-scope box)
    try:
        resolved = resolver(host)
    except Exception as e:
        return False, f"host {host!r} listed but did not resolve ({e}) — deny"
    if ip_allowed(resolved):
        return True, f"host {host!r} resolves to in-scope {resolved}"
    return False, f"host {host!r} resolves to out-of-scope {resolved} — deny"


def check_command(command: str, resolver=None) -> dict:
    """Gate a shell command. Returns {allowed, reason, targets, denied}."""
    p = load_policy()
    if not p.get("enabled", True):
        # scope disabled is itself an auditable, risky state
        _audit("ALLOW", command[:120], "scope enforcement DISABLED in policy", True)
        return {"allowed": True, "reason": "scope enforcement disabled", "targets": [], "denied": []}

    targets = extract_targets(command)
    is_net = _uses_network_binary(command)

    # Pure local command, no targets, no network binary -> allow (ls, cat, python...)
    if not targets and not is_net:
        return {"allowed": True, "reason": "local command, no network targets", "targets": [], "denied": []}

    # Network binary but no identifiable target -> FAIL CLOSED. We can't prove
    # scope, so we don't allow it. (Prevents `nmap $TARGET` style smuggling.)
    if is_net and not targets:
        _audit("DENY", command[:120], "network tool with no resolvable target — fail closed", False)
        return {"allowed": False, "reason": "network command with no identifiable target; "
                "blocked (add an explicit in-scope target)", "targets": [], "denied": []}

    denied = []
    for t in targets:
        ok, why = is_in_scope(t, p, resolver=resolver)
        if not ok:
            denied.append({"target": t, "reason": why})

    if denied:
        _audit("DENY", command[:120], f"out-of-scope: {[d['target'] for d in denied]}", False)
        return {"allowed": False,
                "reason": "blocked: target(s) outside authorized scope. "
                          "Add them to scope.json ONLY if you have written authorization.",
                "targets": targets, "denied": denied}

    _audit("ALLOW", command[:120], f"in-scope: {targets}", True)
    return {"allowed": True, "reason": "all targets in scope", "targets": targets, "denied": []}


def check_target(target: str, resolver=None) -> dict:
    """Gate a single explicit target (for scan_ip, http_request, etc.)."""
    p = load_policy()
    if not p.get("enabled", True):
        _audit("ALLOW", target, "scope enforcement DISABLED in policy", True)
        return {"allowed": True, "reason": "scope enforcement disabled"}
    # for a URL, pull the host
    m = _URL_RE.match(target) or _URL_RE.search(target)
    real = m.group(1) if m else target
    ok, why = is_in_scope(real, p, resolver=resolver)
    _audit("ALLOW" if ok else "DENY", target, why, ok)
    return {"allowed": ok, "reason": why}


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
def _audit(decision: str, subject: str, reason: str, allowed: bool) -> None:
    os.makedirs(BASE_DIR, exist_ok=True)
    line = json.dumps({
        "ts": datetime.now(timezone.utc).isoformat(),
        "decision": decision, "allowed": allowed,
        "subject": subject, "reason": reason,
    })
    try:
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def read_audit(limit: int = 200) -> list[dict]:
    if not os.path.exists(AUDIT_LOG):
        return []
    with open(AUDIT_LOG, encoding="utf-8") as f:
        lines = f.readlines()[-limit:]
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out
