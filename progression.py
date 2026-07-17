"""
progression.py — XP/leveling system for Atherix Red.
Standalone: only reads/writes JSON (no other Atherix imports).
"""

import json
import os
from datetime import datetime, timezone

PROGRESSION_FILE = "C:\\atherix-red\\progression.json"

# ---------------------------------------------------------------------------
# Skill domains
# ---------------------------------------------------------------------------

SKILL_DOMAINS: dict[str, dict] = {
    "web_app": {"name": "Web Application Hacking", "icon": "🌐", "color": "#e63946"},
    "network": {"name": "Network & Infrastructure", "icon": "🔌", "color": "#3498db"},
    "linux_privesc": {"name": "Linux Privilege Escalation", "icon": "🐧", "color": "#2ecc71"},
    "windows_privesc": {"name": "Windows Privilege Escalation", "icon": "🪟", "color": "#9b59b6"},
    "active_directory": {"name": "Active Directory", "icon": "🏰", "color": "#f39c12"},
    "recon": {"name": "Reconnaissance & OSINT", "icon": "🔭", "color": "#1abc9c"},
    "crypto_passwords": {"name": "Cryptography & Password Attacks", "icon": "🔑", "color": "#e67e22"},
}

# XP thresholds for levels 1–10 (index = level, index 0 unused)
LEVEL_XP = [0, 0, 500, 1500, 3000, 5500, 9000, 14000, 21000, 30000, 41500, 55000]

LEVEL_TITLES: dict[int, str] = {
    1: "Beginner",
    2: "Script Kiddie",
    3: "Apprentice",
    4: "Practitioner",
    5: "Specialist",
    6: "Expert",
    7: "Senior Expert",
    8: "Elite",
    9: "Master",
    10: "Mythic",
}

# (average_level_threshold, rank_name)
OVERALL_RANKS: list[tuple[float, str]] = [
    (1.0, "Civilian"),
    (2.0, "Curious"),
    (3.0, "Learner"),
    (4.0, "Hacker in Training"),
    (5.0, "Ethical Hacker"),
    (6.0, "Red Teamer"),
    (7.0, "Penetration Tester"),
    (8.0, "Senior Pentester"),
    (9.0, "Security Researcher"),
    (10.0, "Elite Threat Actor"),
]

MAX_LEVEL = 10


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _default_progression() -> dict:
    data: dict = {}
    for domain in SKILL_DOMAINS:
        data[domain] = {"xp": 0, "level": 1}
    data["total_sessions"] = 0
    data["total_challenges_completed"] = 0
    data["achievements"] = []
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    return data


def load_progression() -> dict:
    if not os.path.exists(PROGRESSION_FILE):
        prog = _default_progression()
        save_progression(prog)
        return prog
    try:
        with open(PROGRESSION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return _default_progression()


def save_progression(data: dict) -> None:
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    try:
        with open(PROGRESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Level math
# ---------------------------------------------------------------------------

def calculate_level(xp: int) -> int:
    """Return level 1–10 for a given XP total."""
    level = 1
    for lvl in range(1, MAX_LEVEL + 1):
        if xp >= LEVEL_XP[lvl]:
            level = lvl
        else:
            break
    return min(level, MAX_LEVEL)


def xp_to_next_level(xp: int) -> dict:
    """Return progress info toward next level."""
    current_level = calculate_level(xp)
    if current_level >= MAX_LEVEL:
        return {
            "current_level": MAX_LEVEL,
            "xp_in_level": xp - LEVEL_XP[MAX_LEVEL],
            "xp_needed": 0,
            "percent": 100,
        }
    current_floor = LEVEL_XP[current_level]
    next_floor = LEVEL_XP[current_level + 1]
    xp_in_level = xp - current_floor
    xp_span = next_floor - current_floor
    percent = int((xp_in_level / xp_span) * 100) if xp_span > 0 else 100
    return {
        "current_level": current_level,
        "xp_in_level": xp_in_level,
        "xp_needed": max(0, next_floor - xp),
        "percent": min(100, percent),
    }


# ---------------------------------------------------------------------------
# Award XP
# ---------------------------------------------------------------------------

def award_xp(
    skill_domain: str,
    base_xp: int,
    efficiency_bonus: bool = False,
    first_time: bool = False,
    multi_skill: bool = False,
) -> dict:
    """
    Award XP to a skill domain with optional multipliers.
    efficiency_bonus: 1.5× (completed fast)
    first_time: 1.25× (first time completing this challenge)
    multi_skill: 1.15× (challenge touches multiple domains)
    Returns detailed result dict.
    """
    if skill_domain not in SKILL_DOMAINS:
        return {"error": f"Unknown skill domain: {skill_domain}"}

    prog = load_progression()

    # Ensure domain exists
    if skill_domain not in prog:
        prog[skill_domain] = {"xp": 0, "level": 1}

    # Calculate multipliers
    multiplier = 1.0
    if efficiency_bonus:
        multiplier *= 1.5
    if first_time:
        multiplier *= 1.25
    if multi_skill:
        multiplier *= 1.15

    xp_awarded = int(base_xp * multiplier)

    old_xp = prog[skill_domain]["xp"]
    old_level = calculate_level(old_xp)

    new_xp = old_xp + xp_awarded
    new_level = calculate_level(new_xp)
    leveled_up = new_level > old_level

    prog[skill_domain]["xp"] = new_xp
    prog[skill_domain]["level"] = new_level

    progress = xp_to_next_level(new_xp)
    save_progression(prog)

    return {
        "domain": skill_domain,
        "domain_name": SKILL_DOMAINS[skill_domain]["name"],
        "xp_awarded": xp_awarded,
        "base_xp": base_xp,
        "multiplier": multiplier,
        "new_total_xp": new_xp,
        "old_level": old_level,
        "new_level": new_level,
        "new_title": LEVEL_TITLES.get(new_level, ""),
        "leveled_up": leveled_up,
        "xp_to_next": progress["xp_needed"],
        "percent_to_next": progress["percent"],
    }


# ---------------------------------------------------------------------------
# Full progression snapshot
# ---------------------------------------------------------------------------

def _average_level(prog: dict) -> float:
    levels = [prog.get(d, {}).get("level", 1) for d in SKILL_DOMAINS]
    return sum(levels) / len(levels) if levels else 1.0


def _get_rank(avg_level: float) -> str:
    rank = "Civilian"
    for threshold, name in OVERALL_RANKS:
        if avg_level >= threshold:
            rank = name
    return rank


def get_full_progression() -> dict:
    """Return complete progression snapshot including rank, domains, and achievements."""
    prog = load_progression()

    domains: dict[str, dict] = {}
    for domain_key, meta in SKILL_DOMAINS.items():
        entry = prog.get(domain_key, {"xp": 0, "level": 1})
        xp = entry.get("xp", 0)
        level = calculate_level(xp)
        progress = xp_to_next_level(xp)
        domains[domain_key] = {
            "key": domain_key,
            "name": meta["name"],
            "icon": meta["icon"],
            "color": meta["color"],
            "xp": xp,
            "level": level,
            "title": LEVEL_TITLES.get(level, ""),
            "xp_in_level": progress["xp_in_level"],
            "xp_needed": progress["xp_needed"],
            "percent": progress["percent"],
        }

    avg = _average_level(prog)
    rank = _get_rank(avg)

    achievements = check_achievements(prog)

    return {
        "domains": domains,
        "overall_rank": rank,
        "average_level": round(avg, 2),
        "total_sessions": prog.get("total_sessions", 0),
        "total_challenges": prog.get("total_challenges_completed", 0),
        "achievements": prog.get("achievements", []),
        "new_achievements": achievements,
    }


# ---------------------------------------------------------------------------
# Achievements
# ---------------------------------------------------------------------------

def check_achievements(progression: dict) -> list[dict]:
    """
    Check for newly unlocked achievements.
    Returns list of newly earned achievement dicts.
    Saves newly earned achievements back to file.
    """
    earned_names = {a["name"] for a in progression.get("achievements", [])}
    newly_earned: list[dict] = []

    def _domain_level(domain: str) -> int:
        return calculate_level(progression.get(domain, {}).get("xp", 0))

    def _domain_challenges(domain: str) -> int:
        return progression.get(f"{domain}_challenges_completed", 0)

    def _unlock(name: str, description: str, icon: str) -> None:
        if name not in earned_names:
            achievement = {
                "name": name,
                "description": description,
                "icon": icon,
                "earned_at": datetime.now(timezone.utc).isoformat(),
            }
            newly_earned.append(achievement)

    # First Blood — any XP at all
    total_xp = sum(progression.get(d, {}).get("xp", 0) for d in SKILL_DOMAINS)
    if total_xp > 0:
        _unlock("First Blood", "Completed your first practice session.", "🩸")

    # Web Warrior — web_app level 5
    if _domain_level("web_app") >= 5:
        _unlock("Web Warrior", "Reached Level 5 in Web Application Hacking.", "🌐")

    # Network Ninja — 10 network challenges
    if _domain_challenges("network") >= 10:
        _unlock("Network Ninja", "Completed 10 network challenges.", "🥷")

    # Polyglot — level 3 in 5+ domains
    domains_at_3 = sum(1 for d in SKILL_DOMAINS if _domain_level(d) >= 3)
    if domains_at_3 >= 5:
        _unlock("Polyglot", "Reached Level 3 in 5 or more skill domains.", "🧠")

    # Speed Runner — hard challenge in ≤5 steps (stored on progression)
    if progression.get("speed_runner_earned", False):
        _unlock("Speed Runner", "Solved a hard challenge in 5 steps or fewer.", "⚡")

    # Completionist — all challenges in any single lab
    if progression.get("completionist_lab"):
        lab = progression.get("completionist_lab", "a lab")
        _unlock("Completionist", f"Completed every challenge in {lab}.", "🏆")

    # Mythic rank — all domains at level 10
    if all(_domain_level(d) >= 10 for d in SKILL_DOMAINS):
        _unlock("Elite Threat Actor", "Reached Mythic level in all skill domains.", "💀")

    # Save newly earned achievements
    if newly_earned:
        prog = load_progression()
        existing = prog.get("achievements", [])
        existing_names = {a["name"] for a in existing}
        for ach in newly_earned:
            if ach["name"] not in existing_names:
                existing.append(ach)
        prog["achievements"] = existing
        save_progression(prog)

    return newly_earned