"""
autonomous_curiosity.py — Self-tasking extension to the existing _curiosity_loop
in atherix_red_app.py.

What changes vs. the original: the original cycle calls verify_and_store(topic)
and just records the verdict — it never acts on what it finds. This version
still runs on the same schedule with the same topic list, but when a result
comes back UNVERIFIED or DISPUTED, it treats that as a real signal ("I don't
actually know this, or sources disagree") and spawns a bounded follow-up
research task through the multi-agent orchestrator to dig deeper, then stores
the deeper finding back into curiosity_state.

Honesty note for Min: this is NOT a fully autonomous agent choosing its own
goals from nothing. It's still bounded to the CURIOSITY_TOPICS list and the
24h schedule you already had. What's new is that it now *acts* on ambiguous
results instead of just logging them — a small, real, bounded form of
self-tasking, not general autonomy.
"""
import time as _time
from datetime import datetime

from knowledge_verifier import verify_and_store
from orchestrator import run_multi_agent

# How many ambiguous topics to actually chase per cycle — deliberately small,
# since each follow-up is a full multi-agent run (researcher + critic), not
# a cheap single search call. Keep this low to keep cycle time and cost sane.
MAX_FOLLOWUPS_PER_CYCLE = 2


def _needs_followup(verdict: str) -> bool:
    return verdict in ("UNVERIFIED", "DISPUTED")


def run_autonomous_curiosity_cycle(state: dict, topics: list[str], num_topics: int = 6) -> dict:
    """
    Drop-in replacement for _run_curiosity_cycle(state) in atherix_red_app.py.
    NOTE: the real call sites pass CURIOSITY_TOPICS explicitly as `topics` —
    the original function read it from a module-level global instead, which
    this version can't do without a circular import back into atherix_red_app.
    See PATCH notes for the two call-site edits this requires.

    Same state mutation contract as the original, same topic sampling
    behavior, PLUS the original's GitHub lab discovery step (preserved here
    so this stays a true drop-in and doesn't silently lose that feature),
    PLUS the new follow-up spawning step.
    """
    import random
    shuffled = topics.copy()
    random.shuffle(shuffled)
    sample = shuffled[:num_topics]

    learned = []
    followups_run = 0

    print(f"[Curiosity] Cycle #{state.get('run_count', 0) + 1} starting — {len(sample)} topics")

    for topic in sample:
        try:
            result = verify_and_store(topic)
            verdict = result.get("verdict", "UNVERIFIED")
            conf = result.get("confidence", 0)
            entry = {
                "topic": topic,
                "verdict": verdict,
                "confidence": conf,
                "timestamp": datetime.now().isoformat(),
                "followup_spawned": False,
            }

            print(f"[Curiosity] {'✓' if verdict == 'VERIFIED' else '~'} {topic[:60]} ({verdict}, {conf}%)")

            if _needs_followup(verdict) and followups_run < MAX_FOLLOWUPS_PER_CYCLE:
                print(f"[Curiosity] Ambiguous result on '{topic[:50]}' — spawning follow-up research task")
                followup_goal = (
                    f"The claim/topic '{topic}' came back {verdict} with only {conf}% confidence "
                    f"from initial verification. Research this specifically: find why sources "
                    f"disagree or why it couldn't be verified, and report what's actually true "
                    f"as best you can determine."
                )
                try:
                    followup_result = run_multi_agent(followup_goal)
                    entry["followup_spawned"] = True
                    entry["followup_summary"] = followup_result.get("critic_review", "")[:1500]
                    followups_run += 1
                except Exception as e:
                    print(f"[Curiosity] Follow-up task failed: {e}")
                    entry["followup_error"] = str(e)

            learned.append(entry)

        except Exception as e:
            print(f"[Curiosity] Error on topic '{topic[:40]}': {e}")

        _time.sleep(2)

    state["topics_learned"] = (state.get("topics_learned", []) + learned)[-100:]
    state["followups_run_last_cycle"] = followups_run

    # GitHub lab discovery — preserved from the original _run_curiosity_cycle,
    # unrelated to topic verification but was part of the same cycle before.
    try:
        from lab_manager import discover_new_labs
        new_labs = discover_new_labs()
        if new_labs:
            state["new_labs_found"] = (state.get("new_labs_found", []) + new_labs)[-20:]
            print(f"[Curiosity] Found {len(new_labs)} potential new labs")
    except Exception as e:
        print(f"[Curiosity] Lab discovery error: {e}")

    print(f"[Curiosity] Cycle complete — {len(learned)} topics, {followups_run} follow-up task(s) spawned")
    return state
