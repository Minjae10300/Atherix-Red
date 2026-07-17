"""
Atherix Red - Agent Tools
All tools the agent can execute autonomously
"""

import subprocess
import os
import re
import json
import tempfile
import requests
from datetime import datetime

import simforge_bridge as sf

BASE_DIR = "C:\\atherix-red"
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
SANDBOX_DIR = os.path.join(BASE_DIR, "sandbox")
os.makedirs(SANDBOX_DIR, exist_ok=True)

# ============================================================
# TOOL REGISTRY
# ============================================================
TOOLS = {}

def tool(name, description, params):
    """Decorator to register a tool"""
    def decorator(func):
        TOOLS[name] = {
            "name": name,
            "description": description,
            "params": params,
            "function": func
        }
        return func
    return decorator

def build_tool_schemas(allowed=None):
    """Export TOOLS as Ollama-native tool-calling schemas (OpenAI function format).

    NOTE on param types: your existing tool defs only carry name+description,
    no explicit type per param. Everything is declared "string" here as a
    permissive default -- it's honest to flag this isn't fully correct: a few
    tools (run_epidemic_sim's population/beta/gamma, run_queue_sim's rates)
    genuinely expect numbers, and a model that dutifully returns a quoted
    "50000" instead of 50000 could hand your Python function a str where it
    wanted an int/float. Most of your tool functions already do loose
    coercion internally or numpy handles the cast silently, so this works in
    practice more often than not -- but if you hit a type error on a specific
    tool, that's the fix: give that one tool a proper "type": "number" in its
    params here, not a blanket rewrite of all 30+.
    """
    schemas = []
    for name, info in TOOLS.items():
        if allowed is not None and name not in allowed:
            continue
        properties = {p["name"]: {"type": "string", "description": p["description"]}
                      for p in info["params"]}
        schemas.append({
            "type": "function",
            "function": {
                "name": name,
                "description": info["description"],
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    # deliberately not setting "required" -- several tools have
                    # optional args with Python-side defaults (market_odds=None,
                    # t_max=10000, etc); marking everything required would push
                    # the model to invent values it doesn't actually need to supply
                },
            },
        })
    return schemas

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
        # Get valid parameter names for this function
        valid_params = set(inspect.signature(func).parameters.keys())
        # Filter args to only include valid params
        filtered_args = {k: v for k, v in args.items() if k in valid_params}
        result = func(**filtered_args)
        return result
    except Exception as e:
        return {"error": f"Tool '{name}' failed: {str(e)}"}

# ============================================================
# SHELL COMMAND EXECUTION
# ============================================================
@tool("run_command", "Execute a shell command and return output. Use for nmap, gobuster, curl, ping, etc.",
      [{"name": "command", "description": "Shell command to execute"},
       {"name": "timeout", "description": "Timeout in seconds (default 60)"}])
def run_command(command, timeout=60):
    # Safety: block dangerous commands
    blocked = ["format", "del /s", "rm -rf /", "mkfs", "dd if=", ":(){", "shutdown", "reboot"]
    for b in blocked:
        if b.lower() in command.lower():
            return {"error": f"Blocked dangerous command: {command}"}
    
    try:
        timeout = int(timeout)
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=SANDBOX_DIR
        )
        output = result.stdout[:10000] if result.stdout else ""
        error = result.stderr[:5000] if result.stderr else ""
        return {
            "command": command,
            "exit_code": result.returncode,
            "stdout": output,
            "stderr": error,
            "truncated": len(result.stdout or "") > 10000
        }
    except subprocess.TimeoutExpired:
        return {"error": f"Command timed out after {timeout}s", "command": command}
    except Exception as e:
        return {"error": str(e), "command": command}

# ============================================================
# PYTHON CODE EXECUTION (SANDBOX)
# ============================================================
@tool("run_python", "Execute Python code in a sandbox. Returns stdout and any errors.",
      [{"name": "code", "description": "Python code to execute"},
       {"name": "timeout", "description": "Timeout in seconds (default 30)"}])
def run_python(code, timeout=30):
    # Write code to temp file
    script_path = os.path.join(SANDBOX_DIR, f"script_{datetime.now().strftime('%Y%m%d_%H%M%S')}.py")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(code)
    
    try:
        timeout = int(timeout)
        result = subprocess.run(
            ["python", script_path],
            capture_output=True, text=True, timeout=timeout,
            cwd=SANDBOX_DIR
        )
        return {
            "script": script_path,
            "exit_code": result.returncode,
            "stdout": result.stdout[:10000],
            "stderr": result.stderr[:5000],
            "code": code[:2000]
        }
    except subprocess.TimeoutExpired:
        return {"error": f"Script timed out after {timeout}s"}
    except Exception as e:
        return {"error": str(e)}

# ============================================================
# FILE OPERATIONS
# ============================================================
@tool("read_file", "Read contents of a file. Supports text, code, logs, configs.",
      [{"name": "path", "description": "Path to the file to read"},
       {"name": "max_lines", "description": "Max lines to read (default 500)"}])
def read_file(path, max_lines=500):
    max_lines = int(max_lines)
    if not os.path.exists(path):
        return {"error": f"File not found: {path}"}
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        total = len(lines)
        content = "".join(lines[:max_lines])
        return {
            "path": path,
            "total_lines": total,
            "lines_read": min(max_lines, total),
            "content": content[:15000],
            "truncated": total > max_lines
        }
    except Exception as e:
        return {"error": str(e)}

@tool("write_file", "Create or overwrite a file with content.",
      [{"name": "path", "description": "Path to write the file"},
       {"name": "content", "description": "Content to write"}])
def write_file(path, content):
    # Ensure path is within allowed directories
    allowed_dirs = [OUTPUT_DIR, SANDBOX_DIR, BASE_DIR]
    abs_path = os.path.abspath(path)
    if not any(abs_path.startswith(os.path.abspath(d)) for d in allowed_dirs):
        # Default to output dir
        path = os.path.join(OUTPUT_DIR, os.path.basename(path))
    
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return {"path": path, "size": os.path.getsize(path), "status": "created"}

@tool("list_files", "List files in a directory.",
      [{"name": "path", "description": "Directory path to list"},
       {"name": "pattern", "description": "Optional glob pattern filter (default *)"}])
def list_files(path, pattern="*"):
    import glob
    if not os.path.isdir(path):
        return {"error": f"Not a directory: {path}"}
    
    files = []
    search = os.path.join(path, "**", pattern) if pattern != "*" else os.path.join(path, "**")
    for fp in glob.glob(search, recursive=True)[:200]:
        if os.path.isfile(fp):
            files.append({
                "path": fp,
                "name": os.path.basename(fp),
                "size": os.path.getsize(fp),
                "ext": os.path.splitext(fp)[1]
            })
    return {"directory": path, "count": len(files), "files": files}

@tool("search_in_files", "Search for a pattern across files in a directory. Like grep.",
      [{"name": "path", "description": "Directory to search in"},
       {"name": "pattern", "description": "Regex pattern to search for"},
       {"name": "file_ext", "description": "File extension filter (e.g. .py, .js). Leave empty for all."}])
def search_in_files(path, pattern, file_ext=""):
    import glob
    if not os.path.isdir(path):
        return {"error": f"Not a directory: {path}"}
    
    results = []
    search_glob = os.path.join(path, "**", f"*{file_ext}") if file_ext else os.path.join(path, "**", "*")
    
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return {"error": f"Invalid regex: {e}"}
    
    for fp in glob.glob(search_glob, recursive=True)[:500]:
        if not os.path.isfile(fp):
            continue
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                for i, line in enumerate(f, 1):
                    if regex.search(line):
                        results.append({
                            "file": fp,
                            "line_number": i,
                            "content": line.strip()[:200]
                        })
                        if len(results) >= 50:
                            return {"pattern": pattern, "matches": results, "truncated": True}
        except:
            continue
    
    return {"pattern": pattern, "matches": results, "count": len(results)}

# ============================================================
# PYTHON ENVIRONMENT MANAGEMENT
# ============================================================
@tool("pip_install", "Install a Python package using pip. Use this when a library is missing or ImportError occurs.",
      [{"name": "package", "description": "Package name to install (e.g. 'requests', 'beautifulsoup4', 'duckduckgo-search')"},
       {"name": "version", "description": "Optional version constraint (e.g. '>=2.0', '==1.4.0'). Leave empty for latest."}])
def pip_install(package, version=""):
    pkg = f"{package}{version}".strip()
    try:
        result = subprocess.run(
            ["python", "-m", "pip", "install", pkg, "--quiet"],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            # Verify it's importable
            import_name = package.replace("-", "_").split("[")[0]
            verify = subprocess.run(
                ["python", "-c", f"import {import_name}; print('OK')"],
                capture_output=True, text=True, timeout=10
            )
            return {
                "package": pkg,
                "status": "installed",
                "importable": verify.returncode == 0,
                "import_name": import_name
            }
        return {
            "package": pkg,
            "status": "failed",
            "error": result.stderr[:1000]
        }
    except subprocess.TimeoutExpired:
        return {"error": f"pip install timed out for {pkg}"}
    except Exception as e:
        return {"error": str(e)}

@tool("check_env", "Check the Python environment: version, installed packages, and system info.",
      [{"name": "filter", "description": "Optional package name filter (e.g. 'requests' to check if installed). Empty = list all."}])
def check_env(filter=""):
    try:
        # Python version
        ver = subprocess.run(["python", "--version"], capture_output=True, text=True).stdout.strip()
        
        # Installed packages
        pkgs = subprocess.run(
            ["python", "-m", "pip", "list", "--format=columns"],
            capture_output=True, text=True, timeout=30
        )
        pkg_list = pkgs.stdout
        
        if filter:
            lines = [l for l in pkg_list.splitlines() if filter.lower() in l.lower()]
            pkg_list = "\n".join(lines) or f"'{filter}' not found in installed packages"
        else:
            pkg_list = pkg_list[:3000]
        
        return {
            "python_version": ver,
            "packages": pkg_list,
            "cwd": os.getcwd()
        }
    except Exception as e:
        return {"error": str(e)}

# ============================================================
# GITHUB CODE SEARCH & RETRIEVAL
# ============================================================
@tool("search_github", "Search GitHub for code examples, repositories, or issues. Automatically scores trust/legitimacy of results.",
      [{"name": "query", "description": "Search query (e.g. 'python nmap scanner script', 'flask jwt authentication')"},
       {"name": "search_type", "description": "What to search: 'code' for code snippets, 'repos' for repositories, 'issues' for bug fixes. Default: repos"},
       {"name": "language", "description": "Filter by language (e.g. 'python', 'javascript'). Leave empty for all."},
       {"name": "min_stars", "description": "Minimum stars to include (default 5). Set to 0 for all."}])
def search_github(query, search_type="repos", language="", min_stars="5"):
    """Search GitHub with automatic trust verification. Flags sketchy repos."""
    try:
        min_stars = int(min_stars)
        lang_filter = f"+language:{language}" if language else ""
        star_filter = f"+stars:>={min_stars}" if min_stars > 0 and search_type == "repos" else ""
        encoded_query = requests.utils.quote(f"{query}{lang_filter}{star_filter}")
        
        endpoint_map = {"code": "code", "repos": "repositories", "issues": "issues"}
        endpoint = endpoint_map.get(search_type, "repositories")
        
        headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "AtherixRed/1.0"}
        
        r = requests.get(
            f"https://api.github.com/search/{endpoint}?q={encoded_query}&per_page=10&sort=stars",
            headers=headers, timeout=15
        )
        
        if r.status_code == 200:
            data = r.json()
            items = data.get("items", [])
            
            if search_type == "repos":
                results = []
                for item in items[:10]:
                    stars = item.get("stargazers_count", 0)
                    forks = item.get("forks_count", 0)
                    created = item.get("created_at", "")[:10]
                    updated = item.get("updated_at", "")[:10]
                    owner = item.get("owner", {})
                    owner_type = owner.get("type", "User")  # User or Organization
                    has_license = bool(item.get("license"))
                    has_description = bool(item.get("description"))
                    archived = item.get("archived", False)
                    
                    # Trust scoring: 0-100
                    trust = 0
                    trust += min(stars, 50)           # Up to 50 pts for stars
                    trust += min(forks * 2, 20)       # Up to 20 pts for forks
                    if has_license: trust += 10        # Licensed = more legit
                    if has_description: trust += 5     # Has description
                    if owner_type == "Organization": trust += 10  # Org > random user
                    if archived: trust -= 20           # Archived = probably dead
                    # Age bonus: older repos are more vetted
                    try:
                        from datetime import datetime as dt
                        age_days = (dt.now() - dt.strptime(created, "%Y-%m-%d")).days
                        trust += min(age_days // 30, 10)  # Up to 10 pts for age (in months)
                    except: pass
                    trust = max(0, min(100, trust))
                    
                    # Trust label
                    if trust >= 60: trust_label = "HIGH"
                    elif trust >= 30: trust_label = "MEDIUM"
                    elif trust >= 10: trust_label = "LOW"
                    else: trust_label = "SKETCHY"
                    
                    results.append({
                        "name": item.get("full_name"),
                        "description": (item.get("description") or "")[:200],
                        "url": item.get("html_url"),
                        "stars": stars,
                        "forks": forks,
                        "language": item.get("language"),
                        "license": (item.get("license") or {}).get("spdx_id", "None"),
                        "topics": item.get("topics", [])[:5],
                        "created": created,
                        "updated": updated,
                        "owner_type": owner_type,
                        "archived": archived,
                        "trust_score": trust,
                        "trust_level": trust_label,
                    })
                
            elif search_type == "code":
                results = []
                for item in items[:10]:
                    repo = item.get("repository", {})
                    repo_stars = repo.get("stargazers_count", 0) if "stargazers_count" in repo else -1
                    
                    # Trust: if repo has low stars, flag it
                    if repo_stars >= 0:
                        trust_label = "HIGH" if repo_stars >= 50 else "MEDIUM" if repo_stars >= 10 else "LOW" if repo_stars >= 3 else "SKETCHY"
                    else:
                        trust_label = "UNKNOWN"
                    
                    raw_url = item.get("html_url", "").replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
                    
                    results.append({
                        "file": item.get("name"),
                        "repo": repo.get("full_name"),
                        "path": item.get("path"),
                        "url": item.get("html_url"),
                        "raw_url": raw_url,
                        "repo_stars": repo_stars if repo_stars >= 0 else "unknown",
                        "trust_level": trust_label,
                    })
            else:
                results = [
                    {"title": item.get("title"), "url": item.get("html_url"),
                     "state": item.get("state"), "body": (item.get("body") or "")[:300]}
                    for item in items[:8]
                ]
            
            return {
                "query": query, "search_type": search_type,
                "total_found": data.get("total_count", 0),
                "results": results,
                "trust_note": "Results sorted by stars. Trust levels: HIGH (60+), MEDIUM (30-59), LOW (10-29), SKETCHY (<10). Prefer HIGH/MEDIUM trust repos for code you'll actually run."
            }
        elif r.status_code == 403:
            return {"error": "GitHub rate limit hit. Try again in 60 seconds or use web_search instead."}
        return {"error": f"GitHub API returned HTTP {r.status_code}"}
    except Exception as e:
        return {"error": str(e)}

@tool("fetch_github_file", "Fetch the raw content of a file from GitHub. Use the raw URL from search_github results.",
      [{"name": "url", "description": "GitHub URL (html or raw). Works with github.com or raw.githubusercontent.com links."},
       {"name": "max_lines", "description": "Max lines to return (default 300)"}])
def fetch_github_file(url, max_lines=300):
    try:
        max_lines = int(max_lines)
        # Convert html github URL to raw
        raw_url = url
        if "github.com" in url and "/blob/" in url:
            raw_url = url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
        
        headers = {"User-Agent": "AtherixRed/1.0"}
        r = requests.get(raw_url, headers=headers, timeout=15)
        
        if r.status_code == 200:
            lines = r.text.splitlines()
            total = len(lines)
            content = "\n".join(lines[:max_lines])
            return {
                "url": raw_url,
                "total_lines": total,
                "lines_shown": min(max_lines, total),
                "content": content,
                "truncated": total > max_lines
            }
        return {"error": f"HTTP {r.status_code} for {raw_url}"}
    except Exception as e:
        return {"error": str(e)}

@tool("fetch_and_analyze_url", "Fetch any URL and return its content. Works for web pages, blog posts, documentation, GitHub repos, paste sites, etc. Extracts readable text from HTML.",
      [{"name": "url", "description": "Full URL to fetch (must start with http:// or https://)"},
       {"name": "max_chars", "description": "Max characters to return (default 12000)"},
       {"name": "extract_code", "description": "If 'true', also extract code blocks separately. Default: false"}])
def fetch_and_analyze_url(url, max_chars=12000, extract_code="false"):
    """Fetch any URL, clean the HTML, and optionally extract code blocks."""
    try:
        max_chars = int(max_chars)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        r = requests.get(url, headers=headers, timeout=20, verify=False, allow_redirects=True)
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}", "url": url}
        
        content = r.text
        content_type = r.headers.get("Content-Type", "")
        
        # If it's not HTML, return raw content
        if "text/plain" in content_type or "application/json" in content_type:
            return {
                "url": url,
                "content_type": content_type,
                "content": content[:max_chars],
                "length": len(content),
                "truncated": len(content) > max_chars
            }
        
        # Extract code blocks before stripping HTML
        code_blocks = []
        if extract_code.lower() == "true":
            # Find <pre><code> blocks
            for match in re.findall(r'<pre[^>]*>\s*<code[^>]*>(.*?)</code>\s*</pre>', content, re.DOTALL):
                clean_code = re.sub(r'<[^>]+>', '', match).strip()
                if len(clean_code) > 20:
                    code_blocks.append(clean_code[:3000])
            # Find ``` markdown blocks in text content
            for match in re.findall(r'```\w*\n(.*?)```', content, re.DOTALL):
                if len(match.strip()) > 20:
                    code_blocks.append(match.strip()[:3000])
        
        # Strip HTML to readable text
        clean = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL)
        clean = re.sub(r'<style[^>]*>.*?</style>', '', clean, flags=re.DOTALL)
        clean = re.sub(r'<nav[^>]*>.*?</nav>', '', clean, flags=re.DOTALL)
        clean = re.sub(r'<footer[^>]*>.*?</footer>', '', clean, flags=re.DOTALL)
        clean = re.sub(r'<header[^>]*>.*?</header>', '', clean, flags=re.DOTALL)
        # Convert some tags to readable markers
        clean = re.sub(r'<h[1-6][^>]*>(.*?)</h[1-6]>', r'\n## \1\n', clean, flags=re.DOTALL)
        clean = re.sub(r'<li[^>]*>(.*?)</li>', r'\n- \1', clean, flags=re.DOTALL)
        clean = re.sub(r'<br\s*/?>', '\n', clean)
        clean = re.sub(r'<p[^>]*>', '\n', clean)
        clean = re.sub(r'<[^>]+>', ' ', clean)
        # Fix whitespace
        clean = re.sub(r'[ \t]+', ' ', clean)
        clean = re.sub(r'\n{3,}', '\n\n', clean)
        clean = clean.strip()
        
        result = {
            "url": url,
            "content_type": content_type,
            "content": clean[:max_chars],
            "length": len(clean),
            "truncated": len(clean) > max_chars,
            "title": ""
        }
        
        # Extract page title
        title_match = re.search(r'<title[^>]*>(.*?)</title>', content, re.DOTALL | re.IGNORECASE)
        if title_match:
            result["title"] = title_match.group(1).strip()[:200]
        
        if code_blocks:
            result["code_blocks"] = code_blocks[:10]
            result["code_block_count"] = len(code_blocks)
        
        return result
    except Exception as e:
        return {"error": str(e), "url": url}

# ============================================================
# NETWORK TOOLS
# ============================================================
@tool("cve_lookup", "Look up CVE details including CVSS, EPSS, and exploitability.",
      [{"name": "cve_id", "description": "CVE ID (e.g. CVE-2024-0204)"}])
def cve_lookup(cve_id):
    cve_id = cve_id.upper().strip()
    if not cve_id.startswith("CVE-"):
        cve_id = "CVE-" + cve_id
    try:
        r = requests.get(f"https://cvedb.shodan.io/cve/{cve_id}", timeout=10)
        if r.status_code == 200:
            d = r.json()
            return {
                "cve": d.get("cve_id"), "summary": d.get("summary", "")[:500],
                "cvss_v3": d.get("cvss_v3"), "cvss_v2": d.get("cvss_v2"),
                "epss": d.get("epss"), "epss_ranking": d.get("ranking_epss"),
                "kev": d.get("kev"), "ransomware": d.get("ransomware_campaign"),
                "published": d.get("published_time"),
                "references": d.get("references", [])[:8]
            }
        return {"error": f"Not found: {cve_id}"}
    except Exception as e:
        return {"error": str(e)}

@tool("scan_ip", "Scan a public IP for open ports, services, vulnerabilities via Shodan.",
      [{"name": "ip", "description": "IP address to scan"}])
def scan_ip(ip):
    try:
        r = requests.get(f"https://internetdb.shodan.io/{ip.strip()}", timeout=10)
        return r.json() if r.status_code == 200 else {"error": f"No data for {ip}"}
    except Exception as e:
        return {"error": str(e)}

@tool("exploit_search", "Search for known exploits by keyword.",
      [{"name": "query", "description": "Search query (e.g. 'apache 2.4.49')"}])
def exploit_search(query):
    try:
        r = requests.get("https://exploits.shodan.io/api/search", params={"query": query}, timeout=10)
        if r.status_code == 200:
            d = r.json()
            return {
                "total": d.get("total", 0),
                "results": [
                    {"source": m.get("source", ""), "title": m.get("title", "")[:150],
                     "cve": m.get("cve", []), "has_code": bool(m.get("code")),
                     "platform": m.get("platform", "")}
                    for m in d.get("matches", [])[:10]
                ]
            }
        return {"error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"error": str(e)}

@tool("whois_lookup", "Domain WHOIS lookup.",
      [{"name": "domain", "description": "Domain to look up"}])
def whois_lookup(domain):
    try:
        r = requests.get(f"https://rdap.org/domain/{domain.strip()}", timeout=10)
        if r.status_code == 200:
            d = r.json()
            ev = {e.get("eventAction", ""): e.get("eventDate", "") for e in d.get("events", [])}
            ns = [n.get("ldhName", "") if isinstance(n, dict) else str(n) for n in d.get("nameservers", [])]
            return {"domain": d.get("name", domain), "status": d.get("status", [])[:3],
                    "registered": ev.get("registration"), "expires": ev.get("expiration"),
                    "nameservers": ns[:4]}
        return {"error": f"Failed for {domain}"}
    except Exception as e:
        return {"error": str(e)}

@tool("http_request", "Make an HTTP request to a URL and return the response.",
      [{"name": "url", "description": "URL to request"},
       {"name": "method", "description": "HTTP method (GET, POST, HEAD, OPTIONS)"},
       {"name": "headers", "description": "JSON string of headers (optional)"}])
def http_request(url, method="GET", headers="{}"):
    try:
        hdrs = json.loads(headers) if headers else {}
        r = requests.request(method.upper(), url, headers=hdrs, timeout=15, verify=False, allow_redirects=True)
        resp_headers = dict(r.headers)
        return {
            "url": url, "method": method, "status_code": r.status_code,
            "headers": {k: v for k, v in resp_headers.items()},
            "body": r.text[:8000],
            "content_type": resp_headers.get("Content-Type", ""),
            "server": resp_headers.get("Server", ""),
            "content_length": len(r.content)
        }
    except Exception as e:
        return {"error": str(e)}

# ============================================================
# ANALYSIS TOOLS
# ============================================================
@tool("analyze_code", "Analyze a code file for security vulnerabilities.",
      [{"name": "path", "description": "Path to the code file"}])
def analyze_code(path):
    if not os.path.exists(path):
        return {"error": f"File not found: {path}"}
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        ext = os.path.splitext(path)[1].lower()
        lang_map = {".py": "python", ".js": "javascript", ".php": "php", ".java": "java",
                    ".c": "c", ".cpp": "cpp", ".rb": "ruby", ".go": "go", ".rs": "rust",
                    ".cs": "csharp", ".html": "html", ".sql": "sql"}
        return {"path": path, "language": lang_map.get(ext, "unknown"),
                "lines": content.count("\n") + 1, "size": len(content), "content": content[:15000]}
    except Exception as e:
        return {"error": str(e)}

# ============================================================
# WEB SEARCH & KNOWLEDGE RETRIEVAL (RAG)
# ============================================================
@tool("web_search", "Search the internet for information, documentation, error fixes, CVEs, exploit techniques, or anything else.",
      [{"name": "query", "description": "Search query"},
       {"name": "max_results", "description": "Number of results (default 5)"}])
def web_search(query, max_results=5):
    """Live web search via DuckDuckGo — no API key needed"""
    try:
        from duckduckgo_search import DDGS
        max_results = int(max_results)
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", "")[:500]
                })
        return {"query": query, "results": results, "count": len(results)}
    except ImportError:
        return {"error": "duckduckgo_search not installed. Run: pip install duckduckgo-search"}
    except Exception as e:
        return {"error": str(e), "query": query}

@tool("fetch_url", "Fetch the full content of a webpage. Use after web_search to read documentation, Stack Overflow answers, GitHub issues, etc.",
      [{"name": "url", "description": "URL to fetch"},
       {"name": "max_chars", "description": "Max characters to return (default 8000)"}])
def fetch_url(url, max_chars=8000):
    """Fetch webpage content and extract readable text"""
    try:
        max_chars = int(max_chars)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        r = requests.get(url, headers=headers, timeout=15, verify=False)
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}", "url": url}
        
        content = r.text
        
        # Strip HTML tags for cleaner text
        clean = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL)
        clean = re.sub(r'<style[^>]*>.*?</style>', '', clean, flags=re.DOTALL)
        clean = re.sub(r'<[^>]+>', ' ', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        
        return {
            "url": url,
            "content": clean[:max_chars],
            "length": len(clean),
            "truncated": len(clean) > max_chars
        }
    except Exception as e:
        return {"error": str(e), "url": url}

@tool("search_error", "Search for a fix to a specific error message or exception. Searches Stack Overflow and GitHub automatically.",
      [{"name": "error", "description": "The exact error message or exception"},
       {"name": "language", "description": "Programming language (python, javascript, etc.)"}])
def search_error(error, language="python"):
    """Targeted error search — finds fixes from Stack Overflow and GitHub"""
    try:
        from duckduckgo_search import DDGS
        query = f"{language} {error} fix site:stackoverflow.com OR site:github.com"
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=5):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", "")[:600]
                })
        
        if not results:
            # Fallback without site filter
            with DDGS() as ddgs:
                for r in ddgs.text(f"{language} {error}", max_results=5):
                    results.append({
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", "")[:600]
                    })
        
        return {"error_query": error, "language": language, "results": results}
    except ImportError:
        return {"error": "duckduckgo_search not installed. Run: pip install duckduckgo-search"}
    except Exception as e:
        return {"error": str(e)}

@tool("search_docs", "Look up official documentation for a library, framework, function, or API.",
      [{"name": "query", "description": "What to look up (e.g. 'Python requests session headers', 'Flask route decorator')"},
       {"name": "library", "description": "Library or framework name (e.g. requests, flask, numpy)"}])
def search_docs(query, library=""):
    """Search official docs and authoritative sources"""
    try:
        from duckduckgo_search import DDGS
        doc_sites = {
            # Core Python
            "python": "docs.python.org",
            "asyncio": "docs.python.org",
            "subprocess": "docs.python.org",
            "pathlib": "docs.python.org",
            "argparse": "docs.python.org",
            # HTTP & Web
            "requests": "docs.python-requests.org",
            "httpx": "www.python-httpx.org",
            "aiohttp": "docs.aiohttp.org",
            "flask": "flask.palletsprojects.com",
            "fastapi": "fastapi.tiangolo.com",
            "django": "docs.djangoproject.com",
            "starlette": "www.starlette.io",
            "uvicorn": "www.uvicorn.org",
            # Data
            "numpy": "numpy.org/doc",
            "pandas": "pandas.pydata.org/docs",
            "sqlite3": "docs.python.org",
            "sqlalchemy": "docs.sqlalchemy.org",
            # Frontend / JS
            "javascript": "developer.mozilla.org",
            "react": "react.dev",
            "nodejs": "nodejs.org/en/docs",
            "typescript": "www.typescriptlang.org/docs",
            # Security & Pentest
            "nmap": "nmap.org/book",
            "scapy": "scapy.readthedocs.io",
            "paramiko": "docs.paramiko.org",
            "impacket": "github.com/fortra/impacket",
            "pwntools": "docs.pwntools.com",
            "cryptography": "cryptography.io/en/latest",
            "pycryptodome": "pycryptodome.readthedocs.io",
            "shodan": "shodan.readthedocs.io",
            "pymetasploit3": "github.com/DanMcInerney/pymetasploit3",
            "burp": "portswigger.net/burp/documentation",
            "sqlmap": "github.com/sqlmapproject/sqlmap/wiki",
            "gobuster": "github.com/OJ/gobuster",
            "hashlib": "docs.python.org",
            "ssl": "docs.python.org",
            "socket": "docs.python.org",
            # LLM / AI
            "ollama": "github.com/ollama/ollama",
            "anthropic": "docs.anthropic.com",
            "openai": "platform.openai.com/docs",
            "transformers": "huggingface.co/docs/transformers",
            "langchain": "python.langchain.com/docs",
            # Tools
            "duckduckgo_search": "github.com/deedy5/duckduckgo_search",
            "beautifulsoup4": "www.crummy.com/software/BeautifulSoup/bs4/doc",
            "bs4": "www.crummy.com/software/BeautifulSoup/bs4/doc",
            "selenium": "selenium-python.readthedocs.io",
            "playwright": "playwright.dev/python/docs",
            "rich": "rich.readthedocs.io",
            "click": "click.palletsprojects.com",
        }
        site = doc_sites.get(library.lower(), "")
        search_q = f"{library} {query} documentation"
        if site:
            search_q += f" site:{site}"
        
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(search_q, max_results=5):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", "")[:600]
                })
        
        return {"query": query, "library": library, "results": results}
    except ImportError:
        return {"error": "duckduckgo_search not installed. Run: pip install duckduckgo-search"}
    except Exception as e:
        return {"error": str(e)}

@tool("check_latest_version", "Check the CURRENT latest version of a package from PyPI or npm. Always use this instead of guessing from memory — your training data has outdated version numbers.",
      [{"name": "package", "description": "Package name (e.g. 'requests', 'react', 'fastapi')"},
       {"name": "ecosystem", "description": "'pypi' for Python or 'npm' for JavaScript. Default: pypi"}])
def check_latest_version(package, ecosystem="pypi"):
    try:
        if ecosystem.lower() in ("pypi", "python", "pip"):
            r = requests.get(f"https://pypi.org/pypi/{package}/json", timeout=12,
                             headers={"User-Agent": "AtherixRed/1.0"})
            if r.status_code == 404:
                return {"error": f"Package '{package}' not found on PyPI"}
            if r.status_code != 200:
                return {"error": f"PyPI returned HTTP {r.status_code}"}
            d = r.json()
            info = d.get("info", {})
            latest = info.get("version", "")
            release_files = d.get("releases", {}).get(latest, [])
            release_date = release_files[0].get("upload_time", "")[:10] if release_files else ""
            try:
                from packaging.version import parse as vparse
                versions = sorted(d.get("releases", {}).keys(), key=vparse, reverse=True)[:5]
            except Exception:
                versions = sorted(d.get("releases", {}).keys(), reverse=True)[:5]
            return {
                "package": package, "ecosystem": "PyPI",
                "latest_version": latest, "release_date": release_date,
                "summary": info.get("summary", "")[:200],
                "requires_python": info.get("requires_python", ""),
                "recent_versions": versions,
                "install": f"pip install {package}=={latest}"
            }
        elif ecosystem.lower() in ("npm", "javascript", "js", "node"):
            r = requests.get(f"https://registry.npmjs.org/{package}/latest", timeout=12,
                             headers={"User-Agent": "AtherixRed/1.0"})
            if r.status_code == 404:
                return {"error": f"Package '{package}' not found on npm"}
            if r.status_code != 200:
                return {"error": f"npm returned HTTP {r.status_code}"}
            d = r.json()
            return {
                "package": package, "ecosystem": "npm",
                "latest_version": d.get("version", ""),
                "description": d.get("description", "")[:200],
                "license": d.get("license", ""),
                "install": f"npm install {package}@{d.get('version', '')}"
            }
        return {"error": f"Unknown ecosystem '{ecosystem}'. Use 'pypi' or 'npm'."}
    except Exception as e:
        return {"error": str(e)}

@tool("get_package_changelog", "Get recent release history for a PyPI package. Use to learn what changed since your training cutoff.",
      [{"name": "package", "description": "PyPI package name"},
       {"name": "count", "description": "How many recent releases to show (default 8)"}])
def get_package_changelog(package, count="8"):
    try:
        count = int(count)
        r = requests.get(f"https://pypi.org/pypi/{package}/json", timeout=12,
                         headers={"User-Agent": "AtherixRed/1.0"})
        if r.status_code != 200:
            return {"error": f"PyPI returned HTTP {r.status_code} for {package}"}
        d = r.json()
        releases = d.get("releases", {})
        rel_list = []
        for ver, files in releases.items():
            if files:
                rel_list.append((ver, files[0].get("upload_time", "")[:10]))
        rel_list.sort(key=lambda x: x[1], reverse=True)
        info = d.get("info", {})
        project_urls = info.get("project_urls") or {}
        changelog_url = next((v for k, v in project_urls.items()
                              if any(w in k.lower() for w in ["changelog", "changes", "history", "release"])), "")
        return {
            "package": package,
            "current_version": info.get("version", ""),
            "recent_releases": [{"version": v, "date": dt} for v, dt in rel_list[:count]],
            "changelog_url": changelog_url,
            "docs_url": info.get("docs_url") or project_urls.get("Documentation", ""),
        }
    except Exception as e:
        return {"error": str(e)}

@tool("task_complete", "Signal that the current task is complete and provide the final summary.",
      [{"name": "summary", "description": "Final summary of findings and results"}])
def task_complete(summary):
    return {"status": "complete", "summary": summary}


# ============================================================
# PRACTICE LAB TOOLS
# ============================================================

@tool(
    "run_command_in_lab",
    "Run a shell command against a localhost practice lab via WSL2. Rejects external IPs.",
    [
        {"name": "command", "description": "WSL2 shell command targeting localhost (e.g. 'curl -s http://localhost:8080/')"},
        {"name": "timeout", "description": "Timeout in seconds (default 30)"},
    ],
)
def run_command_in_lab(command: str, timeout: str = "30") -> dict:
    from lab_manager import run_command_in_lab as _rcl
    return _rcl(command, int(timeout))


@tool(
    "check_lab_status",
    "Check which practice lab Docker containers are currently running.",
    [],
)
def check_lab_status() -> dict:
    from lab_manager import get_running_containers
    return {"running": get_running_containers()}


@tool(
    "start_lab",
    "Spin up a practice lab Docker container via WSL2.",
    [
        {"name": "lab_key", "description": "Lab identifier: dvwa, juiceshop, webgoat, metasploitable2, vulnado, nodegoat"},
    ],
)
def start_lab(lab_key: str) -> dict:
    from lab_manager import spin_up_lab
    return spin_up_lab(lab_key)

# ============================================================
# SIMFORGE / ARC-SIM BRIDGE TOOLS
# ============================================================

@tool("forecast_soccer_match", "Forecast a soccer match using historical results, optionally comparing to market odds.",
      [{"name": "matches", "description": "List of [home, away, home_goals, away_goals] historical results"},
       {"name": "home", "description": "Home team name for the match to forecast"},
       {"name": "away", "description": "Away team name for the match to forecast"},
       {"name": "market_odds", "description": "Optional dict {home, draw, away} of American odds"}])
def forecast_soccer_match(matches, home, away, market_odds=None):
    return sf.forecast_soccer_match(matches, home, away, market_odds)


@tool("forecast_basketball_matchup", "Forecast a basketball matchup from team ratings.",
      [{"name": "home", "description": "Home team name"},
       {"name": "away", "description": "Away team name"},
       {"name": "team_stats", "description": "Dict of team -> {off_rtg, def_rtg, pace}"}])
def forecast_basketball_matchup(home, away, team_stats):
    return sf.forecast_basketball_matchup(home, away, team_stats)


@tool("check_calibration", "Score a set of probabilistic predictions against actual outcomes -- Brier, ECE, plain-language verdict on whether the probabilities can be trusted.",
      [{"name": "predicted_probs", "description": "List of predicted probabilities [0,1]"},
       {"name": "outcomes", "description": "List of actual outcomes, 0 or 1"}])
def check_calibration(predicted_probs, outcomes):
    return sf.check_calibration(predicted_probs, outcomes)


@tool("size_bet", "Calibration-gated Kelly position sizing. Refuses to size a bet unless a calibration (ECE) score is supplied.",
      [{"name": "p_model", "description": "Model's predicted probability"},
       {"name": "american_odds", "description": "Market odds, American format"},
       {"name": "p_market_fair", "description": "Vig-removed fair market probability"},
       {"name": "bankroll", "description": "Total bankroll available"},
       {"name": "model_ece", "description": "Model's ECE from a real backtest -- required to size anything"}])
def size_bet(p_model, american_odds, p_market_fair, bankroll, model_ece=None):
    return sf.size_bet(p_model, american_odds, p_market_fair, bankroll, model_ece)


@tool("run_epidemic_sim", "Run a stochastic SIR epidemic simulation.",
      [{"name": "population", "description": "Total population N"},
       {"name": "initial_infected", "description": "Initial infected count"},
       {"name": "beta", "description": "Transmission rate"},
       {"name": "gamma", "description": "Recovery rate"}])
def run_epidemic_sim(population, initial_infected, beta, gamma):
    return sf.run_epidemic_sim(population, initial_infected, beta, gamma)


@tool("run_queue_sim", "Run an M/M/1 queue simulation for wait times and utilization.",
      [{"name": "arrival_rate", "description": "Customer arrival rate"},
       {"name": "service_rate", "description": "Service rate"},
       {"name": "t_max", "description": "Simulation time horizon"}])
def run_queue_sim(arrival_rate, service_rate, t_max=10000):
    return sf.run_queue_sim(arrival_rate, service_rate, t_max)


@tool("run_arcsim_view", "Run an ARC-SIM physics module view (fusion energy balance, radial profile, etc). Call list_arcsim_modules first to see what's available and each view's required params.",
      [{"name": "module_id", "description": "e.g. 'fusion'"},
       {"name": "view_id", "description": "e.g. 'energy_balance', 'triple_product', 'radial_profile', 'size_sweep'"},
       {"name": "params", "description": "Dict of params matching that view's params_schema"}])
def run_arcsim_view(module_id, view_id, params):
    return sf.run_arcsim_view(module_id, view_id, params)


@tool("list_arcsim_modules", "List every registered ARC-SIM physics module, its views, and each view's parameter schema.", [])
def list_arcsim_modules():
    return sf.list_arcsim_modules()
