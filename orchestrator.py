"""
orchestrator.py — Multi-agent dispatcher for Atherix AGI.

Design choice, and why: rather than standing up separate model instances or a
message-passing framework, each "agent" here is just run_agent() called with a
different (system_prompt, allowed_tools) pair. This is deliberately the cheapest
version of multi-agent that's still real:
  - Specialization is real (a persona literally cannot see or call tools outside
    its lane — enforced by the allowed_tools patch, not just prompted).
  - Handoff is real (each subtask gets the prior subtasks' findings as context).
  - It runs on your one Ollama instance sequentially, which matches your hardware
    (one local model, one inference stream) — no fake parallelism to manage.

If you later want true concurrency (e.g. researcher and coder working at once),
that's a follow-on: swap the sequential for-loop in run_multi_agent() for asyncio
+ multiple Ollama requests, since Ollama can serve concurrent requests. Not done
here because it adds real complexity (shared state races, output ordering) for a
gain that doesn't matter until your task volume actually needs it.
"""
from __future__ import annotations
import json
from datetime import datetime

from agent_core import run_agent, AGENT_SYSTEM_PROMPT
from intelligence import call_llm

try:
    from progression import award_xp
except ImportError:
    award_xp = None


# ---------------------------------------------------------------------------
# Personas — each maps to a skill domain from skill_domains.py
# ---------------------------------------------------------------------------

AGENT_PERSONAS: dict[str, dict] = {
    "researcher": {
        "skill_domain": "research_synthesis",
        "system_prompt": AGENT_SYSTEM_PROMPT.split("{tools}")[0] + """
You are the RESEARCH agent. Your only job is finding and verifying information.
Do not write application code. Do not attempt long-horizon planning — you're
given one focused research question, answer it thoroughly, cite what you found,
and call task_complete with a clear written summary of findings.
""",
        "allowed_tools": [
            "web_search", "fetch_url", "fetch_and_analyze_url", "search_docs",
            "search_github", "fetch_github_file", "search_error",
            "check_latest_version", "get_package_changelog", "task_complete",
        ],
    },
    "coder": {
        "skill_domain": "code_generation",
        "system_prompt": AGENT_SYSTEM_PROMPT.split("{tools}")[0] + """
You are the CODE agent. Your only job is writing, testing, and fixing code for
the specific subtask you're given. Use RESEARCH_CONTEXT below if provided
instead of re-researching from scratch. Test what you write. Call task_complete
with a summary of what was built and where.
""",
        "allowed_tools": [
            "run_command", "run_python", "read_file", "write_file", "list_files",
            "search_in_files", "pip_install", "check_env", "search_error",
            "search_docs", "analyze_code", "task_complete",
        ],
    },
    "critic": {
        "skill_domain": "self_correction",
        "system_prompt": AGENT_SYSTEM_PROMPT.split("{tools}")[0] + """
You are the CRITIC agent. You do not create new work. You are given the combined
output of other agents for one goal. Your job: find concrete problems — code
that wasn't actually tested, claims without a source, steps that were skipped,
contradictions between subtask outputs. If something is wrong, say exactly what
and why. If it genuinely holds up, say so plainly — don't invent problems to
seem thorough. Call task_complete with your verdict and the specific issues (or
none) found.
""",
        "allowed_tools": [
            "read_file", "run_python", "run_command", "search_in_files",
            "task_complete",
        ],
    },
}


# ---------------------------------------------------------------------------
# Planner — decomposes a goal into subtasks, each tagged with a persona
# ---------------------------------------------------------------------------

PLANNER_PROMPT = """You are the PLANNING layer for a multi-agent system. You do not \
execute anything yourself. Given a goal, break it into 1-4 concrete subtasks. \
Each subtask must be assigned to exactly one of these agents:

- researcher: finding/verifying information, no code, no file writing
- coder: writing/testing/fixing code, assumes any needed research is already done
- (do not assign anything to "critic" — it always runs last automatically)

Respond ONLY with valid JSON, no other text, in this exact shape:
{{
  "subtasks": [
    {{"persona": "researcher", "task": "specific question to answer"}},
    {{"persona": "coder", "task": "specific thing to build, referencing what research will provide"}}
  ]
}}

If the goal is simple enough for one agent, return a single subtask. Do not
over-decompose — only split when a step genuinely depends on information the
other step doesn't have yet.

GOAL: {goal}"""


def plan_subtasks(goal: str, settings: dict | None = None) -> list[dict]:
    """Ask the model to decompose a goal into persona-tagged subtasks."""
    settings = settings or {}
    messages = [{"role": "user", "content": PLANNER_PROMPT.format(goal=goal)}]
    try:
        raw = call_llm(messages, settings=settings, max_tokens=1024)
        text = raw if isinstance(raw, str) else raw.get("content", "")
        text = text.strip()
        # tolerate accidental markdown fencing
        if text.startswith("```"):
            text = text.strip("`")
            text = text.split("\n", 1)[1] if "\n" in text else text
            text = text.rsplit("```", 1)[0]
        parsed = json.loads(text)
        subtasks = parsed.get("subtasks", [])
        subtasks = [s for s in subtasks if s.get("persona") in ("researcher", "coder")]
        if subtasks:
            return subtasks
    except Exception as e:
        print(f"[Orchestrator] Planning failed, falling back to single-agent: {e}")

    # Fallback: no valid plan parsed — treat the whole goal as one coder subtask.
    # (Safer default than silently dropping the goal.)
    return [{"persona": "coder", "task": goal}]


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_multi_agent(goal: str, settings: dict | None = None, on_step=None, on_complete=None) -> dict:
    """
    Decompose goal -> run each subtask with its specialist persona (sequential,
    each getting prior findings as context) -> run critic pass -> return combined result.
    """
    settings = settings or {}
    started = datetime.now().isoformat()
    subtasks = plan_subtasks(goal, settings)

    if on_step:
        on_step(0, f"Planned {len(subtasks)} subtask(s)", "plan", {"subtasks": subtasks})

    accumulated_context = ""
    subtask_results = []

    for i, sub in enumerate(subtasks, start=1):
        persona_key = sub["persona"]
        persona = AGENT_PERSONAS[persona_key]
        task_text = sub["task"]

        prefixed_goal = task_text
        if accumulated_context:
            prefixed_goal = f"{task_text}\n\nRESEARCH_CONTEXT so far:\n{accumulated_context[:4000]}"

        sub_settings = dict(settings)
        sub_settings["system_prompt"] = persona["system_prompt"]
        sub_settings["allowed_tools"] = persona["allowed_tools"]

        if on_step:
            on_step(i, f"Dispatching to {persona_key}", task_text, {})

        result = run_agent(prefixed_goal, settings=sub_settings, on_step=on_step)
        summary = result.get("summary", "")
        subtask_results.append({"persona": persona_key, "task": task_text, "summary": summary})
        accumulated_context += f"\n[{persona_key}] {task_text} -> {summary}\n"

        if award_xp:
            try:
                award_xp(persona["skill_domain"], base_xp=100)
            except Exception:
                pass

    # Critic pass — reviews everything produced above
    critic = AGENT_PERSONAS["critic"]
    critic_goal = (
        f"ORIGINAL GOAL: {goal}\n\nCOMBINED AGENT OUTPUT TO REVIEW:\n{accumulated_context[:6000]}"
    )
    critic_settings = dict(settings)
    critic_settings["system_prompt"] = critic["system_prompt"]
    critic_settings["allowed_tools"] = critic["allowed_tools"]

    if on_step:
        on_step(len(subtasks) + 1, "Running critic pass", "critique", {})

    critic_result = run_agent(critic_goal, settings=critic_settings, on_step=on_step)
    critic_summary = critic_result.get("summary", "")

    if award_xp:
        try:
            award_xp(critic["skill_domain"], base_xp=75)
        except Exception:
            pass

    final = {
        "goal": goal,
        "started": started,
        "completed": datetime.now().isoformat(),
        "subtasks": subtask_results,
        "critic_review": critic_summary,
    }

    if on_complete:
        on_complete(final)

    return final
