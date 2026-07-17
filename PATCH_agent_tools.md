# Patch: agent_tools.py

Replace `get_tools_prompt()` and `execute_tool()` with these versions.
Everything else in the file is unchanged — this only adds an optional
`allowed` filter, defaulting to None (= all tools, same as today).

```python
def get_tools_prompt(allowed=None):
    """Generate tool descriptions for the agent system prompt.
    allowed: optional list/set of tool names to include. None = all tools (unchanged behavior)."""
    lines = ["Available tools:\n"]
    for name, info in TOOLS.items():
        if allowed is not None and name not in allowed:
            continue
        params_str = ", ".join([f"{p['name']}: {p['description']}" for p in info["params"]])
        lines.append(f"- {name}({params_str}): {info['description']}")
    return "\n".join(lines)

def execute_tool(name, args, allowed=None):
    """Execute a tool by name with given args — strips unknown kwargs.
    allowed: optional list/set of tool names this caller may use. None = no restriction."""
    if allowed is not None and name not in allowed:
        return {"error": f"Tool '{name}' is not available to this agent persona."}
    if name not in TOOLS:
        return {"error": f"Unknown tool: {name}"}
    try:
        import inspect
        func = TOOLS[name]["function"]
        valid_params = set(inspect.signature(func).parameters.keys())
        filtered_args = {k: v for k, v in args.items() if k in valid_params}
        result = func(**filtered_args)
        return result
    except Exception as e:
        return {"error": f"Tool '{name}' failed: {str(e)}"}
```

# Patch: agent_core.py

In `run_agent()` (and mirror the same change in `run_agent_streaming()`),
change these two lines:

```python
    custom_system = settings.get("system_prompt", "")
    if custom_system:
        system = custom_system + "\n\nAVAILABLE TOOLS:\n" + get_tools_prompt()
    else:
        system = AGENT_SYSTEM_PROMPT.format(tools=get_tools_prompt())
```

to:

```python
    allowed_tools = settings.get("allowed_tools")  # None = all tools
    custom_system = settings.get("system_prompt", "")
    if custom_system:
        system = custom_system + "\n\nAVAILABLE TOOLS:\n" + get_tools_prompt(allowed_tools)
    else:
        system = AGENT_SYSTEM_PROMPT.format(tools=get_tools_prompt(allowed_tools))
```

And change the `execute_tool(tool_name, tool_args)` call further down to:

```python
    tool_result = execute_tool(tool_name, tool_args, allowed=allowed_tools)
```

That's the entire patch. Backward compatible — if nobody passes `allowed_tools`,
behavior is identical to today.
