"""
Atherix Red - Agent Core
ReAct agent loop with task planning and working memory
"""

import json
import os
import re
import requests
from datetime import datetime
from agent_tools import TOOLS, get_tools_prompt, execute_tool, build_tool_schemas

# ============================================================
# CONFIG
# ============================================================
MODEL = "joe-speedboat/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive:Q4_K_M"
OLLAMA_URL = "http://localhost:11434/api/chat"
BASE_DIR = "C:\\atherix-red"
WORKING_MEMORY_DIR = os.path.join(BASE_DIR, "working_memory")
os.makedirs(WORKING_MEMORY_DIR, exist_ok=True)

AGENT_SYSTEM_PROMPT = """You are Atherix Red Agent. Complete tasks using tools. Be efficient.

RESPONSE FORMAT — use exactly this every time:
THINK: <what you're doing, 1 sentence>
ACT: tool_name(param1="value1", param2="value2")

WHEN DONE:
THINK: Task complete.
ACT: task_complete(summary="what was done and what files were created")

RULES:
- One tool call per response. No exceptions.
- If the task includes file content, use that content directly. Do not try to read the file from disk.
- For code fixes: write the fixed code with write_file, then call task_complete. That's it.
- Do not explain. Do not ask questions. Just act.
- If you hit an error or are unsure: use search_error or web_search to find the answer first.
- If you need documentation or examples: use search_docs then fetch_url on the best result.

CODING WORKFLOW — always follow this order:
1. RESEARCH FIRST: Before writing code for any library or tool you haven't used recently, call search_docs or web_search to get the latest API. Libraries change. Don't guess from memory.
2. FIND EXAMPLES: Use search_github(query, search_type="code") to find real working implementations. Then fetch_github_file on the best result to read the actual code.
3. CHECK DEPS: If you need a package, call check_env(filter="package_name") first. If it's missing, call pip_install before writing code that imports it.
4. WRITE THE CODE: Use write_file to save it. Scripts go in the output dir.
5. TEST IT: Call run_python or run_command to execute it. Read the output.
6. FIX ERRORS: If it fails, call search_error("exact error message", language="python") → fetch_url the top result → apply the fix → re-test.
7. NEVER GUESS: If you don't know the current API signature for a function, look it up. search_docs exists for this exact reason.

RESEARCH TOOLS — use these aggressively:
- search_github(query, search_type="code", language="python") → find working code examples (results include trust scores)
- fetch_github_file(url) → read the actual source code from any GitHub URL
- fetch_and_analyze_url(url) → read ANY web page, blog post, docs page, or paste site
- search_docs(query, library="requests") → official documentation
- web_search(query) → anything else — CVEs, techniques, news, tutorials
- fetch_url(url) → read the full page after a search
- search_error("error message", language="python") → Stack Overflow / GitHub fix
- pip_install(package) → install a missing package
- check_env(filter="package") → check if something is installed

GITHUB TRUST RULES — follow these strictly:
- search_github results include a trust_level: HIGH, MEDIUM, LOW, or SKETCHY
- ONLY use code from HIGH or MEDIUM trust repos. Never copy code from SKETCHY repos.
- Trust is based on: stars, forks, license, age, whether it's an organization.
- If you need code from a LOW trust repo, verify it manually first — read through it for backdoors, hardcoded IPs, suspicious imports, or obfuscated code.
- When presenting GitHub results to the user, always mention the trust level.

URL HANDLING — when the user gives you a link:
- Use fetch_and_analyze_url(url) to read and analyze it
- For GitHub repos, fetch the README and key source files
- For documentation pages, extract the relevant sections
- For blog posts or articles, summarize the actionable content

WEB SEARCH WORKFLOW (use when stuck):
1. search_error("exact error", language="python") → finds Stack Overflow/GitHub fixes
2. fetch_url("top result URL") → reads the full solution
3. Apply the fix and continue

{tools}"""

MAX_AGENT_STEPS = 20

# ============================================================
# WORKING MEMORY
# ============================================================
class WorkingMemory:
    """Persistent working memory for multi-step tasks"""
    
    def __init__(self, task_id):
        self.task_id = task_id
        self.path = os.path.join(WORKING_MEMORY_DIR, f"{task_id}.json")
        self.data = self._load()
    
    def _load(self):
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "task_id": self.task_id,
            "created": datetime.now().isoformat(),
            "goal": "",
            "plan": [],
            "steps": [],
            "findings": [],
            "files_created": [],
            "status": "active"
        }
    
    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
        # Prune old working memory files — keep only the 50 most recent
        try:
            files = sorted(
                [os.path.join(WORKING_MEMORY_DIR, f) for f in os.listdir(WORKING_MEMORY_DIR) if f.endswith(".json")],
                key=os.path.getmtime
            )
            for old in files[:-50]:
                os.remove(old)
        except Exception:
            pass
    
    def set_goal(self, goal):
        self.data["goal"] = goal
        self.save()
    
    def set_plan(self, plan):
        self.data["plan"] = plan
        self.save()
    
    def add_step(self, step_num, thought, action, tool_name, tool_args, result):
        self.data["steps"].append({
            "step": step_num,
            "timestamp": datetime.now().isoformat(),
            "thought": thought,
            "action": action,
            "tool": tool_name,
            "args": tool_args,
            "result_summary": str(result)[:2000]
        })
        self.save()
    
    def add_finding(self, finding):
        self.data["findings"].append({
            "content": finding,
            "timestamp": datetime.now().isoformat()
        })
        self.save()
    
    def add_file(self, path):
        self.data["files_created"].append(path)
        self.save()
    
    def complete(self, summary):
        self.data["status"] = "complete"
        self.data["summary"] = summary
        self.data["completed"] = datetime.now().isoformat()
        self.save()
    
    def get_context(self):
        """Build context string for the agent from working memory"""
        parts = [f"TASK: {self.data['goal']}"]
        if self.data["plan"]:
            parts.append("PLAN: " + " → ".join(self.data["plan"]))
        if self.data["findings"]:
            parts.append("FINDINGS SO FAR:")
            for f in self.data["findings"][-10:]:
                parts.append(f"  - {f['content']}")
        if self.data["steps"]:
            parts.append(f"\nPREVIOUS STEPS ({len(self.data['steps'])} total):")
            # Show last 5 steps in detail
            for s in self.data["steps"][-5:]:
                parts.append(f"  Step {s['step']}: {s['thought'][:200]}")
                parts.append(f"    Action: {s['action'][:150]}")
                parts.append(f"    Result: {s['result_summary'][:300]}")
        return "\n".join(parts)

# ============================================================
# TOOL CALL PARSER
# ============================================================
def parse_agent_response(text):
    """Parse THINK and ACT from agent response — tolerant of format variations"""
    think = ""
    action = ""
    
    if not text or not text.strip():
        return "", None, None, None
    
    # Extract THINK (also accepts Thought:, Reasoning:)
    think_match = re.search(r'(?:THINK|Thought|Reasoning):\s*(.+?)(?=(?:ACT|Action|Tool):|$)', text, re.DOTALL | re.IGNORECASE)
    if think_match:
        think = think_match.group(1).strip()
    
    # Extract ACT (also accepts Action:, Tool:)
    act_match = re.search(r'(?:ACT|Action|Tool):\s*(.+?)(?:\n\n|$)', text, re.DOTALL | re.IGNORECASE)
    if act_match:
        action = act_match.group(1).strip()
    
    # Fallback: if no ACT keyword found, look for any tool_name(...) pattern in the text
    if not action:
        tool_pattern = re.search(r'(\w+)\([^)]*\)', text, re.DOTALL)
        if tool_pattern:
            action = tool_pattern.group(0).strip()
    
    if not action:
        return think or text[:200], None, None, None
    
    # Parse tool call: tool_name(param1="value1", param2="value2")
    tool_match = re.match(r'(\w+)\((.*)\)', action, re.DOTALL)
    if not tool_match:
        return think, action, None, None
    
    tool_name = tool_match.group(1)
    args_str = tool_match.group(2).strip()
    
    # Parse arguments — handle multiline content values
    args = {}
    if args_str:
        # Try JSON-style parsing first for content with newlines
        # Find all key="value" or key=value pairs
        pos = 0
        while pos < len(args_str):
            # Match key=
            key_match = re.match(r'\s*(\w+)\s*=\s*', args_str[pos:])
            if not key_match:
                break
            key = key_match.group(1)
            pos += key_match.end()
            
            if pos >= len(args_str):
                break
            
            # Check if value starts with quote
            if args_str[pos] in ('"', "'"):
                quote = args_str[pos]
                pos += 1
                value = ""
                while pos < len(args_str):
                    if args_str[pos] == '\\' and pos + 1 < len(args_str):
                        c = args_str[pos + 1]
                        if c == 'n': value += '\n'
                        elif c == 't': value += '\t'
                        elif c == quote: value += quote
                        else: value += c
                        pos += 2
                    elif args_str[pos] == quote:
                        pos += 1
                        break
                    else:
                        value += args_str[pos]
                        pos += 1
                args[key] = value
            else:
                # Unquoted value — read until comma or end
                val_match = re.match(r'([^,\)]+)', args_str[pos:])
                if val_match:
                    args[key] = val_match.group(1).strip()
                    pos += val_match.end()
            
            # Skip comma
            comma_match = re.match(r'\s*,\s*', args_str[pos:])
            if comma_match:
                pos += comma_match.end()
    
    return think, action, tool_name, args

# ============================================================
# AGENT LOOP
# ============================================================
def run_agent(goal, settings=None, on_step=None, on_complete=None):
    """
    Run the agent loop for a given goal.
    
    Args:
        goal: The user's task/request
        settings: Dict with model settings
        on_step: Callback(step_num, thought, action, result) for streaming updates
        on_complete: Callback(summary, working_memory) when done
    
    Returns:
        Working memory data
    """
    settings = settings or {}
    think_budget = settings.get("think_budget", 512)
    temperature = settings.get("temperature", 0.7)
    num_ctx = settings.get("num_ctx", 16384)
    
    # Create working memory
    task_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    memory = WorkingMemory(task_id)
    memory.set_goal(goal)
    
    # Build system prompt — allow caller to override (e.g. practice mode)
    allowed_tools = settings.get("allowed_tools")  # None = all tools (unchanged default)
    custom_system = settings.get("system_prompt", "")
    if custom_system:
        system = custom_system + "\n\nAVAILABLE TOOLS:\n" + get_tools_prompt(allowed_tools)
    else:
        system = AGENT_SYSTEM_PROMPT.format(tools=get_tools_prompt(allowed_tools))
    
    # Conversation history for the agent
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"TASK: {goal}\n\nIf file content is included above, use it directly — do NOT try to read or search for the file. Begin now."}
    ]
    
    last_result_str = ""  # Initialize before loop to prevent UnboundLocalError on step 2+
    format_failures = 0
    FORMAT_FAILURE_LIMIT = 2  # after this many consecutive bad-format responses,
                              # stop nagging and just use what the model wrote

    for step in range(1, MAX_AGENT_STEPS + 1):
        # Add working memory context after first step
        if step > 1:
            context = memory.get_context()
            messages[-1] = {
                "role": "user",
                "content": f"RESULT:\n{last_result_str}\n\nContinue. Be concise."
            }
        
        # Call the model
        try:
            resp = requests.post(OLLAMA_URL, json={
                "model": MODEL,
                "options": {
                    "num_ctx": num_ctx,
                    "num_predict": 2048,
                    "temperature": temperature,
                    "top_p": 0.95,
                    "top_k": 20
                },
                "messages": messages,
                "stream": False
            }, timeout=300)
            
            result = resp.json()
            agent_text = result.get("message", {}).get("content", "")
            
        except Exception as e:
            if on_step:
                on_step(step, f"Error communicating with model: {e}", "", {"error": str(e)})
            break
        
        # Parse response
        think, action, tool_name, tool_args = parse_agent_response(agent_text)
        
        if not tool_name:
            # Model didn't output a proper tool call — try to recover
            format_failures += 1
            if format_failures > FORMAT_FAILURE_LIMIT and agent_text.strip():
                # It has clearly produced a real answer, just not in ACT: format.
                # Stop nagging and use its own text rather than burn the rest of
                # MAX_AGENT_STEPS on a correction it isn't going to follow.
                summary = agent_text.strip()
                memory.complete(summary)
                if on_step:
                    on_step(step, think or "", "Format retries exhausted — using model's own answer as completion",
                            {"note": f"gave up correcting format after {format_failures} attempts"})
                if on_complete:
                    on_complete(summary, memory.data)
                return memory.data

            if on_step:
                on_step(step, think or agent_text, "No valid action parsed", {"raw": agent_text[:500]})
            
            # Add correction prompt
            messages.append({"role": "assistant", "content": agent_text})
            messages.append({"role": "user", "content": "Your response didn't follow the required format. Remember: THINK: <reasoning> then ACT: tool_name(param=\"value\"). Try again."})
            continue
        
        format_failures = 0  # reset on any successfully parsed action
        
        # Check for task completion
        if tool_name == "task_complete":
            summary = tool_args.get("summary", "Task completed")
            memory.complete(summary)
            
            if on_step:
                on_step(step, think, f"task_complete", {"summary": summary})
            if on_complete:
                on_complete(summary, memory.data)
            
            return memory.data
        
        # Execute the tool
        tool_result = execute_tool(tool_name, tool_args, allowed=allowed_tools)
        
        # Track file creation
        if tool_name == "write_file" and "path" in (tool_result or {}):
            memory.add_file(tool_result["path"])
        
        # Store step in working memory
        last_result_str = json.dumps(tool_result, indent=2, default=str)[:3000]
        memory.add_step(step, think, action, tool_name, tool_args, tool_result)
        
        # Extract findings from results
        result_text = json.dumps(tool_result, default=str)
        if "vuln" in result_text.lower() or "cve" in result_text.lower() or "exploit" in result_text.lower():
            memory.add_finding(f"Step {step} ({tool_name}): Potential vulnerability found")
        
        # Callback
        if on_step:
            on_step(step, think, f"{tool_name}({json.dumps(tool_args, default=str)[:200]})", tool_result)
        
        # Build message history for next turn
        messages.append({"role": "assistant", "content": agent_text})
        messages.append({"role": "user", "content": f"OBSERVATION:\n{last_result_str}"})
        
        # Keep message history manageable
        if len(messages) > 20:
            # Keep system + first user + last 8 exchanges
            messages = messages[:2] + messages[-16:]
    
    # Hit max steps
    memory.data["status"] = "max_steps_reached"
    memory.save()
    
    if on_complete:
        on_complete("Max steps reached. Partial results in working memory.", memory.data)
    
    return memory.data

# ============================================================
# STREAMING AGENT (for UI integration)
# ============================================================
def run_agent_streaming(goal, settings=None):
    """
    Generator version of run_agent for streaming to the UI.
    Yields JSON events for each step.
    """
    settings = settings or {}
    think_budget = settings.get("think_budget", 512)
    temperature = settings.get("temperature", 0.7)
    num_ctx = settings.get("num_ctx", 16384)
    
    task_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    memory = WorkingMemory(task_id)
    memory.set_goal(goal)
    
    allowed_tools = settings.get("allowed_tools")  # None = all tools (unchanged default)
    custom_system = settings.get("system_prompt", "")
    if custom_system:
        system = custom_system + "\n\nAVAILABLE TOOLS:\n" + get_tools_prompt(allowed_tools)
    else:
        system = AGENT_SYSTEM_PROMPT.format(tools=get_tools_prompt(allowed_tools))
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"TASK: {goal}\n\nIf file content is included above, use it directly — do NOT try to read or search for the file. Begin now."}
    ]
    
    yield json.dumps({"type": "agent_start", "task_id": task_id, "goal": goal})
    
    last_result_str = ""
    format_failures = 0
    FORMAT_FAILURE_LIMIT = 2  # after this many consecutive bad-format responses,
                              # stop nagging and just use what the model wrote —
                              # it clearly has the answer, it just won't format it

    for step in range(1, MAX_AGENT_STEPS + 1):
        if step > 1:
            messages[-1] = {
                "role": "user",
                "content": f"RESULT:\n{last_result_str}\n\nContinue. Be concise."
            }
        
        yield json.dumps({"type": "agent_thinking", "step": step})
        
        try:
            resp = requests.post(OLLAMA_URL, json={
                "model": MODEL,
                "options": {"num_ctx": num_ctx, "num_predict": 2048, "temperature": temperature},
                "messages": messages,
                "stream": False
            }, timeout=300)
            agent_text = resp.json().get("message", {}).get("content", "")
        except Exception as e:
            yield json.dumps({"type": "agent_error", "step": step, "error": str(e)})
            break
        
        think, action, tool_name, tool_args = parse_agent_response(agent_text)
        
        if not tool_name:
            format_failures += 1
            if format_failures > FORMAT_FAILURE_LIMIT and agent_text.strip():
                # The model has repeatedly produced a real answer, just not in the
                # required ACT: format. Stop looping and use its own text as the
                # completion rather than burning the rest of MAX_AGENT_STEPS on
                # a correction it isn't going to follow.
                summary = agent_text.strip()
                memory.complete(summary)
                yield json.dumps({"type": "agent_step", "step": step, "think": think or "",
                                "action": "Format retries exhausted — using model's own answer as completion",
                                "result": {"note": f"gave up correcting format after {format_failures} attempts"}})
                yield json.dumps({"type": "agent_complete", "step": step, "think": think,
                                "summary": summary, "memory": memory.data})
                return
            yield json.dumps({"type": "agent_step", "step": step, "think": think or agent_text[:500],
                            "action": "No valid action", "result": {"raw": agent_text[:300]}})
            messages.append({"role": "assistant", "content": agent_text})
            messages.append({"role": "user", "content": "Format error. Use THINK: then ACT: tool_name(param=\"value\"). Try again."})
            continue
        
        format_failures = 0  # reset on any successfully parsed action
        
        if tool_name == "task_complete":
            summary = tool_args.get("summary", "Done")
            memory.complete(summary)
            yield json.dumps({"type": "agent_complete", "step": step, "think": think,
                            "summary": summary, "memory": memory.data})
            return
        
        yield json.dumps({"type": "agent_executing", "step": step, "think": think,
                        "tool": tool_name, "args": tool_args})
        
        tool_result = execute_tool(tool_name, tool_args, allowed=allowed_tools)
        
        if tool_name == "write_file" and "path" in (tool_result or {}):
            memory.add_file(tool_result["path"])
        
        last_result_str = json.dumps(tool_result, indent=2, default=str)[:3000]
        memory.add_step(step, think, action, tool_name, tool_args, tool_result)
        
        yield json.dumps({"type": "agent_step", "step": step, "think": think,
                        "action": f"{tool_name}({json.dumps(tool_args, default=str)[:200]})",
                        "result": tool_result})
        
        messages.append({"role": "assistant", "content": agent_text})
        messages.append({"role": "user", "content": f"OBSERVATION:\n{last_result_str}"})
        
        if len(messages) > 20:
            messages = messages[:2] + messages[-16:]
    
    memory.data["status"] = "max_steps_reached"
    memory.save()
    yield json.dumps({"type": "agent_complete", "step": MAX_AGENT_STEPS,
                    "summary": "Max steps reached", "memory": memory.data})

# ============================================================
# NATIVE TOOL-CALLING AGENT (Ollama's real tools/tool_calls API)
# ============================================================
def run_agent_streaming_native(goal, settings=None):
    """
    Same event contract as run_agent_streaming (agent_start/agent_thinking/
    agent_executing/agent_step/agent_complete/agent_error), but uses Ollama's
    native tools API instead of THINK:/ACT: text parsing.

    Why this exists alongside run_agent_streaming rather than replacing it:
    native tool-calling requires the specific model to have chat-template
    support for it (check via `ollama show <model>` -> Capabilities -> tools).
    Your current model (the Qwen3.6 uncensored merge) does have it, confirmed
    July 2026. If you ever switch models and the new one lacks "tools" in its
    capabilities, this function will misbehave -- fall back to
    run_agent_streaming in that case, which works with any model since it
    doesn't depend on template support.

    This should be structurally more reliable than the text-parsed version:
    there's no regex trying to find an ACT: line in free text, no way for the
    model to "forget" the format after a few turns -- tool_calls is either
    present in the response or it isn't, and when it's absent that's a clean,
    unambiguous signal the model is done, not a parse failure to recover from.
    """
    settings = settings or {}
    temperature = settings.get("temperature", 0.7)
    num_ctx = settings.get("num_ctx", 16384)
    allowed_tools = settings.get("allowed_tools")  # None = all tools

    task_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    memory = WorkingMemory(task_id)
    memory.set_goal(goal)

    custom_system = settings.get("system_prompt", "")
    system = custom_system if custom_system else (
        "You are Atherix Red, an autonomous agent. Use the available tools to "
        "accomplish the task. When the task is complete, call task_complete "
        "with a clear summary. Do not call task_complete until the task is "
        "actually done."
    )

    tool_schemas = build_tool_schemas(allowed_tools)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"TASK: {goal}"},
    ]

    yield json.dumps({"type": "agent_start", "task_id": task_id, "goal": goal})

    for step in range(1, MAX_AGENT_STEPS + 1):
        yield json.dumps({"type": "agent_thinking", "step": step})

        try:
            resp = requests.post(OLLAMA_URL, json={
                "model": MODEL,
                "messages": messages,
                "tools": tool_schemas,
                "think": True,
                "options": {"num_ctx": num_ctx, "num_predict": 2048, "temperature": temperature},
                "stream": False,
            }, timeout=300)
            msg = resp.json().get("message", {})
        except Exception as e:
            yield json.dumps({"type": "agent_error", "step": step, "error": str(e)})
            break

        think = msg.get("thinking", "") or ""
        content = msg.get("content", "") or ""
        tool_calls = msg.get("tool_calls") or []
        messages.append(msg)  # native API expects the raw assistant message appended as-is

        # No tool call at all -> the model is done. This is a clean signal,
        # not a parse failure -- unlike the text-parsed loop, there's nothing
        # to "recover" from here.
        if not tool_calls:
            summary = content.strip() or "Task completed (no summary provided)."
            memory.complete(summary)
            yield json.dumps({"type": "agent_complete", "step": step, "think": think,
                            "summary": summary, "memory": memory.data})
            return

        # A turn can contain multiple tool calls; execute each and append its
        # result as a "tool" role message before the next model call.
        done = False
        for call in tool_calls:
            fn = call.get("function", {})
            tool_name = fn.get("name")
            tool_args = fn.get("arguments") or {}

            if tool_name == "task_complete":
                summary = tool_args.get("summary", content.strip() or "Done")
                memory.complete(summary)
                yield json.dumps({"type": "agent_complete", "step": step, "think": think,
                                "summary": summary, "memory": memory.data})
                done = True
                break

            yield json.dumps({"type": "agent_executing", "step": step, "think": think,
                            "tool": tool_name, "args": tool_args})

            tool_result = execute_tool(tool_name, tool_args, allowed=allowed_tools)

            if tool_name == "write_file" and "path" in (tool_result or {}):
                memory.add_file(tool_result["path"])

            memory.add_step(step, think, f"{tool_name}(...)", tool_name, tool_args, tool_result)

            yield json.dumps({"type": "agent_step", "step": step, "think": think,
                            "action": f"{tool_name}({json.dumps(tool_args, default=str)[:200]})",
                            "result": tool_result})

            messages.append({"role": "tool", "tool_name": tool_name,
                            "content": json.dumps(tool_result, default=str)[:3000]})

        if done:
            return

        if len(messages) > 24:
            messages = messages[:2] + messages[-20:]

    memory.data["status"] = "max_steps_reached"
    memory.save()
    yield json.dumps({"type": "agent_complete", "step": MAX_AGENT_STEPS,
                    "summary": "Max steps reached", "memory": memory.data})
