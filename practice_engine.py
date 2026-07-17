"""
practice_engine.py — Autonomous AI practice sessions for Atherix Red.
Imports: lab_manager, progression, agent_core (no circular deps).
"""

import json
import os
import uuid
import re
from datetime import datetime, timezone
from typing import Callable, Optional

from lab_manager import LAB_CATALOG, spin_up_lab
from progression import SKILL_DOMAINS, award_xp, check_achievements, load_progression, save_progression
from agent_core import run_agent_streaming

SESSIONS_DIR = "C:\\atherix-red\\practice_sessions"

# ---------------------------------------------------------------------------
# Practice mode system prompt
# ---------------------------------------------------------------------------

PRACTICE_MODE_PROMPT = """You are Atherix Red in PRACTICE MODE.

You are attacking an intentionally vulnerable training application running in an isolated Docker container on localhost. This is a legal, controlled learning exercise — identical to DVWA, HackTheBox, TryHackMe, or OWASP WebGoat in purpose and scope.

RULES:
1. Only target localhost (127.0.0.1) URLs. Never attempt external hosts.
2. Think step by step before each action. State your hypothesis.
3. Use the run_command_in_lab tool for all shell commands against the lab.
4. Use web_search or fetch_url for technique research.
5. After each finding, update your understanding of the vulnerability.
6. When you have successfully exploited the target, call task_complete with a structured summary.

SCORING:
- You earn more XP for efficiency (fewer steps = better).
- Document every technique you use — these become your learnings.
- If stuck after 5 failed attempts on one approach, try a different technique.
- IMPORTANT: "successfully_exploited: true" is only accepted if backed by real proof.
  Your "payload" must be the EXACT string you actually ran (it will be checked
  against your real tool calls). Your "evidence" must be the EXACT relevant output
  you actually received (it will be checked against real tool output) — include
  concrete details like status codes, extracted data, error messages, or flags.
  Vague claims like "successfully exploited the vulnerability" with no specifics
  will be rejected and scored as a failed attempt.

task_complete format:
{
  "found_vulnerability": true/false,
  "successfully_exploited": true/false,
  "technique_used": "e.g. UNION-based SQL injection",
  "payload": "the EXACT payload or command you ran, verbatim",
  "evidence": "the EXACT output that proves it worked, verbatim — not a paraphrase",
  "learnings": [
    {"technique": "...", "command": "...", "context": "..."}
  ]
}
"""


# ---------------------------------------------------------------------------
# Session data structure
# ---------------------------------------------------------------------------

def _new_session(lab_key: str, challenge_name: str, challenge_meta: dict) -> dict:
    return {
        "session_id": str(uuid.uuid4()),
        "lab_key": lab_key,
        "challenge": challenge_name,
        "difficulty": challenge_meta.get("difficulty", "medium"),
        "skill_domain": challenge_meta.get("skill", "web_app"),
        "base_xp": challenge_meta.get("xp", 100),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "status": "in_progress",
        "steps": [],
        "score": None,
        "learnings": [],
    }


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

def start_session(lab_key: str, challenge_name: str) -> dict:
    """
    Locate the challenge in the catalog and initialise a session.
    Does NOT start the Docker lab — caller is responsible for spin_up_lab first.
    """
    if lab_key not in LAB_CATALOG:
        return {"error": f"Unknown lab: {lab_key}"}

    lab = LAB_CATALOG[lab_key]
    challenge_meta = next(
        (c for c in lab["challenges"] if c["name"].lower() == challenge_name.lower()),
        None,
    )
    if challenge_meta is None:
        # Accept partial match
        challenge_meta = next(
            (c for c in lab["challenges"] if challenge_name.lower() in c["name"].lower()),
            None,
        )
    if challenge_meta is None:
        return {"error": f"Challenge '{challenge_name}' not found in {lab_key}"}

    session = _new_session(lab_key, challenge_meta["name"], challenge_meta)
    save_session(session)
    return session


# ---------------------------------------------------------------------------
# Proof-of-exploit validation
# ---------------------------------------------------------------------------

# Negation patterns that flip an apparent success claim into a failure.
# Catches cases like "failed to exploit", "could not exploit", "unable to exploit".
_NEGATION_NEAR_EXPLOIT = re.compile(
    r"(?:failed|fail|could\s*not|couldn'?t|unable|did\s*not|didn'?t|no\s+luck|"
    r"not\s+able|was\s+not|wasn'?t|no\s+success|unsuccessful|blocked|rejected|"
    r"sanitiz|prevented|denied)\W{0,40}(?:to\s+)?exploit"
    r"|exploit\W{0,40}(?:failed|fail|blocked|rejected|prevented|denied|unsuccessful)",
    re.IGNORECASE
)

# Signals that indicate genuine technical evidence rather than a vague claim.
_EVIDENCE_SIGNALS = [
    r"HTTP/\d\.\d\s+\d{3}",              # HTTP status line
    r"\b\d{3}\s+(OK|Found|Forbidden|Internal Server Error)\b",
    r"root:.*:0:0:",                      # /etc/passwd style dump
    r"uid=\d+.*gid=\d+",                  # id command output
    r"flag\{.*?\}",                       # CTF-style flag
    r"[A-Za-z0-9+/]{20,}={0,2}",          # base64-looking blob (extracted data)
    r"mysql|SELECT.*FROM|UNION\s+SELECT", # SQL evidence
    r"<script>|onerror=|onload=",         # XSS payload reflected
    r"\bshell\b.*\$|#\s*$",               # shell prompt in output
    r"\b(?:200|301|302)\b.*\b(?:bytes|Content-Length)\b",
]
_EVIDENCE_SIGNAL_RE = re.compile("|".join(_EVIDENCE_SIGNALS), re.IGNORECASE)


def _validate_proof_of_exploit(session: dict, evidence: str, payload: str) -> dict:
    """
    Verify a claimed exploitation is backed by real evidence, not just a self-report.

    Design principle: payload execution is a HARD GATE, not a soft scoring signal.
    If the claimed payload never appears in an actual executed tool call, the claim
    is rejected outright — no amount of "good-sounding" evidence text can compensate,
    because generic output (HTTP status lines, boilerplate) can coincidentally match
    evidence text even when nothing was actually exploited.

    Returns {"valid": bool, "confidence": int, "reasons": [str, ...]}
    """
    reasons = []
    confidence = 0

    evidence = (evidence or "").strip()
    payload = (payload or "").strip()

    if len(evidence) < 15:
        return {"valid": False, "confidence": 0, "reasons": ["Evidence too short or missing — no real proof provided."]}
    if len(payload) < 2:
        return {"valid": False, "confidence": 0, "reasons": ["No payload provided — cannot verify what was executed."]}

    # Gather all raw tool output/args text from the session's actual steps
    all_step_text = []
    all_step_args_text = []
    for step in session.get("steps", []):
        result = step.get("result", {})
        args = step.get("args", {})
        if isinstance(result, dict):
            all_step_text.append(json.dumps(result))
        elif isinstance(result, str):
            all_step_text.append(result)
        if isinstance(args, dict):
            all_step_args_text.append(json.dumps(args))
        elif isinstance(args, str):
            all_step_args_text.append(args)

    combined_output = "\n".join(all_step_text)
    combined_args = "\n".join(all_step_args_text)

    # ---- HARD GATE 1: was the claimed payload actually executed? ----
    payload_fragment = payload[:40] if len(payload) > 40 else payload
    payload_executed = bool(payload_fragment) and payload_fragment.lower() in combined_args.lower()
    if not payload_executed:
        return {
            "valid": False, "confidence": 10,
            "reasons": ["HARD FAIL: claimed payload was never found in any executed tool call. "
                       "The model may be reporting a fabricated or hypothetical exploit."]
        }
    confidence += 35

    # ---- HARD GATE 2: does the evidence match real tool output, using a fragment ----
    # long enough (and specific enough) that generic boilerplate can't false-match.
    # Generic HTTP status lines / short common substrings are excluded from matching.
    GENERIC_FRAGMENTS = re.compile(r"^(?:HTTP/\d\.\d\s+\d{3}|OK|Content-Type|Content-Length)", re.IGNORECASE)
    evidence_fragment_found = False
    min_frag_len = 25  # long enough that boilerplate can't coincidentally match
    if len(evidence) >= min_frag_len:
        for i in range(0, len(evidence) - min_frag_len, min_frag_len // 2):
            frag = evidence[i:i + min_frag_len].strip()
            if not frag or GENERIC_FRAGMENTS.match(frag):
                continue
            if frag.lower() in combined_output.lower():
                evidence_fragment_found = True
                break
    if not evidence_fragment_found:
        return {
            "valid": False, "confidence": 35,
            "reasons": ["HARD FAIL: evidence text does not match any actual tool output from this session "
                       "(after excluding generic boilerplate). Payload was executed but claimed result "
                       "could not be verified against real output."]
        }
    confidence += 35

    # ---- Supporting signal: concrete technical evidence present ----
    if _EVIDENCE_SIGNAL_RE.search(evidence) or _EVIDENCE_SIGNAL_RE.search(combined_output):
        confidence += 20
    else:
        reasons.append("No additional concrete technical signal found (still passed hard gates).")

    generic_phrases = [
        "successfully exploited", "vulnerability confirmed", "exploit successful",
        "attack worked", "confirmed the vulnerability", "proved the vulnerability"
    ]
    if not any(p in evidence.lower() for p in generic_phrases) or len(evidence) >= 60:
        confidence += 10

    valid = True  # both hard gates passed
    if not reasons:
        reasons.append("Payload confirmed executed and evidence confirmed present in real tool output.")

    return {"valid": valid, "confidence": min(100, confidence), "reasons": reasons}


def score_session(session: dict) -> dict:
    """Score a completed session."""
    steps = session.get("steps", [])
    step_count = len(steps)

    if step_count <= 5:
        efficiency_rating = "excellent"
    elif step_count <= 10:
        efficiency_rating = "good"
    elif step_count <= 20:
        efficiency_rating = "fair"
    else:
        efficiency_rating = "poor"

    # Determine if completed by checking final task_complete step
    found_vulnerability = False
    successfully_exploited = False
    claimed_evidence = ""
    claimed_payload = ""
    proof = {"valid": False, "confidence": 0, "reasons": ["No task_complete result found."]}

    for step in reversed(steps):
        result = step.get("result", {})
        if isinstance(result, dict):
            if result.get("found_vulnerability"):
                found_vulnerability = True
            claimed_evidence = result.get("evidence", "")
            claimed_payload = result.get("payload", "")
            if result.get("successfully_exploited"):
                # Do NOT trust this claim directly — validate it against real evidence first.
                proof = _validate_proof_of_exploit(session, claimed_evidence, claimed_payload)
                successfully_exploited = proof["valid"]
                found_vulnerability = found_vulnerability or successfully_exploited
            if found_vulnerability or "successfully_exploited" in result:
                break
        elif isinstance(result, str):
            # Fixed: check for negation before treating "exploit" mention as success.
            # Old bug: "Failed to exploit the endpoint" contained "exploit" and was
            # incorrectly scored as a successful exploitation.
            if _NEGATION_NEAR_EXPLOIT.search(result):
                break  # explicit failure signal — stop looking, this is not a success
            if "exploit" in result.lower():
                # Weak signal from an unstructured string — still requires proof.
                proof = _validate_proof_of_exploit(session, result, "")
                successfully_exploited = proof["valid"]
                found_vulnerability = successfully_exploited
                break

    efficiency_bonus = step_count <= 5 and successfully_exploited
    first_time = _is_first_time(session["lab_key"], session["challenge"])

    base_xp = session.get("base_xp", 100)
    if not successfully_exploited:
        base_xp = int(base_xp * 0.3)  # Partial credit for attempt
    if not found_vulnerability:
        base_xp = 0

    xp_result = award_xp(
        skill_domain=session.get("skill_domain", "web_app"),
        base_xp=base_xp,
        efficiency_bonus=efficiency_bonus,
        first_time=first_time,
    )

    score = {
        "found_vulnerability": found_vulnerability,
        "successfully_exploited": successfully_exploited,
        "proof_of_exploit": proof,
        "step_count": step_count,
        "efficiency_rating": efficiency_rating,
        "xp_earned": xp_result.get("xp_awarded", 0),
        "skill_domain": session.get("skill_domain", "web_app"),
        "leveled_up": xp_result.get("leveled_up", False),
        "new_level": xp_result.get("new_level", 1),
        "new_title": xp_result.get("new_title", ""),
    }

    # Track speed runner achievement
    if session.get("difficulty") == "hard" and step_count <= 5 and successfully_exploited:
        prog = load_progression()
        prog["speed_runner_earned"] = True
        save_progression(prog)

    # Track per-challenge completion for completionist
    _record_challenge_completion(session, successfully_exploited=successfully_exploited)

    return score


def _is_first_time(lab_key: str, challenge_name: str) -> bool:
    """Return True if this challenge has never been completed before."""
    history = get_session_history(limit=200)
    for s in history:
        if (s.get("lab_key") == lab_key
                and s.get("challenge") == challenge_name
                and s.get("score", {}).get("successfully_exploited")):
            return False
    return True


def _record_challenge_completion(session: dict, successfully_exploited: bool = False) -> None:
    """Update per-domain challenge count and check completionist."""
    domain = session.get("skill_domain", "web_app")
    prog = load_progression()

    key = f"{domain}_challenges_completed"
    prog[key] = prog.get(key, 0) + 1
    prog["total_challenges_completed"] = prog.get("total_challenges_completed", 0) + 1

    # Completionist: check if all challenges in this lab are done
    lab_key = session.get("lab_key", "")
    if lab_key in LAB_CATALOG and successfully_exploited:
        lab_challenges = [c["name"] for c in LAB_CATALOG[lab_key]["challenges"]]
        history = get_session_history(limit=500)
        completed_in_lab = {
            s["challenge"] for s in history
            if s.get("lab_key") == lab_key and s.get("score", {}).get("successfully_exploited")
        }
        completed_in_lab.add(session["challenge"])

        if all(c in completed_in_lab for c in lab_challenges):
            prog["completionist_lab"] = LAB_CATALOG[lab_key]["name"]

    save_progression(prog)


# ---------------------------------------------------------------------------
# Learning extraction
# ---------------------------------------------------------------------------

def extract_learnings(session: dict) -> list[dict]:
    """Extract technique/command pairs from session steps."""
    learnings: list[dict] = []
    seen: set[str] = set()

    for step in session.get("steps", []):
        action = step.get("action", "")
        args = step.get("args", {})
        result = step.get("result", {})

        # Extract from task_complete payload
        if isinstance(result, dict) and "learnings" in result:
            for item in result["learnings"]:
                key = item.get("technique", "") + item.get("command", "")
                if key and key not in seen:
                    seen.add(key)
                    learnings.append({
                        "technique": item.get("technique", ""),
                        "command": item.get("command", ""),
                        "context": item.get("context", ""),
                        "verified": True,
                    })

        # Extract from run_command_in_lab calls that succeeded
        if action == "run_command_in_lab" and isinstance(result, dict) and result.get("success"):
            cmd = args.get("command", "")
            if cmd and cmd not in seen:
                seen.add(cmd)
                think = step.get("think", "")
                learnings.append({
                    "technique": _infer_technique(cmd),
                    "command": cmd,
                    "context": think[:200] if think else "",
                    "verified": True,
                })

    return learnings


def _infer_technique(command: str) -> str:
    """Heuristically label a shell command with a technique name."""
    cmd_lower = command.lower()
    if "sqlmap" in cmd_lower:
        return "SQLMap automated injection"
    if "' or " in cmd_lower or "union select" in cmd_lower:
        return "Manual SQL injection"
    if "curl" in cmd_lower and "cookie" in cmd_lower:
        return "Cookie manipulation / authenticated request"
    if "nikto" in cmd_lower:
        return "Nikto web scan"
    if "nmap" in cmd_lower:
        return "Nmap port/service scan"
    if "hydra" in cmd_lower or "medusa" in cmd_lower:
        return "Brute force login"
    if "curl" in cmd_lower:
        return "HTTP request via curl"
    if "python" in cmd_lower or "python3" in cmd_lower:
        return "Python script"
    return "Shell command"


# ---------------------------------------------------------------------------
# Full autonomous session runner
# ---------------------------------------------------------------------------

def run_full_session(
    lab_key: str,
    challenge_name: str,
    settings: dict,
    stream_callback: Optional[Callable[[dict], None]] = None,
    max_steps: int = 30,
) -> dict:
    """
    Run a complete autonomous practice session.
    Spins up the lab, runs the agent, scores and saves the result.
    stream_callback receives each agent event dict as it happens.
    """
    # Ensure lab is running
    lab_result = spin_up_lab(lab_key)
    if not lab_result.get("success"):
        return {"error": f"Failed to start lab: {lab_result.get('message')}"}

    lab = LAB_CATALOG[lab_key]
    lab_url = lab_result.get("url", lab["url"])
    lab_creds = lab.get("default_creds", {})

    # Initialise session
    session = start_session(lab_key, challenge_name)
    if "error" in session:
        return session

    # Build agent goal
    goal = (
        f"Practice challenge: {challenge_name}\n"
        f"Lab: {lab['name']}\n"
        f"URL: {lab_url}\n"
        f"Default credentials: {lab_creds}\n"
        f"Difficulty: {session['difficulty']}\n\n"
        f"Your goal is to find and exploit the '{challenge_name}' vulnerability in this lab. "
        f"Think carefully, enumerate first, then attack. "
        f"When done, call task_complete with your findings."
    )

    # Override system prompt with practice mode prompt
    practice_settings = dict(settings)
    practice_settings["system_prompt"] = PRACTICE_MODE_PROMPT
    practice_settings["max_steps"] = max_steps

    # Update session step count in progression
    prog = load_progression()
    prog["total_sessions"] = prog.get("total_sessions", 0) + 1
    save_progression(prog)

    # Run agent
    step_num = 0
    for event in run_agent_streaming(goal, practice_settings):
        event_type = event.get("type", "")

        if event_type == "agent_step":
            step_num += 1
            step_data = {
                "step_num": step_num,
                "think": event.get("think", ""),
                "action": event.get("action", ""),
                "args": event.get("args", {}),
                "result": event.get("result", {}),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            session["steps"].append(step_data)
            save_session(session)

        elif event_type == "agent_complete":
            session["status"] = "completed"
            session["completed_at"] = datetime.now(timezone.utc).isoformat()

        elif event_type == "agent_error":
            session["status"] = "failed"
            session["completed_at"] = datetime.now(timezone.utc).isoformat()

        if stream_callback:
            stream_callback(event)

    # Score the session
    if session["status"] == "in_progress":
        session["status"] = "completed"
        session["completed_at"] = datetime.now(timezone.utc).isoformat()

    score = score_session(session)
    session["score"] = score
    session["learnings"] = extract_learnings(session)

    # Check for newly unlocked achievements
    prog = load_progression()
    new_achievements = check_achievements(prog)
    session["new_achievements"] = new_achievements

    save_session(session)

    if stream_callback:
        stream_callback({
            "type": "session_complete",
            "session_id": session["session_id"],
            "score": score,
            "new_achievements": new_achievements,
        })

    return session


# ---------------------------------------------------------------------------
# Session persistence
# ---------------------------------------------------------------------------

def save_session(session: dict) -> str:
    """Save session JSON. Returns file path."""
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    path = os.path.join(SESSIONS_DIR, f"{session['session_id']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(session, f, indent=2, ensure_ascii=False)
    return path


def load_session(session_id: str) -> dict:
    path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
    if not os.path.exists(path):
        return {"error": f"Session not found: {session_id}"}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_session_history(limit: int = 20) -> list[dict]:
    """Return most recent sessions (sorted newest-first)."""
    if not os.path.exists(SESSIONS_DIR):
        return []
    files = [
        os.path.join(SESSIONS_DIR, f)
        for f in os.listdir(SESSIONS_DIR)
        if f.endswith(".json")
    ]
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    sessions: list[dict] = []
    for fpath in files[:limit]:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                sessions.append(json.load(f))
        except Exception:
            continue
    return sessions


def get_lab_completion_stats() -> dict:
    """Return per-lab challenge completion stats."""
    history = get_session_history(limit=500)
    stats: dict[str, dict] = {}

    for lab_key, lab in LAB_CATALOG.items():
        completed = {
            s["challenge"] for s in history
            if s.get("lab_key") == lab_key and s.get("score", {}).get("successfully_exploited")
        }
        total = len(lab["challenges"])
        stats[lab_key] = {
            "name": lab["name"],
            "total_challenges": total,
            "completed_challenges": len(completed),
            "completed_names": list(completed),
            "percent_complete": int((len(completed) / total) * 100) if total else 0,
        }

    return stats