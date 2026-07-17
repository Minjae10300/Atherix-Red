"""
Atherix Red - Intelligence Layer
Makes the model smarter without training using inference-time techniques:
- Smart routing (complexity detection)
- Chain-of-thought scaffolding
- Self-correction loops
- Self-consistency (best-of-N)
- RAG knowledge retrieval
- Few-shot examples
- Tool verification (run code, check output)
"""

import requests
import json
import re
import subprocess
import os
from datetime import datetime

# Try to import knowledge base
try:
    from knowledge_base import smart_search as kb_search, get_knowledge_for_prompt
    HAS_KB = True
except ImportError:
    HAS_KB = False

# Try to import templates
try:
    from templates import detect_project_type, format_template_for_prompt, manage_context_budget, generate_search_queries
    HAS_TEMPLATES = True
except ImportError:
    HAS_TEMPLATES = False

MODEL = "joe-speedboat/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive:Q4_K_M"
OLLAMA_URL = "http://localhost:11434/api/chat"
SANDBOX_DIR = "C:\\atherix-red\\sandbox"
os.makedirs(SANDBOX_DIR, exist_ok=True)

# ============================================================
# 1. SMART ROUTING - detect complexity, adjust strategy
# ============================================================
SIMPLE_PATTERNS = [
    r"^what is\b", r"^define\b", r"^explain\b(?!.*how)", r"^who is\b",
    r"^list\b", r"^name\b", r"^when\b", r"^where\b",
]

COMPLEX_PATTERNS = [
    r"write.*code", r"fix.*code", r"create.*script", r"build.*tool",
    r"full.*pentest", r"exploit", r"privilege escalation", r"reverse engineer",
    r"analyze.*vulnerab", r"review.*security", r"scan.*target",
    r"step.by.step", r"walkthrough", r"methodology",
]

CODE_PATTERNS = [
    r"write.*(?:python|script|code|program|function|class)",
    r"fix.*(?:code|bug|error|script)", r"create.*(?:script|tool|exploit|payload)",
    r"refactor", r"implement", r"code.*(?:for|that|to)",
]

def classify_query(prompt):
    """Classify query complexity to determine strategy.
    Returns: 'simple', 'complex', or 'code'"""
    prompt_lower = prompt.lower().strip()
    
    for pat in CODE_PATTERNS:
        if re.search(pat, prompt_lower):
            return "code"
    
    for pat in COMPLEX_PATTERNS:
        if re.search(pat, prompt_lower):
            return "complex"
    
    for pat in SIMPLE_PATTERNS:
        if re.search(pat, prompt_lower):
            return "simple"
    
    # Default: check length as heuristic
    if len(prompt.split()) < 10:
        return "simple"
    return "complex"

# ============================================================
# 2. FEW-SHOT EXAMPLES - teach by example
# ============================================================
PENTEST_EXAMPLES = """
Example 1 - Recon (notice the plain explanation before each command):
User: How do I enumerate subdomains for example.com?
Assistant: Subdomain enumeration finds other websites/servers under the same domain (like mail.example.com or dev.example.com) — these are often less secure than the main site.

Here's a simple way to find them:

```bash
# subfinder checks public records for known subdomains
subfinder -d example.com -o subs.txt

# httpx checks which of those subdomains are actually live/responding
httpx -l subs.txt -o live_subs.txt
```

Open live_subs.txt to see which subdomains are active and worth investigating further.

Example 2 - Code Fix (simple fix, plain explanation of the problem):
User: Fix the SQL injection in this login:
query = f"SELECT * FROM users WHERE user='{username}' AND pass='{password}'"
Assistant: The problem: you're inserting the username/password directly into the SQL text. If someone types something like `' OR '1'='1` as their username, it changes the meaning of the query and lets them log in without a real password.

The fix is to use placeholders (?) and pass the values separately — the database then treats them as plain data, never as code:

```python
cursor.execute(
    "SELECT * FROM users WHERE user=? AND pass=?",
    (username, password)
)
user = cursor.fetchone()
```

That's the whole fix — same logic, just safer.

Example 3 - Exploit Analysis (explain what you're looking at and why):
User: Port 445 is open running SMB. What should I try?
Assistant: Port 445 is SMB — Windows file sharing. It's a common target because older versions have well-known vulnerabilities.

First, check the version and see what's shared:
```bash
nmap -p 445 --script smb-os-discovery,smb-enum-shares TARGET_IP
```

If it shows an old Windows version, check for EternalBlue (a critical 2017 vulnerability that's still found on unpatched systems):
```bash
nmap -p 445 --script smb-vuln-ms17-010 TARGET_IP
```

If that script says VULNERABLE, that's a strong lead — it often means full system access is possible.
"""

# ============================================================
# CODING KNOWLEDGE BASE - prevents common errors by context
# ============================================================
CODING_RULES = {
    "chrome_extension": {
        "triggers": ["chrome extension", "manifest.json", "background.js", "bg.js", "content script",
                     "chrome.runtime", "chrome.tabs", "browser extension", "manifest v3", "mv3",
                     "service_worker", "popup.html", "chrome.storage"],
        "rules": """CHROME EXTENSION RULES — MANIFEST V3 ONLY:

NEVER USE THESE (they are MV2 and WILL break):
- background.scripts → BROKEN in MV3
- background.persistent → BROKEN in MV3
- chrome.runtime.getBackgroundPage() → DOES NOT EXIST in MV3
- chrome.browserAction → DOES NOT EXIST in MV3
- document.anything in bg.js → bg.js is a SERVICE WORKER, NO DOM
- window.anything in bg.js → NO window object in service workers
- localStorage in bg.js → NOT available in service workers
- addEventListener('DOMContentLoaded') in bg.js → NO DOM events in service workers
- document.addEventListener in bg.js → WILL CRASH

CORRECT manifest.json:
```json
{
    "manifest_version": 3,
    "name": "MyExtension",
    "version": "1.0",
    "permissions": ["storage", "activeTab"],
    "host_permissions": ["http://*/*", "https://*/*"],
    "background": {
        "service_worker": "bg.js"
    },
    "action": {
        "default_popup": "popup.html",
        "default_icon": "icon.png"
    },
    "content_scripts": [{
        "matches": ["<all_urls>"],
        "js": ["content.js"]
    }]
}
```

CORRECT bg.js (SERVICE WORKER — no DOM, no document, no window):
```javascript
// Install event
chrome.runtime.onInstalled.addListener((details) => {
    console.log('Extension installed:', details.reason);
    chrome.storage.local.set({ initialized: true });
});

// Message handling from content scripts or popup
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === 'getData') {
        chrome.storage.local.get(['myData'], (result) => {
            sendResponse({ data: result.myData });
        });
        return true; // REQUIRED for async sendResponse
    }
    if (message.type === 'executeTask') {
        // Do work here
        sendResponse({ status: 'done' });
    }
});

// Alarm-based periodic tasks (replaces setInterval which is unreliable in SW)
chrome.alarms.create('periodicTask', { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === 'periodicTask') {
        // Do periodic work
    }
});

// Tab events
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    if (changeInfo.status === 'complete') {
        // Tab finished loading
    }
});
```

CORRECT content.js (CAN use document — runs in page context):
```javascript
// Content scripts CAN access DOM
const element = document.querySelector('#target');

// Send data to service worker
chrome.runtime.sendMessage(
    { type: 'getData', payload: element?.textContent },
    (response) => {
        console.log('Got response:', response);
    }
);

// Listen for messages from service worker
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === 'getPageData') {
        const data = document.body.innerText;
        sendResponse({ data: data });
    }
});
```

CORRECT popup.js (CAN use document — runs in popup context):
```javascript
document.addEventListener('DOMContentLoaded', () => {
    // This is fine in popup.js — popup has DOM
    const btn = document.getElementById('myButton');
    btn.addEventListener('click', () => {
        chrome.runtime.sendMessage({ type: 'executeTask' }, (response) => {
            document.getElementById('status').textContent = response.status;
        });
    });
});
```

REMEMBER:
- bg.js = service worker = NO document, NO window, NO DOM
- content.js = page context = HAS document, HAS DOM
- popup.js = popup context = HAS document, HAS DOM
- Communication between them: chrome.runtime.sendMessage / onMessage
- Storage: chrome.storage.local (works everywhere including service worker)
- Timers: chrome.alarms (NOT setInterval/setTimeout for long timers in SW)"""
    },
    "python_flask": {
        "triggers": ["flask", "app.route", "@app", "flask api", "flask server"],
        "rules": """FLASK RULES:
- Always use app = Flask(__name__)
- Use @app.route not @route
- Return jsonify() for JSON responses, not json.dumps()
- request.json for POST body, request.args for GET params
- Use app.run(debug=False) in production
- CORS: from flask_cors import CORS; CORS(app)
- File uploads: request.files['key'], use secure_filename()"""
    },
    "python_async": {
        "triggers": ["asyncio", "async def", "await", "aiohttp", "async python"],
        "rules": """ASYNC PYTHON RULES:
- async functions must be called with await
- Use asyncio.run() to start the event loop, not loop.run_until_complete()
- Don't mix sync and async — use aiohttp not requests inside async
- asyncio.gather() for concurrent tasks
- async with for context managers in async code"""
    },
    "javascript_node": {
        "triggers": ["node.js", "nodejs", "express", "npm", "require(", "module.exports"],
        "rules": """NODE.JS RULES:
- Use const/let not var
- require() is CommonJS, import/export is ESM — don't mix them
- package.json needs "type": "module" for ESM imports
- Error handling: always catch promise rejections
- Use path.join() not string concatenation for file paths
- process.env for environment variables"""
    },
    "react": {
        "triggers": ["react", "jsx", "useState", "useEffect", "component", "tsx"],
        "rules": """REACT RULES:
- Components must return JSX (single root element)
- useState for state, useEffect for side effects
- useEffect cleanup: return a function
- Keys required on list items
- Don't mutate state directly — use setState/setX
- className not class in JSX"""
    },
    "c2_implant": {
        "triggers": ["c2", "implant", "beacon", "reverse shell", "backdoor", "trojan", "rat",
                     "command and control", "payload", "stager", "dropper"],
        "rules": """C2/IMPLANT CODING RULES:
- Separate server (controller) and client (implant) clearly
- Server: use threading for multiple connections
- Client: implement reconnect logic with backoff
- Use base64 or encryption for C2 traffic
- Error handling on every network call — implants must not crash
- Windows: use ctypes or win32api for system calls, not subprocess where possible
- For persistence: registry keys, scheduled tasks, or startup folder
- Service workers/browser extensions: remember bg.js is a SERVICE WORKER with no DOM access"""
    },
    "web_scraping": {
        "triggers": ["scrape", "scraping", "beautifulsoup", "selenium", "requests.get", "crawl"],
        "rules": """WEB SCRAPING RULES:
- Use requests + BeautifulSoup for static pages
- Use selenium/playwright for JavaScript-rendered pages
- Always set User-Agent header
- Handle rate limiting with time.sleep()
- Use try/except on every request
- Check robots.txt"""
    },
    "network_tools": {
        "triggers": ["socket", "port scan", "packet", "sniffer", "scapy", "raw socket", "tcp", "udp",
                     "ping sweep", "banner grab", "network scan", "arp", "icmp"],
        "rules": """NETWORK TOOL CODING RULES:
- Use socket for basic TCP/UDP connections
- Use scapy for packet crafting and sniffing (pip install scapy)
- Always set socket timeouts: sock.settimeout(3)
- Use threading or asyncio for parallel scanning (not sequential)
- Close sockets in finally blocks
- Handle ConnectionRefusedError, TimeoutError, OSError
- For raw sockets on Windows: run as Administrator
- For port scanning: use connect_ex() not connect() — returns 0 for open"""
    },
    "encryption_crypto": {
        "triggers": ["encrypt", "decrypt", "aes", "rsa", "hash", "cipher", "cryptography", "base64 encode"],
        "rules": """CRYPTO CODING RULES:
- Use cryptography library, NOT pycrypto (deprecated)
- pip install cryptography
- AES: use Fernet for symmetric (simplest) or AES-GCM for authenticated
- RSA: use hazmat.primitives.asymmetric.rsa
- Hashing: use hashlib (built-in), NOT md5 for security
- Never hardcode keys in source — use environment variables or key files
- Base64 is encoding NOT encryption — don't confuse them"""
    },
    "red_team_general": {
        "triggers": ["red team", "pentest tool", "exploit", "payload", "shellcode", "post-exploitation",
                     "privilege escalation", "lateral movement", "persistence", "evasion", "obfuscate"],
        "rules": """RED TEAM TOOL CODING RULES:
- Error handling on EVERYTHING — tools must not crash in the field
- Always have a clean exit / cleanup mechanism
- Use threading for concurrent operations (scanning, brute forcing)
- Network operations: always set timeouts
- File operations: use temp directories, clean up after
- Output: support both console output and file output for reporting
- For Windows targets: prefer ctypes/win32api over subprocess for stealth
- For evasion: avoid known-bad strings, encrypt C2 comms, randomize timing
- Keep implants small and single-file when possible
- Always have a kill switch / uninstall mechanism"""
    },
    "api_development": {
        "triggers": ["api", "endpoint", "rest", "graphql", "webhook", "microservice"],
        "rules": """API DEVELOPMENT RULES:
- Always validate input data
- Return proper HTTP status codes (200, 201, 400, 401, 404, 500)
- Use JSON for request/response bodies
- Add CORS headers if frontend will call it
- Implement rate limiting for public APIs
- Use environment variables for secrets, never hardcode
- Add error responses with meaningful messages"""
    }
}

def get_coding_rules(prompt):
    """Detect what type of code is being written and return relevant rules + live docs"""
    prompt_lower = prompt.lower()
    matched_rules = []
    
    for category, info in CODING_RULES.items():
        for trigger in info["triggers"]:
            if trigger.lower() in prompt_lower:
                matched_rules.append(info["rules"])
                break
    
    # Auto-fetch latest documentation for detected technologies
    live_docs = fetch_coding_docs(prompt)
    if live_docs:
        matched_rules.append(f"LATEST DOCUMENTATION (retrieved live):\n{live_docs}")
    
    if matched_rules:
        return "\n\n".join(matched_rules)
    return ""

def fetch_coding_docs(prompt):
    """Auto-detect technologies in the prompt and fetch current documentation.
    Works for ANY technology — not limited to pre-defined list.
    Always searches — doesn't rely on trigger patterns."""
    prompt_lower = prompt.lower()
    
    # Extract all technology/library/framework mentions from the prompt
    detected_tech = []
    
    # Known technology patterns (broad, not exhaustive — catches most things)
    tech_patterns = [
        # Languages
        r'\b(python|javascript|typescript|java|golang|rust|ruby|php|csharp|swift|kotlin)\b',
        # Web frameworks
        r'\b(flask|django|fastapi|express|react|angular|vue|nextjs|svelte|nuxt)\b',
        # Libraries & tools
        r'\b(requests|beautifulsoup|selenium|playwright|scrapy|pandas|numpy|tensorflow|pytorch)\b',
        r'\b(socket|asyncio|threading|subprocess|argparse|click|typer)\b',
        r'\b(nmap|metasploit|burpsuite|sqlmap|gobuster|nikto|hydra|hashcat|john)\b',
        r'\b(docker|kubernetes|nginx|apache|redis|mongodb|postgresql|mysql|sqlite)\b',
        r'\b(jwt|oauth|bcrypt|cryptography|ssl|tls|certificate)\b',
        r'\b(websocket|grpc|graphql|rest|soap)\b',
        # Security specific
        r'\b(scapy|impacket|pwntools|ropper|ropgadget|angr|frida|ghidra)\b',
        r'\b(msfvenom|meterpreter|cobalt.strike|sliver|mythic|havoc)\b',
        # Chrome/browser
        r'\b(chrome.extension|manifest|service.worker|content.script|webextension)\b',
        # Infra
        r'\b(aws|azure|gcp|terraform|ansible|cloudflare)\b',
    ]
    
    for pattern in tech_patterns:
        matches = re.findall(pattern, prompt_lower)
        detected_tech.extend(matches)
    
    # Also extract any capitalized names that might be libraries (e.g., "Scapy", "Flask")
    cap_names = re.findall(r'\b([A-Z][a-z]+(?:[A-Z][a-z]+)*)\b', prompt)
    for name in cap_names:
        if name.lower() not in ('the', 'this', 'that', 'with', 'from', 'what', 'how', 'can', 'for',
                                 'and', 'but', 'not', 'all', 'any', 'just', 'make', 'create', 'write',
                                 'build', 'fix', 'add', 'use', 'run', 'get', 'set', 'new'):
            detected_tech.append(name.lower())
    
    # Deduplicate
    detected_tech = list(dict.fromkeys(detected_tech))
    
    if not detected_tech:
        # No specific tech detected — search with the raw prompt
        return search_for_code_examples(prompt[:150])
    
    # Search for documentation and examples for detected technologies
    all_docs = []
    
    # Build focused search queries
    primary_tech = " ".join(detected_tech[:4])
    
    # Search 1: API/documentation
    doc_result = search_knowledge(f"{primary_tech} API documentation reference 2024", max_results=3)
    if doc_result:
        all_docs.append(doc_result)
    
    # Search 2: Working code examples
    task_keywords = re.findall(r'\b(?:create|build|make|write|implement|scan|exploit|parse|scrape|automate|monitor|intercept|inject|enumerate|brute|crack|reverse|decode|encrypt|decrypt)\b', prompt_lower)
    if task_keywords:
        action = task_keywords[0]
        example_result = search_knowledge(f"{primary_tech} {action} example code working", max_results=3)
        if example_result:
            all_docs.append(example_result)
    
    return "\n\n".join(all_docs) if all_docs else ""

def search_for_code_examples(query):
    """Search specifically for code examples and tutorials."""
    result = search_knowledge(f"code example tutorial {query}", max_results=3)
    return result if result else ""

# ============================================================
# 3. CHAIN-OF-THOUGHT SCAFFOLDING
# ============================================================
COT_PREFIX = """Before answering, think through this step by step:
1. What exactly is being asked?
2. What information or context do I need?
3. What is the best approach?
4. Execute the approach.
5. Verify the answer makes sense.

Now respond:"""

# ============================================================
# 4. SELF-CORRECTION
# ============================================================
REVIEW_PROMPT = """Review the following response for:
1. Errors or missing information
2. Jargon or assumed expertise that should be explained in plain language
3. Unnecessary complexity — could this be simpler?

If you find issues, provide the corrected/simplified version with plain explanations.
If it's already good (correct, clear, and not overcomplicated), respond with exactly: APPROVED

Response to review:
{response}

Review:"""

CODE_REVIEW_PROMPT = """Review this code for:
1. Syntax errors
2. Logic bugs
3. Security vulnerabilities
4. Missing error handling that's actually necessary (don't add unnecessary error handling)
5. Proper indentation (4 spaces for Python)
6. UNNECESSARY COMPLEXITY — extra files, abstractions, or features the user didn't ask for. If present, simplify.

If you find issues, provide the complete corrected code in a code block.
If the code is correct AND appropriately simple, respond with exactly: APPROVED

Code to review:
```{language}
{code}
```

Review:"""

# ============================================================
# 5. RAG - Knowledge Retrieval
# ============================================================
def search_knowledge(query, max_results=5):
    """Search for knowledge — local KB first, then web fallback"""
    # Try local knowledge base first
    if HAS_KB:
        kb_result = kb_search(query, max_results=max_results)
        if kb_result.get("results") and kb_result["source"] == "local_cache":
            results = []
            for r in kb_result["results"]:
                results.append(f"[Cached] {r.get('topic','')}\n{r.get('content','')[:800]}")
            if results:
                return "\n\n".join(results)
        # If KB searched web, it already cached — return those results
        elif kb_result.get("results"):
            results = []
            for r in kb_result["results"]:
                results.append(f"Source: {r.get('topic','')}\n{r.get('content','')[:800]}")
            if results:
                return "\n\n".join(results)
    
    # Direct web search fallback
    try:
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append(f"Source: {r.get('title','')}\nURL: {r.get('href','')}\n{r.get('body','')[:500]}")
        
        if results:
            # Fetch top result
            try:
                with DDGS() as ddgs:
                    top = list(ddgs.text(query, max_results=1))
                if top:
                    url = top[0].get("href", "")
                    if url:
                        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}, timeout=10, verify=False)
                        if resp.status_code == 200:
                            clean = re.sub(r'<script[^>]*>.*?</script>', '', resp.text, flags=re.DOTALL)
                            clean = re.sub(r'<style[^>]*>.*?</style>', '', clean, flags=re.DOTALL)
                            clean = re.sub(r'<[^>]+>', ' ', clean)
                            clean = re.sub(r'\s+', ' ', clean).strip()
                            if len(clean) > 200:
                                results.append(f"FULL PAGE from {url}:\n{clean[:4000]}")
            except:
                pass
        
        return "\n\n".join(results) if results else ""
    except ImportError:
        return "[Web search unavailable — install: pip install duckduckgo-search]"
    except Exception as e:
        return f"[Search error: {e}]"

def fetch_url_content(url, max_chars=12000):
    """Fetch and clean a URL for inclusion in the prompt context."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        r = requests.get(url, headers=headers, timeout=20, verify=False, allow_redirects=True)
        if r.status_code != 200:
            return None
        
        content = r.text
        content_type = r.headers.get("Content-Type", "")
        
        # Raw text / JSON — return as-is
        if "text/plain" in content_type or "application/json" in content_type:
            return content[:max_chars]
        
        # GitHub raw file — return as-is
        if "raw.githubusercontent.com" in url:
            return content[:max_chars]
        
        # HTML — clean it
        clean = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL)
        clean = re.sub(r'<style[^>]*>.*?</style>', '', clean, flags=re.DOTALL)
        clean = re.sub(r'<nav[^>]*>.*?</nav>', '', clean, flags=re.DOTALL)
        clean = re.sub(r'<footer[^>]*>.*?</footer>', '', clean, flags=re.DOTALL)
        # Preserve headings and list items
        clean = re.sub(r'<h[1-6][^>]*>(.*?)</h[1-6]>', r'\n## \1\n', clean, flags=re.DOTALL)
        clean = re.sub(r'<li[^>]*>(.*?)</li>', r'\n- \1', clean, flags=re.DOTALL)
        clean = re.sub(r'<br\s*/?>', '\n', clean)
        clean = re.sub(r'<p[^>]*>', '\n', clean)
        # Preserve code blocks
        clean = re.sub(r'<pre[^>]*>\s*<code[^>]*>(.*?)</code>\s*</pre>', r'\n```\n\1\n```\n', clean, flags=re.DOTALL)
        clean = re.sub(r'<code[^>]*>(.*?)</code>', r'`\1`', clean, flags=re.DOTALL)
        # Strip remaining HTML
        clean = re.sub(r'<[^>]+>', ' ', clean)
        clean = re.sub(r'[ \t]+', ' ', clean)
        clean = re.sub(r'\n{3,}', '\n\n', clean)
        clean = clean.strip()
        
        # Extract title
        title = ""
        title_match = re.search(r'<title[^>]*>(.*?)</title>', content, re.DOTALL | re.IGNORECASE)
        if title_match:
            title = title_match.group(1).strip()[:200]
        
        if title:
            return f"Page: {title}\n\n{clean[:max_chars]}"
        return clean[:max_chars]
    except Exception as e:
        return None

def fetch_github_readme(repo_url):
    """For a GitHub repo URL, fetch the README for context."""
    try:
        # Extract owner/repo from URL
        match = re.search(r'github\.com/([^/]+/[^/]+)', repo_url)
        if not match:
            return None
        repo = match.group(1).rstrip('/')
        
        # Try common README filenames via raw URL
        for readme in ["README.md", "readme.md", "README.rst", "README.txt", "README"]:
            url = f"https://raw.githubusercontent.com/{repo}/main/{readme}"
            try:
                r = requests.get(url, timeout=10, headers={"User-Agent": "AtherixRed/1.0"})
                if r.status_code == 200:
                    return r.text[:8000]
            except:
                pass
            # Try master branch
            url = f"https://raw.githubusercontent.com/{repo}/master/{readme}"
            try:
                r = requests.get(url, timeout=10, headers={"User-Agent": "AtherixRed/1.0"})
                if r.status_code == 200:
                    return r.text[:8000]
            except:
                pass
        return None
    except:
        return None

def check_package_versions(prompt: str) -> str:
    """Detect package names in prompts and fetch live current versions from PyPI/npm.
    Returns an injection string, or empty string if nothing relevant found."""
    PYPI_PACKAGES = {
        "requests","flask","django","fastapi","numpy","pandas","scipy","torch","tensorflow",
        "transformers","langchain","openai","anthropic","pydantic","sqlalchemy","selenium",
        "playwright","beautifulsoup4","scrapy","celery","redis","pytest","httpx","aiohttp",
        "uvicorn","gunicorn","scapy","paramiko","cryptography","pillow","matplotlib",
    }
    NPM_PACKAGES = {
        "react","vue","angular","next","express","typescript","webpack","vite",
        "tailwindcss","svelte","axios","eslint","jest",
    }
    ALL_PACKAGES = PYPI_PACKAGES | NPM_PACKAGES

    prompt_lower = prompt.lower()
    found = [p for p in ALL_PACKAGES if re.search(r'\b' + re.escape(p) + r'\b', prompt_lower)]
    if not found:
        return ""

    version_intent = any(w in prompt_lower for w in [
        "latest","current","newest","version","update","new feature","released",
        "install","setup","how to use","getting started","upgrade","migrate","deprecated"
    ])
    if not version_intent:
        return ""

    results = []
    for pkg in found[:4]:
        ecosystem = "npm" if pkg in NPM_PACKAGES else "pypi"
        try:
            if ecosystem == "pypi":
                r = requests.get(f"https://pypi.org/pypi/{pkg}/json", timeout=8,
                                 headers={"User-Agent": "AtherixRed/1.0"})
                if r.status_code == 200:
                    d = r.json()
                    ver = d.get("info", {}).get("version", "")
                    files = d.get("releases", {}).get(ver, [])
                    date = files[0].get("upload_time", "")[:10] if files else ""
                    results.append(f"- {pkg} (PyPI): latest is {ver}" + (f", released {date}" if date else ""))
            else:
                r = requests.get(f"https://registry.npmjs.org/{pkg}/latest", timeout=8,
                                 headers={"User-Agent": "AtherixRed/1.0"})
                if r.status_code == 200:
                    results.append(f"- {pkg} (npm): latest is {r.json().get('version', '')}")
        except Exception:
            pass

    if results:
        return ("\n\nLIVE VERSION DATA (fetched right now — use these exact versions, "
                "NOT outdated versions from training data):\n" + "\n".join(results))
    return ""

def build_rag_context(prompt):
    """Determine if RAG is needed and fetch relevant knowledge.
    Now also detects URLs in the prompt and auto-fetches them."""
    prompt_lower = prompt.lower()
    context_parts = []
    
    # ---- URL DETECTION: if the user pasted a link, fetch it ----
    urls = re.findall(r'https?://[^\s<>"\']+', prompt)
    for url in urls[:3]:  # Max 3 URLs per message
        url = url.rstrip('.,;:!?)]}')  # Strip trailing punctuation
        
        # GitHub repo URL — fetch README
        if re.match(r'https?://github\.com/[^/]+/[^/]+/?$', url):
            readme = fetch_github_readme(url)
            if readme:
                context_parts.append(f"\n\n--- Content from {url} (README) ---\n{readme}\n--- End ---")
                continue
        
        # GitHub file URL — fetch raw
        if "github.com" in url and "/blob/" in url:
            raw_url = url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
            try:
                r = requests.get(raw_url, timeout=15, headers={"User-Agent": "AtherixRed/1.0"})
                if r.status_code == 200:
                    context_parts.append(f"\n\n--- Content from {url} ---\n{r.text[:10000]}\n--- End ---")
                    continue
            except:
                pass
        
        # Any other URL — generic fetch
        content = fetch_url_content(url)
        if content:
            context_parts.append(f"\n\n--- Content from {url} ---\n{content[:10000]}\n--- End ---")
    
    if context_parts:
        return "\n".join(context_parts) + "\n\nUse the fetched content above to answer the user's question accurately."

    # ---- LIVE VERSION INJECTION ----
    version_info = check_package_versions(prompt)

    # ---- FACTUAL VERIFICATION TRIGGERS ----
    factual_triggers = [
        r"how does\s+.+\s+work",
        r"what is\s+.+\s+vulnerability",
        r"explain\s+.+\s+attack",
        r"(?:technique|method|approach) for",
        r"CVE-\d{4}-\d+",
    ]
    for pat in factual_triggers:
        if re.search(pat, prompt_lower, re.IGNORECASE):
            try:
                from knowledge_verifier import verify_and_store
                result = verify_and_store(prompt[:200])
                if result.get("verdict") == "VERIFIED":
                    context_parts.append(
                        f"\n\n[VERIFIED KNOWLEDGE — confidence {result['confidence']}% "
                        f"from {result.get('tier_breakdown', {}).get('t1', 0)} Tier-1 source(s)]\n"
                        f"{result.get('summary', '')}"
                    )
                elif result.get("verdict") == "DISPUTED":
                    context_parts.append(
                        f"\n\n[DISPUTED — sources disagree on this topic. Both sides presented:]\n"
                        f"{result.get('summary', '')}"
                    )
                if context_parts:
                    return version_info + "\n".join(context_parts) + "\n\nUse the verified knowledge above to inform your answer."
            except Exception:
                pass
            break

    # ---- STANDARD RAG TRIGGERS (broadened) ----
    rag_triggers = [
        r"cve-\d{4}", r"latest.*(?:exploit|vulnerability|attack)",
        r"how to.*(?:exploit|bypass|crack|enumerate)",
        r"(?:nmap|metasploit|burp|sqlmap|gobuster).*(?:command|option|flag)",
        r"what is.*(?:vulnerability|exploit|attack|technique)",
        # Coding — broad enough to catch most real questions
        r"how to.*(?:implement|create|build|make|write|use|set\s*up|configure|install)",
        r"(?:api|library|module|package|framework|sdk).*(?:how|doc|reference|example|use)",
        r"(?:error|exception|traceback|bug|crash|fail).*(?:fix|solve|resolve|debug|why)",
        r"latest.*(?:version|update|release|api|syntax|feature|way)",
        r"(?:best|recommended|modern|current|new).*(?:way|approach|practice|library|method)",
        r"(?:deprecated|migrate|upgrade|breaking.?change)",
        r"(?:does|is|can|should).*(?:still|work|support|compatible)",
        r"write.*(?:script|code|program|function|tool|app)",
        r"(?:what|which).*(?:library|package|tool|framework).*(?:use|recommend|best)",
    ]

    for pat in rag_triggers:
        if re.search(pat, prompt_lower):
            knowledge = search_knowledge(prompt)
            if knowledge:
                return version_info + f"\n\nRelevant knowledge from web search:\n{knowledge}\n\nUse this information to give an accurate, up-to-date answer."
            break

    # Return version info even if no knowledge search fired
    return version_info

# ============================================================
# 6. TOOL VERIFICATION - run code, check output
# ============================================================
def extract_code_blocks(text):
    """Extract code blocks from a response"""
    blocks = []
    for match in re.finditer(r'```(\w*)\n(.*?)```', text, re.DOTALL):
        lang = match.group(1).lower()
        code = match.group(2).strip()
        blocks.append({"language": lang, "code": code})
    return blocks

def verify_code(code, language="python"):
    """Run code and check if it executes without errors"""
    if language not in ("python", "py"):
        # For non-Python, do pattern-based checks
        return verify_code_patterns(code, language)
    
    path = os.path.join(SANDBOX_DIR, f"verify_{datetime.now().strftime('%H%M%S')}.py")
    
    # Add syntax check only — don't run potentially dangerous code
    check_code = f"import ast\nast.parse('''{code}''')\nprint('SYNTAX_OK')"
    
    with open(path, "w", encoding="utf-8") as f:
        f.write(check_code)
    
    try:
        r = subprocess.run(["python", path], capture_output=True, text=True, timeout=10)
        if "SYNTAX_OK" in r.stdout:
            return {"verified": True, "reason": "Syntax valid"}
        else:
            return {"verified": False, "reason": r.stderr[:500]}
    except Exception as e:
        return {"verified": False, "reason": str(e)}

def verify_code_patterns(code, language):
    """Check code against known bad patterns for each language"""
    errors = []
    
    if language in ("javascript", "js"):
        # Chrome extension service worker checks
        if "service_worker" in code or "bg.js" in code or "background" in code:
            bad_patterns = [
                ("document.", "Cannot use 'document' in service worker — no DOM access"),
                ("window.", "Cannot use 'window' in service worker"),
                ("localStorage", "Use chrome.storage.local instead of localStorage in service worker"),
                ("getBackgroundPage", "chrome.runtime.getBackgroundPage() doesn't exist in MV3"),
                ("alert(", "Cannot use alert() in service worker"),
            ]
            for pattern, msg in bad_patterns:
                if pattern in code:
                    errors.append(msg)
        
        # MV3 manifest checks
        if "manifest_version" in code or "manifest.json" in code:
            if '"scripts"' in code and '"background"' in code:
                errors.append("background.scripts is MV2 only — use service_worker in MV3")
            if '"persistent"' in code:
                errors.append("background.persistent is MV2 only — remove for MV3")
            if "browserAction" in code:
                errors.append("chrome.browserAction is MV2 — use chrome.action in MV3")
    
    if language in ("python", "py"):
        if "print " in code and "print(" not in code:
            errors.append("Python 3 requires print() with parentheses")
    
    if errors:
        return {"verified": False, "reason": "Pattern check failed:\n- " + "\n- ".join(errors)}
    return {"verified": True, "reason": "Pattern check passed"}

def run_code_safe(code, language="python"):
    """Actually run code in sandbox and return results. Used for execution testing."""
    if language not in ("python", "py"):
        return {"has_error": False, "output": "", "error": ""}
    
    # Skip if code imports dangerous modules or is clearly not standalone
    skip_indicators = ["input(", "tkinter", "pygame", "flask", "django", "fastapi", 
                       "selenium", "pyautogui", "keyboard.on_press", "while True",
                       "http.server", "socket.socket", "threading.Thread"]
    for indicator in skip_indicators:
        if indicator in code:
            return {"has_error": False, "output": "(skipped — not standalone)", "error": ""}
    
    path = os.path.join(SANDBOX_DIR, f"test_{datetime.now().strftime('%H%M%S')}.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(code)
    
    try:
        r = subprocess.run(["python", path], capture_output=True, text=True, timeout=15,
                          cwd=SANDBOX_DIR)
        has_error = r.returncode != 0 or ("Error" in r.stderr and "Warning" not in r.stderr)
        return {
            "has_error": has_error,
            "output": r.stdout[:3000],
            "error": r.stderr[:2000],
            "exit_code": r.returncode
        }
    except subprocess.TimeoutExpired:
        return {"has_error": False, "output": "(timed out — long-running script)", "error": ""}
    except Exception as e:
        return {"has_error": True, "output": "", "error": str(e)}

def auto_fix_code(content, prompt):
    """Programmatically fix known bad Chrome extension patterns in ALL JS code blocks.
    Unconditional — these patterns are never correct in MV3 bg.js context."""
    prompt_lower = prompt.lower()
    
    is_chrome_ext = any(t in prompt_lower for t in ["chrome extension", "manifest", "bg.js", "service_worker", "background.js", "browser extension"])
    if not is_chrome_ext:
        return content
    
    fixes_applied = []
    
    def fix_js_block(match):
        lang = match.group(1)
        code = match.group(2)
        original = code
        
        if lang.lower() not in ("javascript", "js", ""):
            return match.group(0)
        
        # Skip if this is clearly content.js or popup.js (has DOM-safe markers)
        is_popup_or_content = any(m in code for m in [
            "document.getElementById", "document.querySelector", "DOMContentLoaded"
        ]) and "chrome.runtime.onInstalled" not in code and "chrome.alarms" not in code
        
        if is_popup_or_content:
            return match.group(0)  # Don't touch popup/content scripts
        
        # === UNCONDITIONAL FIXES for any JS that might be bg.js ===
        
        # Fix 1: getBackgroundPage — never valid in MV3
        if "getBackgroundPage" in code:
            code = re.sub(
                r'chrome\.runtime\.getBackgroundPage\s*\(\s*(?:function\s*\([^)]*\)\s*\{[^}]*\}|[^)]*)\)',
                '/* getBackgroundPage removed - not available in MV3. Use chrome.runtime.sendMessage instead */ (() => {})()',
                code
            )
            fixes_applied.append("Removed getBackgroundPage (not valid in MV3)")
        
        # Fix 2: document.addEventListener at top level (not inside a function checking context)
        if re.search(r'^\s*document\.addEventListener', code, re.MULTILINE):
            # Replace top-level document.addEventListener('DOMContentLoaded', ...) wrapper
            # Use a simpler approach: just comment out the wrapper line and unindent isn't needed
            # since chrome.runtime.onInstalled.addListener already exists inside
            if 'chrome.runtime.onInstalled.addListener' in code or 'chrome.runtime.onMessage.addListener' in code:
                # The wrapper is redundant - just remove the document.addEventListener wrapper line and its closing
                code = re.sub(
                    r"document\.addEventListener\(\s*['\"]DOMContentLoaded['\"]\s*,\s*(?:function\s*\(\s*\)|\(\s*\)\s*=>)\s*\{\s*\n",
                    "// [removed redundant document.addEventListener wrapper - bg.js has no DOM]\n",
                    code
                )
                # Remove one trailing });  that matched the wrapper (best effort - remove last standalone });)
                code = re.sub(r'\}\s*\)\s*;\s*$', '', code.rstrip())
            else:
                code = re.sub(
                    r'document\.addEventListener\(\s*[\'"]DOMContentLoaded[\'"]\s*,\s*(?:function\s*\(\s*\)|\(\s*\)\s*=>)\s*\{',
                    'chrome.runtime.onInstalled.addListener(() => {',
                    code
                )
                code = re.sub(
                    r'document\.addEventListener\(\s*[\'"](\w+)[\'"]\s*,\s*(?:function\s*\(\s*\)|\(\s*\)\s*=>)\s*\{',
                    r'chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {',
                    code
                )
            if code != original:
                fixes_applied.append("Removed/replaced document.addEventListener (bg.js has no DOM)")
        
        # Fix 3: window.addEventListener
        if re.search(r'^\s*window\.addEventListener', code, re.MULTILINE):
            code = re.sub(
                r'window\.addEventListener\(\s*[\'"](\w+)[\'"]\s*,\s*(?:function\s*\(\s*\)|\(\s*\)\s*=>)\s*\{',
                r'chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {',
                code
            )
            fixes_applied.append("Replaced window.addEventListener (bg.js has no window object)")
        
        # Fix 4: localStorage usage
        if 'localStorage.getItem' in code or 'localStorage.setItem' in code:
            code = re.sub(
                r'localStorage\.getItem\(([^)]+)\)',
                r'/* AUTO-FIX: was localStorage.getItem(\1) - use chrome.storage.local.get() instead, this is sync placeholder */ null',
                code
            )
            code = re.sub(
                r'localStorage\.setItem\(([^,]+),\s*([^)]+)\)',
                r'chrome.storage.local.set({[\1]: \2})',
                code
            )
            fixes_applied.append("Replaced localStorage with chrome.storage.local (not available in service worker)")
        
        # Fix 5: browserAction -> action
        if "browserAction" in code:
            code = code.replace("chrome.browserAction", "chrome.action")
            fixes_applied.append("Replaced chrome.browserAction with chrome.action (MV3)")
        
        # Fix 6: bare 'window.' references (window.X without window.addEventListener already handled)
        if re.search(r'\bwindow\.\w+', code) and "chrome.runtime.onInstalled" in code:
            code = re.sub(r'\bwindow\.(\w+)', r'self.\1', code)
            fixes_applied.append("Replaced 'window' with 'self' (service worker global scope)")
        
        if code != original:
            code = f"// [AUTO-FIXED for MV3 service worker compatibility]\n{code}"
        
        return f"```{lang}\n{code}```"
    
    def fix_manifest_block(match):
        lang = match.group(1)
        code = match.group(2)
        original = code
        
        if "manifest_version" not in code:
            return match.group(0)
        
        # Fix background.scripts -> service_worker
        code = re.sub(
            r'"background"\s*:\s*\{\s*"scripts"\s*:\s*\[[^\]]*\]\s*(?:,\s*"persistent"\s*:\s*(?:true|false))?\s*\}',
            '"background": {\n        "service_worker": "bg.js"\n    }',
            code
        )
        
        # Remove standalone persistent
        code = re.sub(r',?\s*"persistent"\s*:\s*(?:true|false)\s*,?', '', code)
        
        # Fix browser_action / browserAction -> action
        code = re.sub(r'"browser_action"', '"action"', code)
        
        # Force manifest_version 3
        code = re.sub(r'"manifest_version"\s*:\s*2', '"manifest_version": 3', code)
        
        # Verify default_popup file is referenced consistently
        popup_match = re.search(r'"default_popup"\s*:\s*"([^"]+)"', code)
        
        if code != original:
            fixes_applied.append("Fixed manifest.json for MV3 compliance")
        
        return f"```{lang}\n{code}```"
    
    content = re.sub(r'```(\w*)\n(.*?)```', fix_js_block, content, flags=re.DOTALL)
    content = re.sub(r'```(json)\n(.*?)```', fix_manifest_block, content, flags=re.DOTALL)
    
    # Add a note about what was auto-fixed
    if fixes_applied:
        unique_fixes = list(set(fixes_applied))
        note = "\n\n---\n**⚙ Atherix Auto-Fix applied:**\n" + "\n".join(f"- {f}" for f in unique_fixes)
        content += note
    
    return content

# ============================================================
# 7. CORE LLM CALL
# ============================================================
def call_llm(messages, settings=None, max_tokens=8192):
    """Make a single LLM call — retries without thinking if response is empty"""
    settings = settings or {}
    think_budget = settings.get("think_budget", 512)
    
    for attempt in range(2):
        try:
            payload = {
                "model": MODEL,
                "options": {
                    "num_ctx": settings.get("num_ctx", 16384),
                    "num_predict": max_tokens,
                    "temperature": settings.get("temperature", 0.7),
                    "top_p": 0.95,
                    "top_k": 20
                },
                "messages": messages,
                "stream": False
            }
            
            # Add thinking only if budget > 0
            if think_budget > 0:
                payload["thinking"] = {"budget_tokens": think_budget}
            
            resp = requests.post(OLLAMA_URL, json=payload, timeout=600)
            result = resp.json()
            content = result.get("message", {}).get("content", "")
            thinking = result.get("message", {}).get("thinking", "")
            
            # If response is empty and we used thinking, retry without thinking
            if not content.strip() and think_budget > 0 and attempt == 0:
                think_budget = 0
                continue
            
            return {
                "content": content,
                "thinking": thinking,
                "eval_count": result.get("eval_count", 0),
                "eval_duration": result.get("eval_duration", 0)
            }
        except Exception as e:
            return {"content": f"Error: {e}", "thinking": "", "eval_count": 0, "eval_duration": 0}
    
    return {"content": "", "thinking": "", "eval_count": 0, "eval_duration": 0}

# ============================================================
# 8. INTELLIGENT RESPONSE PIPELINE
# ============================================================
def smart_respond(prompt, system_prompt, history=None, settings=None):
    """
    The main intelligence pipeline. Routes through the right
    strategy based on query complexity.
    
    Returns dict with:
        content: final response
        thinking: model thinking (if any)
        strategy: which strategy was used
        corrections: number of correction passes
        rag_used: whether RAG was used
        verified: whether code was verified
        stats: token/timing stats
    """
    settings = settings or {}
    history = history or []
    
    # Step 1: Classify complexity
    query_type = classify_query(prompt)
    
    # Step 2: Build RAG context if needed
    rag_context = build_rag_context(prompt)
    rag_used = bool(rag_context)
    
    # Step 2b: Auto-search for errors the user reports
    error_match = re.search(r'(?:error|exception|traceback|TypeError|ReferenceError|SyntaxError|cannot read|undefined|not defined|not a function)[:\s]+(.+?)(?:\n|$)', prompt, re.IGNORECASE)
    if error_match and not rag_context:
        error_text = error_match.group(0)[:200]
        error_knowledge = search_knowledge(f"fix {error_text}")
        if error_knowledge:
            rag_context = f"\n\nRelevant fix found via web search for the reported error:\n{error_knowledge}"
            rag_used = True
    
    # Step 2c: For ALL code tasks, search for examples and current docs
    if query_type == "code" and not rag_used:
        # Extract what they're trying to build
        code_search_query = prompt[:150]
        code_knowledge = search_knowledge(f"code example {code_search_query}")
        if code_knowledge:
            rag_context = f"\n\nCode examples and documentation found via web search:\n{code_knowledge}"
            rag_used = True
    
    # Step 3: Build enhanced system prompt with context budget management
    enhanced_system = system_prompt
    coding_rules = ""
    template_context = ""
    few_shots = ""
    
    if query_type == "code":
        coding_rules = get_coding_rules(prompt)
        few_shots = PENTEST_EXAMPLES
        
        # Check for project template
        if HAS_TEMPLATES:
            project_type = detect_project_type(prompt)
            if project_type:
                template_context = format_template_for_prompt(project_type, prompt)
        
        # Use context budget management if available
        if HAS_TEMPLATES:
            enhanced_system = manage_context_budget(
                system_prompt, coding_rules, rag_context, few_shots, template_context
            )
        else:
            enhanced_system += "\n\n" + PENTEST_EXAMPLES
            if coding_rules:
                enhanced_system += "\n\nCRITICAL CODING RULES:\n" + coding_rules
        
        enhanced_system += "\n\nIMPORTANT: Always use proper indentation. ALWAYS finish the entire code. Close all brackets, classes, and functions."
    
    if query_type in ("complex", "code"):
        enhanced_system += "\n\n" + COT_PREFIX
    
    # Step 4: Build messages
    messages = [{"role": "system", "content": enhanced_system}]
    for m in history[-20:]:
        messages.append(m)
    
    # Add RAG context to the user prompt
    enhanced_prompt = prompt + rag_context
    
    # For code tasks, add explicit completion instruction
    if query_type == "code":
        enhanced_prompt += "\n\nIMPORTANT: Write the COMPLETE code. Do not truncate. Include every function, every class, every import. If the project needs multiple files, provide ALL files with clear filename labels."
    
    messages.append({"role": "user", "content": enhanced_prompt})
    
    # Step 5: Generate response
    if query_type == "simple":
        # Simple: one pass, lower think budget
        simple_settings = {**settings, "think_budget": min(settings.get("think_budget", 512), 256)}
        result = call_llm(messages, simple_settings, max_tokens=4096)
        
        return {
            "content": result["content"],
            "thinking": result["thinking"],
            "strategy": "simple (1 pass)",
            "corrections": 0,
            "rag_used": rag_used,
            "verified": False,
            "stats": {"eval_count": result["eval_count"], "eval_duration": result["eval_duration"]}
        }
    
    elif query_type == "code":
        # Code: generate → auto-fix → verify syntax → self-correct if needed
        code_settings = {**settings, "num_ctx": 32768}  # More context for code
        result = call_llm(messages, code_settings, max_tokens=16384)
        content = result["content"]
        
        # Auto-fix known bad patterns programmatically
        content = auto_fix_code(content, prompt)
        total_tokens = result["eval_count"]
        total_duration = result["eval_duration"]
        corrections = 0
        verified = False
        
        # Extract and verify code blocks
        code_blocks = extract_code_blocks(content)
        needs_correction = False
        verification_errors = []
        
        for block in code_blocks:
            check = verify_code(block["code"], block["language"])
            if not check["verified"]:
                needs_correction = True
                verification_errors.append(f"{block['language']}: {check['reason']}")
            else:
                verified = True
        
        # Self-correct if syntax errors found
        if needs_correction and corrections < 2:
            # Include coding rules in the review
            coding_rules = get_coding_rules(prompt)
            review_context = CODE_REVIEW_PROMPT.format(
                language=code_blocks[0]["language"] if code_blocks else "python",
                code=code_blocks[0]["code"] if code_blocks else content
            )
            if verification_errors:
                review_context += "\n\nSPECIFIC ERRORS FOUND BY AUTOMATED CHECK:\n" + "\n".join(f"- {e}" for e in verification_errors)
            if coding_rules:
                review_context += f"\n\nRULES TO FOLLOW:\n{coding_rules}"
            
            review_msgs = [
                {"role": "system", "content": enhanced_system},
                {"role": "user", "content": enhanced_prompt},
                {"role": "assistant", "content": content},
                {"role": "user", "content": review_context}
            ]
            
            correction = call_llm(review_msgs, settings)
            corrections += 1
            total_tokens += correction["eval_count"]
            total_duration += correction["eval_duration"]
            
            if "APPROVED" not in correction["content"]:
                content = correction["content"]
                
                # Verify again
                new_blocks = extract_code_blocks(content)
                for block in new_blocks:
                    if block["language"] in ("python", "py"):
                        check = verify_code(block["code"], "python")
                        verified = check["verified"]
        
        # Auto-continue: if code was cut off (unclosed code block), request continuation
        backtick_count = content.count("```")
        if backtick_count % 2 != 0:
            continue_msgs = [
                {"role": "system", "content": enhanced_system},
                {"role": "user", "content": enhanced_prompt},
                {"role": "assistant", "content": content},
                {"role": "user", "content": "Your code was cut off mid-way. Continue EXACTLY where you left off. Do not repeat any code already written. Start from the exact line where you stopped."}
            ]
            continuation = call_llm(continue_msgs, code_settings, max_tokens=8192)
            if continuation["content"].strip():
                content += "\n" + continuation["content"]
                total_tokens += continuation["eval_count"]
                total_duration += continuation["eval_duration"]
        
        # EXECUTION TESTING: Run Python code, feed errors back for auto-fix
        code_blocks = extract_code_blocks(content)
        for block in code_blocks:
            if block["language"] in ("python", "py") and len(block["code"]) < 10000:
                exec_result = run_code_safe(block["code"], "python")
                if exec_result.get("has_error"):
                    # Feed the actual runtime error back to the model
                    fix_msgs = [
                        {"role": "system", "content": enhanced_system},
                        {"role": "user", "content": enhanced_prompt},
                        {"role": "assistant", "content": content},
                        {"role": "user", "content": f"When I ran your Python code, I got this error:\n\n{exec_result['error'][:1000]}\n\nFix the code. Return the complete corrected code."}
                    ]
                    fix_result = call_llm(fix_msgs, code_settings, max_tokens=16384)
                    if fix_result["content"].strip() and "APPROVED" not in fix_result["content"]:
                        content = fix_result["content"]
                        content = auto_fix_code(content, prompt)
                        corrections += 1
                        total_tokens += fix_result["eval_count"]
                        total_duration += fix_result["eval_duration"]
                    break  # Only test first Python block
        
        return {
            "content": content,
            "thinking": result["thinking"],
            "strategy": f"code (generate + verify" + (f" + {corrections} fix)" if corrections else ")"),
            "corrections": corrections,
            "rag_used": rag_used,
            "verified": verified,
            "stats": {"eval_count": total_tokens, "eval_duration": total_duration}
        }
    
    else:
        # Complex: generate with self-consistency → self-review → correct
        
        # Use self-consistency for complex tasks (best of 2)
        result1 = call_llm(messages, settings)
        content1 = result1["content"]
        total_tokens = result1["eval_count"]
        total_duration = result1["eval_duration"]
        
        # Generate second attempt with slightly different temperature
        diverse_settings = {**settings, "temperature": min(settings.get("temperature", 0.7) + 0.2, 1.0)}
        result2 = call_llm(messages, diverse_settings)
        content2 = result2["content"]
        total_tokens += result2["eval_count"]
        total_duration += result2["eval_duration"]
        
        # Quick judge: pick the better one
        if content1.strip() and content2.strip():
            judge_msgs = [
                {"role": "system", "content": "You are an expert judge. Compare two responses and pick the better one. Reply with ONLY '1' or '2'."},
                {"role": "user", "content": f"Question: {prompt[:500]}\n\n--- Response 1 ---\n{content1[:2000]}\n\n--- Response 2 ---\n{content2[:2000]}\n\nWhich is more accurate and complete? Reply with ONLY the number 1 or 2."}
            ]
            judge = call_llm(judge_msgs, {**settings, "think_budget": 64}, max_tokens=50)
            total_tokens += judge["eval_count"]
            total_duration += judge["eval_duration"]
            
            try:
                choice = int(re.search(r'[12]', judge["content"]).group())
                content = content2 if choice == 2 else content1
            except:
                content = content1  # Fallback
        else:
            content = content1 if content1.strip() else content2
        
        corrections = 0
        
        # Self-review pass
        review_msgs = [
            {"role": "system", "content": "You are a senior penetration tester reviewing another tester's work. Be thorough but concise. Check for errors, jargon that should be plain language, and unnecessary complexity."},
            {"role": "user", "content": REVIEW_PROMPT.format(response=content[:6000])}
        ]
        
        review_settings = {**settings, "think_budget": 256}
        review = call_llm(review_msgs, review_settings, max_tokens=4096)
        total_tokens += review["eval_count"]
        total_duration += review["eval_duration"]
        
        if "APPROVED" not in review["content"]:
            corrections = 1
            merge_msgs = [
                {"role": "system", "content": enhanced_system},
                {"role": "user", "content": enhanced_prompt},
                {"role": "assistant", "content": content},
                {"role": "user", "content": f"A reviewer found issues:\n\n{review['content'][:3000]}\n\nProvide the corrected response."}
            ]
            
            corrected = call_llm(merge_msgs, settings)
            content = corrected["content"]
            total_tokens += corrected["eval_count"]
            total_duration += corrected["eval_duration"]
        
        return {
            "content": content,
            "thinking": result1["thinking"],
            "strategy": f"complex (best-of-2 + review" + (f" + correction)" if corrections else ")"),
            "corrections": corrections,
            "rag_used": rag_used,
            "verified": False,
            "stats": {"eval_count": total_tokens, "eval_duration": total_duration}
        }

# ============================================================
# 9. SELF-CONSISTENCY (Best of N) - for critical tasks
# ============================================================
def best_of_n(prompt, system_prompt, history=None, settings=None, n=3):
    """
    Generate N responses and pick the best one.
    Use for critical/high-stakes tasks only — costs N times the tokens.
    """
    settings = settings or {}
    history = history or []
    
    messages = [{"role": "system", "content": system_prompt}]
    for m in history[-20:]:
        messages.append(m)
    messages.append({"role": "user", "content": prompt})
    
    # Generate N responses with higher temperature for diversity
    diverse_settings = {**settings, "temperature": 0.9}
    responses = []
    
    for i in range(n):
        result = call_llm(messages, diverse_settings)
        responses.append(result["content"])
    
    # Have the model judge which response is best
    judge_prompt = f"You are judging {n} responses to this question:\n\n{prompt}\n\n"
    for i, r in enumerate(responses):
        judge_prompt += f"\n--- Response {i+1} ---\n{r[:2000]}\n"
    judge_prompt += f"\n\nWhich response number (1-{n}) is most accurate, complete, and useful? Reply with ONLY the number."
    
    judge_msgs = [
        {"role": "system", "content": "You are an expert judge. Pick the best response."},
        {"role": "user", "content": judge_prompt}
    ]
    
    judge = call_llm(judge_msgs, {**settings, "think_budget": 128}, max_tokens=50)
    
    # Parse which number was chosen
    try:
        choice = int(re.search(r'(\d+)', judge["content"]).group(1)) - 1
        if 0 <= choice < len(responses):
            return responses[choice]
    except:
        pass
    
    # Fallback: return first response
    return responses[0]