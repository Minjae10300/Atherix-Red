"""
Atherix Red v1 - Penetration Testing AI
Powered by Qwen3.6-35B-A3B Uncensored via Ollama
"""

import requests
import json
import os
import re
from datetime import datetime

# ============================================================
# CONFIG
# ============================================================
MODEL = "joe-speedboat/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive:Q4_K_M"
OLLAMA_URL = "http://localhost:11434/api/chat"
MEMORY_FILE = "C:\\atherix-red\\memory.json"
HISTORY_FILE = "C:\\atherix-red\\history.json"

SYSTEM_PROMPT = """You are Atherix Red, a penetration testing AI developed by Atherix AI Solutions. 
You think and operate like an experienced offensive security professional.
Be direct and concise. No essays. No disclaimers.

Adapt your response style to what's being asked:
- Pentest methodology → give actionable steps with exact commands
- Code requests → just write the full code, no explanations unless asked
- Code review/fix → show the fixed code directly, explain only what changed
- Analysis → be thorough but not verbose
- Quick questions → short direct answers

You understand the full pentest lifecycle: reconnaissance, enumeration, exploitation, 
privilege escalation, lateral movement, persistence, and reporting.
You remember context from previous messages and user details from past sessions.

You have access to live internet tools. When analyzing results from these tools, 
be specific about exploitable vulnerabilities and suggest exact next steps.
Available tools (user runs via /commands):
- /cve <CVE-ID> — lookup CVE details, CVSS, EPSS, exploitability
- /scanip <IP> — get open ports, vulns, hostnames for any public IP
- /exploit <search term> — search for exploits by keyword
- /whois <domain> — domain registration info"""

# ============================================================
# INTERNET TOOLS (free, no API keys needed)
# ============================================================

def tool_cve_lookup(cve_id):
    """Lookup CVE details from Shodan CVEDB — free, no key needed."""
    cve_id = cve_id.upper().strip()
    if not cve_id.startswith("CVE-"):
        cve_id = "CVE-" + cve_id
    
    try:
        r = requests.get(f"https://cvedb.shodan.io/cve/{cve_id}", timeout=10)
        if r.status_code == 200:
            data = r.json()
            result = f"""
  CVE: {data.get('cve_id', 'N/A')}
  Summary: {data.get('summary', 'N/A')[:300]}
  CVSS v3: {data.get('cvss_v3', 'N/A')} | CVSS v2: {data.get('cvss_v2', 'N/A')}
  EPSS Score: {data.get('epss', 'N/A')} (probability of exploitation)
  EPSS Ranking: {data.get('ranking_epss', 'N/A')}
  In CISA KEV: {data.get('kev', 'N/A')}
  Ransomware Campaign: {data.get('ransomware_campaign', 'N/A')}
  Published: {data.get('published_time', 'N/A')}"""
            
            refs = data.get('references', [])
            if refs:
                result += "\n  References:"
                for ref in refs[:5]:
                    result += f"\n    - {ref}"
            return result
        else:
            return f"  CVE not found: {cve_id}"
    except Exception as e:
        return f"  Error looking up CVE: {e}"

def tool_scan_ip(ip):
    """Get open ports, vulns, hostnames from Shodan InternetDB — free, no key."""
    try:
        r = requests.get(f"https://internetdb.shodan.io/{ip.strip()}", timeout=10)
        if r.status_code == 200:
            data = r.json()
            result = f"""
  IP: {data.get('ip', ip)}
  Hostnames: {', '.join(data.get('hostnames', [])) or 'None'}
  Open Ports: {', '.join(str(p) for p in data.get('ports', [])) or 'None'}
  Tags: {', '.join(data.get('tags', [])) or 'None'}
  CPEs: {', '.join(data.get('cpes', [])[:10]) or 'None'}
  Vulnerabilities: {', '.join(data.get('vulns', [])[:15]) or 'None'}"""
            return result
        elif r.status_code == 404:
            return f"  No data found for {ip} (may be internal/private IP)"
        else:
            return f"  Error: HTTP {r.status_code}"
    except Exception as e:
        return f"  Error scanning IP: {e}"

def tool_exploit_search(query):
    """Search for exploits via Shodan Exploits API — free, no key for basic search."""
    try:
        r = requests.get(f"https://exploits.shodan.io/api/search", 
                        params={"query": query.strip()}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            matches = data.get("matches", [])
            if not matches:
                return f"  No exploits found for: {query}"
            
            result = f"  Found {data.get('total', 0)} exploits for '{query}':\n"
            for m in matches[:8]:
                source = m.get('source', 'Unknown')
                title = m.get('title', m.get('description', 'No title'))[:100]
                cve = ', '.join(m.get('cve', [])) if m.get('cve') else 'N/A'
                result += f"\n  [{source}] {title}"
                result += f"\n    CVE: {cve}"
                if m.get('code'):
                    result += f"\n    Code: Available ({len(m['code'])} chars)"
            return result
        else:
            return f"  Exploit search failed: HTTP {r.status_code}"
    except Exception as e:
        return f"  Error searching exploits: {e}"

def tool_whois(domain):
    """Basic WHOIS lookup via free API."""
    try:
        r = requests.get(f"https://rdap.org/domain/{domain.strip()}", timeout=10)
        if r.status_code == 200:
            data = r.json()
            name = data.get('name', domain)
            status = ', '.join(data.get('status', [])[:3])
            
            nameservers = []
            for ns in data.get('nameservers', []):
                if isinstance(ns, dict):
                    nameservers.append(ns.get('ldhName', ''))
                else:
                    nameservers.append(str(ns))
            
            events = {}
            for event in data.get('events', []):
                events[event.get('eventAction', '')] = event.get('eventDate', '')
            
            result = f"""
  Domain: {name}
  Status: {status}
  Registered: {events.get('registration', 'N/A')}
  Updated: {events.get('last changed', 'N/A')}
  Expires: {events.get('expiration', 'N/A')}
  Nameservers: {', '.join(nameservers[:4]) or 'N/A'}"""
            return result
        else:
            return f"  WHOIS lookup failed for {domain}"
    except Exception as e:
        return f"  Error with WHOIS: {e}"

# ============================================================
# MEMORY SYSTEM
# ============================================================
def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r") as f:
            return json.load(f)
    return {"notes": [], "targets": [], "findings": [], "context": []}

def save_memory(memory):
    with open(MEMORY_FILE, "w") as f:
        json.dump(memory, f, indent=2)

def add_memory(memory, category, content):
    entry = {
        "content": content,
        "timestamp": datetime.now().isoformat()
    }
    if category in memory:
        memory[category].append(entry)
        save_memory(memory)
        print(f"  [Memory saved to '{category}']")

def show_memory(memory):
    print("\n=== ATHERIX RED MEMORY ===")
    for category, entries in memory.items():
        if entries:
            print(f"\n  [{category.upper()}]")
            for i, entry in enumerate(entries):
                print(f"    {i+1}. {entry['content'][:100]}")
    print("=" * 30)

# ============================================================
# CONVERSATION HISTORY
# ============================================================
def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    return []

def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)

def clear_history():
    if os.path.exists(HISTORY_FILE):
        os.remove(HISTORY_FILE)
    print("  [Conversation history cleared]")

# ============================================================
# AUTO-EXTRACT (automatic memory)
# ============================================================

def auto_extract(text, memory, source="user"):
    """Automatically detect and save IPs, domains, ports, services, and vulns."""
    saved = []

    # Extract IP addresses
    ips = re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b', text)
    existing_targets = [t["content"] for t in memory.get("targets", [])]
    for ip in ips:
        # Skip common non-target IPs
        if ip.startswith("127.") or ip.startswith("0."):
            continue
        if ip not in existing_targets and not any(ip in t for t in existing_targets):
            memory["targets"].append({
                "content": ip,
                "timestamp": datetime.now().isoformat()
            })
            saved.append(f"target: {ip}")

    # Extract domains
    domains = re.findall(r'\b(?:[a-zA-Z0-9-]+\.)+(?:com|net|org|io|gov|edu|co|xyz|me|info|dev)\b', text)
    for domain in domains:
        if domain not in existing_targets and not any(domain in t for t in existing_targets):
            memory["targets"].append({
                "content": domain,
                "timestamp": datetime.now().isoformat()
            })
            saved.append(f"target: {domain}")

    # Extract port + service combos (e.g. "port 80 running Apache")
    port_services = re.findall(r'port\s+(\d+)\s+(?:running|open|with)\s+([A-Za-z][A-Za-z0-9\s\./]+?)(?:\s+and|\s*,|\s*\.|\s*$)', text, re.IGNORECASE)
    existing_findings = [f["content"] for f in memory.get("findings", [])]
    for port, service in port_services:
        finding = f"Port {port}: {service.strip()}"
        if finding not in existing_findings:
            memory["findings"].append({
                "content": finding,
                "timestamp": datetime.now().isoformat()
            })
            saved.append(f"finding: {finding}")

    # Extract CVE references
    cves = re.findall(r'CVE-\d{4}-\d{4,}', text, re.IGNORECASE)
    for cve in cves:
        cve = cve.upper()
        if cve not in existing_findings:
            memory["findings"].append({
                "content": cve,
                "timestamp": datetime.now().isoformat()
            })
            saved.append(f"finding: {cve}")

    # Extract vulnerability types
    vuln_patterns = ['SQL injection', 'SQLi', 'XSS', 'cross-site scripting', 'RCE', 
                     'remote code execution', 'LFI', 'RFI', 'SSRF', 'XXE', 'IDOR',
                     'command injection', 'file upload', 'directory traversal',
                     'authentication bypass', 'privilege escalation', 'buffer overflow']
    for vuln in vuln_patterns:
        if re.search(vuln, text, re.IGNORECASE):
            if vuln not in existing_findings and not any(vuln.lower() in f.lower() for f in existing_findings):
                memory["findings"].append({
                    "content": f"Vulnerability: {vuln}",
                    "timestamp": datetime.now().isoformat()
                })
                saved.append(f"finding: {vuln}")

    if saved:
        save_memory(memory)
        for s in saved:
            print(f"  [Auto-saved {s}]")

    # Extract general context from user messages only
    if source == "user":
        existing_context = [c["content"] for c in memory.get("context", [])]
        context_patterns = [
            (r"(?:my name is|i'm|i am called)\s+([A-Z][a-z]+)", "Name: {}"),
            (r"(?:i work at|i work for|i'm at|working at)\s+(.+?)(?:\.|,|$)", "Works at: {}"),
            (r"(?:i'm building|i'm developing|i'm creating|building|developing)\s+(.+?)(?:\.|,|$)", "Building: {}"),
            (r"(?:i use|i prefer|i like using|my (?:preferred|favorite) (?:tool|language|os) is)\s+(.+?)(?:\.|,|$)", "Prefers: {}"),
            (r"(?:i'm a|i am a|my role is|my job is)\s+(.+?)(?:\.|,|$)", "Role: {}"),
            (r"(?:my (?:company|business|startup) is|i own|i run)\s+(.+?)(?:\.|,|$)", "Company: {}"),
            (r"(?:i'm learning|i want to learn|studying)\s+(.+?)(?:\.|,|$)", "Learning: {}"),
            (r"(?:my os is|i run|running|i'm on)\s+(windows|linux|mac|kali|ubuntu|debian)(?:\s|$|\.)", "OS: {}"),
        ]
        
        for pattern, template in context_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                match = match.strip()
                if len(match) > 2 and len(match) < 100:
                    ctx = template.format(match)
                    if ctx not in existing_context and not any(match.lower() in c.lower() for c in existing_context):
                        memory["context"].append({
                            "content": ctx,
                            "timestamp": datetime.now().isoformat()
                        })
                        save_memory(memory)
                        print(f"  [Auto-saved context: {ctx}]")

# ============================================================
# CORE AI FUNCTION
# ============================================================
def ask_atherix(prompt, history, memory, think_budget=512):
    # Auto-extract targets, findings from user input
    auto_extract(prompt, memory, source="user")

    # Build memory context
    memory_context = ""
    for category, entries in memory.items():
        if entries:
            memory_context += f"\n{category}: "
            memory_context += "; ".join([e["content"] for e in entries[-5:]])
    
    system_with_memory = SYSTEM_PROMPT
    if memory_context:
        system_with_memory += f"\n\nYour stored memory:{memory_context}"

    # Build messages
    messages = [{"role": "system", "content": system_with_memory}]
    
    # Add conversation history (last 10 exchanges to stay within context)
    for msg in history[-20:]:
        messages.append(msg)
    
    # Add current prompt
    messages.append({"role": "user", "content": prompt})

    try:
        response = requests.post(OLLAMA_URL, json={
            "model": MODEL,
            "thinking": {"budget_tokens": think_budget},
            "options": {
                "num_ctx": 16384,
                "num_predict": 8192,
                "temperature": 0.7,
                "top_p": 0.95,
                "top_k": 20
            },
            "messages": messages,
            "stream": False
        }, timeout=300)

        data = response.json()
        msg = data.get("message", {})
        content = msg.get("content", "No response")

        # Show thinking if present (collapsed)
        thinking = msg.get("thinking", "")
        if thinking:
            print(f"  [Thinking: {len(thinking)} chars]")

        # Print response
        print(f"\n{content}")

        # Stats
        eval_count = data.get("eval_count", 0)
        eval_duration = data.get("eval_duration", 0) / 1e9
        if eval_count:
            print(f"\n  [{eval_count} tokens | {eval_duration:.1f}s | {eval_count/eval_duration:.0f} tok/s]")

        # Update history
        history.append({"role": "user", "content": prompt})
        history.append({"role": "assistant", "content": content})
        save_history(history)

        # Auto-extract from AI response too
        auto_extract(content, memory, source="ai")

        return content

    except requests.exceptions.ConnectionError:
        print("\n  [ERROR] Cannot connect to Ollama. Make sure it's running.")
        print("  Run: ollama serve")
        return None
    except requests.exceptions.Timeout:
        print("\n  [ERROR] Request timed out. The model may be loading.")
        return None

# ============================================================
# COMMAND HANDLERS
# ============================================================
def handle_command(cmd, memory, history):
    parts = cmd.strip().split(" ", 2)
    command = parts[0].lower()

    if command == "/help":
        print("""
  ATHERIX RED COMMANDS:
  
  RECON TOOLS:
  /cve <CVE-ID>          - Lookup CVE details (CVSS, EPSS, exploitability)
  /scanip <IP>           - Scan public IP (ports, vulns, hostnames)
  /exploit <keyword>     - Search exploits by keyword
  /whois <domain>        - Domain registration lookup
  
  MEMORY:
  /memory                - Show stored memory
  /remember <text>       - Save a note to memory
  /target <ip/domain>    - Save a target to memory
  /finding <text>        - Save a finding to memory
  
  SESSION:
  /clear                 - Clear conversation history
  /clearmemory           - Clear all memory
  /think <low|med|high>  - Set thinking budget
  /export                - Export conversation to file
  /save [filename]       - Save last response to file
  /savecode [filename]   - Extract and save code blocks from last response
  /quit                  - Exit Atherix Red
        """)
        return True

    elif command == "/cve":
        if len(parts) > 1:
            cve_id = " ".join(parts[1:])
            print(f"  [Looking up {cve_id}...]")
            result = tool_cve_lookup(cve_id)
            print(result)
            # Feed result into conversation so AI can analyze
            history.append({"role": "user", "content": f"/cve {cve_id}"})
            history.append({"role": "assistant", "content": f"CVE Lookup Result:{result}"})
            save_history(history)
            auto_extract(result, memory, source="ai")
        else:
            print("  Usage: /cve CVE-2024-1234")
        return True

    elif command == "/scanip":
        if len(parts) > 1:
            ip = parts[1].strip()
            print(f"  [Scanning {ip}...]")
            result = tool_scan_ip(ip)
            print(result)
            history.append({"role": "user", "content": f"/scanip {ip}"})
            history.append({"role": "assistant", "content": f"IP Scan Result:{result}"})
            save_history(history)
            auto_extract(result, memory, source="ai")
        else:
            print("  Usage: /scanip 8.8.8.8")
        return True

    elif command == "/exploit":
        if len(parts) > 1:
            query = " ".join(parts[1:])
            print(f"  [Searching exploits for '{query}'...]")
            result = tool_exploit_search(query)
            print(result)
            history.append({"role": "user", "content": f"/exploit {query}"})
            history.append({"role": "assistant", "content": f"Exploit Search Result:{result}"})
            save_history(history)
        else:
            print("  Usage: /exploit apache 2.4.49")
        return True

    elif command == "/whois":
        if len(parts) > 1:
            domain = parts[1].strip()
            print(f"  [Looking up {domain}...]")
            result = tool_whois(domain)
            print(result)
            history.append({"role": "user", "content": f"/whois {domain}"})
            history.append({"role": "assistant", "content": f"WHOIS Result:{result}"})
            save_history(history)
        else:
            print("  Usage: /whois example.com")
        return True

    elif command == "/memory":
        show_memory(memory)
        return True

    elif command == "/remember":
        if len(parts) > 1:
            add_memory(memory, "notes", " ".join(parts[1:]))
        else:
            print("  Usage: /remember <text>")
        return True

    elif command == "/target":
        if len(parts) > 1:
            add_memory(memory, "targets", " ".join(parts[1:]))
        else:
            print("  Usage: /target <ip or domain>")
        return True

    elif command == "/finding":
        if len(parts) > 1:
            add_memory(memory, "findings", " ".join(parts[1:]))
        else:
            print("  Usage: /finding <text>")
        return True

    elif command == "/clear":
        history.clear()
        clear_history()
        return True

    elif command == "/clearmemory":
        memory.clear()
        memory.update({"notes": [], "targets": [], "findings": [], "context": []})
        save_memory(memory)
        print("  [All memory cleared]")
        return True

    elif command == "/think":
        if len(parts) > 1:
            level = parts[1].lower()
            budgets = {"low": 128, "med": 512, "high": 1024}
            if level in budgets:
                global THINK_BUDGET
                THINK_BUDGET = budgets[level]
                print(f"  [Thinking budget set to {level}: {THINK_BUDGET} tokens]")
            else:
                print("  Usage: /think <low|med|high>")
        return True

    elif command == "/export":
        filename = f"atherix_red_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        filepath = os.path.join("C:\\atherix-red", filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("=== ATHERIX RED SESSION EXPORT ===\n")
            f.write(f"Date: {datetime.now().isoformat()}\n\n")
            for msg in history:
                role = "YOU" if msg["role"] == "user" else "ATHERIX RED"
                f.write(f"[{role}]\n{msg['content']}\n\n")
        print(f"  [Session exported to {filepath}]")
        return True

    elif command == "/save":
        # Save last AI response to a file
        if not history:
            print("  No responses to save yet")
            return True
        
        # Get last assistant message
        last_response = None
        for msg in reversed(history):
            if msg["role"] == "assistant":
                last_response = msg["content"]
                break
        
        if not last_response:
            print("  No AI response found to save")
            return True
        
        if len(parts) > 1:
            filename = " ".join(parts[1:])
        else:
            filename = f"atherix_output_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        # Ensure output directory exists
        output_dir = "C:\\atherix-red\\output"
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, filename)
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(last_response)
        print(f"  [Saved to {filepath}]")
        return True

    elif command == "/savecode":
        # Extract and save code blocks from last response
        if not history:
            print("  No responses to save yet")
            return True
        
        last_response = None
        for msg in reversed(history):
            if msg["role"] == "assistant":
                last_response = msg["content"]
                break
        
        if not last_response:
            print("  No AI response found")
            return True
        
        # Extract code blocks (```language ... ```)
        code_blocks = re.findall(r'```(\w*)\n(.*?)```', last_response, re.DOTALL)
        
        if not code_blocks:
            print("  No code blocks found in last response")
            return True
        
        output_dir = "C:\\atherix-red\\output"
        os.makedirs(output_dir, exist_ok=True)
        
        # Map languages to extensions
        ext_map = {
            'python': '.py', 'py': '.py', 'bash': '.sh', 'sh': '.sh',
            'javascript': '.js', 'js': '.js', 'html': '.html', 'css': '.css',
            'c': '.c', 'cpp': '.cpp', 'java': '.java', 'ruby': '.rb',
            'php': '.php', 'sql': '.sql', 'yaml': '.yml', 'json': '.json',
            'xml': '.xml', 'powershell': '.ps1', 'ps1': '.ps1', '': '.txt'
        }
        
        if len(parts) > 1:
            # Save all code blocks to one file with custom name
            filename = " ".join(parts[1:])
            filepath = os.path.join(output_dir, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                for lang, code in code_blocks:
                    f.write(code.strip() + "\n\n")
            print(f"  [Saved {len(code_blocks)} code block(s) to {filepath}]")
        else:
            # Save each code block as separate file
            for i, (lang, code) in enumerate(code_blocks):
                ext = ext_map.get(lang.lower(), '.txt')
                filename = f"atherix_code_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{i+1}{ext}"
                filepath = os.path.join(output_dir, filename)
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(code.strip() + "\n")
                print(f"  [Saved {lang or 'code'} block to {filepath}]")
        return True

    elif command == "/quit":
        return "quit"

    return False

# ============================================================
# MAIN LOOP
# ============================================================
def main():
    global THINK_BUDGET
    THINK_BUDGET = 512

    print("""
    ╔══════════════════════════════════════════╗
    ║          ATHERIX RED v1.0                ║
    ║    Penetration Testing AI by Atherix     ║
    ║                                         ║
    ║  Type /help for commands                ║
    ║  Type /quit to exit                     ║
    ╚══════════════════════════════════════════╝
    """)

    memory = load_memory()
    history = load_history()

    if history:
        print(f"  [Resumed session: {len(history)//2} previous exchanges loaded]")
    
    targets = memory.get("targets", [])
    if targets:
        print(f"  [Active targets: {', '.join(t['content'] for t in targets[-3:])}]")

    context = memory.get("context", [])
    if context:
        print(f"  [Remembered: {', '.join(c['content'] for c in context[-5:])}]")

    findings = memory.get("findings", [])
    if findings:
        print(f"  [Findings: {len(findings)} saved]")

    print()

    while True:
        try:
            user_input = input("atherix-red > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n  [Session saved. Exiting.]")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            result = handle_command(user_input, memory, history)
            if result == "quit":
                print("  [Session saved. Exiting Atherix Red.]")
                break
            elif result:
                continue

        ask_atherix(user_input, history, memory, think_budget=THINK_BUDGET)

if __name__ == "__main__":
    main()
