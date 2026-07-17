"""
lab_manager.py — Docker CTF lab spin-up/teardown for Atherix Red.
Standalone: only subprocess and requests (no other Atherix imports).
All Docker commands run via WSL2 bridge.
"""

import os
import subprocess
import time
import re

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

LABS_DIR = os.path.join("C:\\atherix-red", "labs")

# ---------------------------------------------------------------------------
# Lab catalog
# ---------------------------------------------------------------------------

LAB_CATALOG: dict[str, dict] = {
    "dvwa": {
        "name": "DVWA - Damn Vulnerable Web App",
        "description": "Classic training ground for SQL injection, XSS, file inclusion, and more.",
        "docker_cmd": "docker run -d --name dvwa -p 8080:80 vulnerables/web-dvwa",
        "url": "http://localhost:8080",
        "default_creds": {"user": "admin", "pass": "password"},
        "challenges": [
            {"name": "SQL Injection", "difficulty": "easy", "xp": 100, "skill": "web_app"},
            {"name": "SQL Injection (Blind)", "difficulty": "medium", "xp": 200, "skill": "web_app"},
            {"name": "XSS (Reflected)", "difficulty": "easy", "xp": 100, "skill": "web_app"},
            {"name": "XSS (Stored)", "difficulty": "medium", "xp": 150, "skill": "web_app"},
            {"name": "CSRF", "difficulty": "medium", "xp": 150, "skill": "web_app"},
            {"name": "File Inclusion", "difficulty": "easy", "xp": 100, "skill": "web_app"},
            {"name": "File Upload", "difficulty": "medium", "xp": 200, "skill": "web_app"},
            {"name": "Command Injection", "difficulty": "easy", "xp": 100, "skill": "web_app"},
        ],
    },
    "juiceshop": {
        "name": "OWASP Juice Shop",
        "description": "Modern vulnerable web app covering all OWASP Top 10 in a realistic NodeJS/Angular app.",
        "docker_cmd": "docker run -d --name juiceshop -p 3000:3000 bkimminich/juice-shop",
        "url": "http://localhost:3000",
        "default_creds": {"user": "admin@juice-sh.op", "pass": "admin123"},
        "challenges": [
            {"name": "DOM XSS", "difficulty": "easy", "xp": 100, "skill": "web_app"},
            {"name": "Admin Section", "difficulty": "easy", "xp": 100, "skill": "web_app"},
            {"name": "Login Admin", "difficulty": "easy", "xp": 100, "skill": "web_app"},
            {"name": "SQL Injection Login", "difficulty": "easy", "xp": 100, "skill": "web_app"},
            {"name": "Sensitive Data Exposure", "difficulty": "medium", "xp": 200, "skill": "web_app"},
            {"name": "JWT Forgery", "difficulty": "hard", "xp": 400, "skill": "crypto_passwords"},
            {"name": "SSRF", "difficulty": "hard", "xp": 400, "skill": "web_app"},
            {"name": "XXE", "difficulty": "medium", "xp": 250, "skill": "web_app"},
        ],
    },
    "webgoat": {
        "name": "WebGoat",
        "description": "OWASP WebGoat — Java-based teaching tool with guided lessons on web vulnerabilities.",
        "docker_cmd": "docker run -d --name webgoat -p 8888:8080 -p 9090:9090 webgoat/webgoat",
        "url": "http://localhost:8888/WebGoat",
        "default_creds": {"user": "guest", "pass": "guest"},
        "challenges": [
            {"name": "SQL Injection Basics", "difficulty": "easy", "xp": 100, "skill": "web_app"},
            {"name": "SQL Injection Advanced", "difficulty": "medium", "xp": 200, "skill": "web_app"},
            {"name": "Path Traversal", "difficulty": "easy", "xp": 100, "skill": "web_app"},
            {"name": "XXE Injection", "difficulty": "medium", "xp": 200, "skill": "web_app"},
            {"name": "Insecure Deserialization", "difficulty": "hard", "xp": 400, "skill": "web_app"},
            {"name": "Missing Function Access Control", "difficulty": "medium", "xp": 150, "skill": "web_app"},
        ],
    },
    "metasploitable2": {
        "name": "Metasploitable2",
        "description": "Intentionally vulnerable Linux VM image — covers network, web, and service exploitation.",
        "docker_cmd": (
            "docker run -d --name metasploitable2 "
            "-p 2121:21 -p 2222:22 -p 8180:80 -p 3632:3632 "
            "tleemcjr/metasploitable2"
        ),
        "url": "http://localhost:8180",
        "default_creds": {"user": "msfadmin", "pass": "msfadmin"},
        "challenges": [
            {"name": "FTP Anonymous Login", "difficulty": "easy", "xp": 100, "skill": "network"},
            {"name": "SSH Brute Force", "difficulty": "easy", "xp": 100, "skill": "crypto_passwords"},
            {"name": "vsftpd Backdoor (CVE-2011-2523)", "difficulty": "medium", "xp": 250, "skill": "network"},
            {"name": "UnrealIRCd Backdoor", "difficulty": "medium", "xp": 250, "skill": "network"},
            {"name": "Distcc Command Execution", "difficulty": "medium", "xp": 200, "skill": "network"},
            {"name": "Samba MS-RPC Shell", "difficulty": "medium", "xp": 200, "skill": "network"},
            {"name": "DVWA SQLi", "difficulty": "easy", "xp": 100, "skill": "web_app"},
            {"name": "PHP CGI Remote Code Execution", "difficulty": "hard", "xp": 400, "skill": "web_app"},
        ],
    },
    "vulnado": {
        "name": "Vulnado",
        "description": "Vulnerable Spring Boot app for SAST/DAST training — SQLi, SSRF, XXE, command injection.",
        "docker_cmd": "docker run -d --name vulnado -p 8090:8080 satoshitest/vulnado",
        "url": "http://localhost:8090",
        "default_creds": {"user": "admin", "pass": "password"},
        "challenges": [
            {"name": "SQL Injection", "difficulty": "easy", "xp": 100, "skill": "web_app"},
            {"name": "SSRF", "difficulty": "medium", "xp": 200, "skill": "web_app"},
            {"name": "Command Injection", "difficulty": "easy", "xp": 150, "skill": "web_app"},
            {"name": "XXE", "difficulty": "medium", "xp": 200, "skill": "web_app"},
        ],
    },
    "nodegoat": {
        "name": "OWASP NodeGoat",
        "description": "Node.js/Express OWASP training app with tutorials for each vulnerability.",
        "docker_cmd": "docker run -d --name nodegoat -p 4000:4000 owasp/nodegoat",
        "url": "http://localhost:4000",
        "default_creds": {"user": "user1@example.com", "pass": "User1_123"},
        "challenges": [
            {"name": "Injection (NoSQL)", "difficulty": "medium", "xp": 200, "skill": "web_app"},
            {"name": "Broken Auth", "difficulty": "easy", "xp": 100, "skill": "web_app"},
            {"name": "XSS", "difficulty": "easy", "xp": 100, "skill": "web_app"},
            {"name": "IDOR", "difficulty": "medium", "xp": 150, "skill": "web_app"},
            {"name": "Security Misconfiguration", "difficulty": "easy", "xp": 100, "skill": "web_app"},
            {"name": "Regex DoS", "difficulty": "hard", "xp": 300, "skill": "web_app"},
        ],
    },
}


# ---------------------------------------------------------------------------
# WSL2 bridge helper
# ---------------------------------------------------------------------------

def _wsl(cmd: list, timeout: int = 60) -> dict:
    """Run a command via WSL2. Returns {"stdout", "stderr", "returncode"}."""
    try:
        result = subprocess.run(
            ["wsl"] + cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "Command timed out", "returncode": -1}
    except FileNotFoundError:
        return {"stdout": "", "stderr": "WSL not found — ensure WSL2 is installed", "returncode": -1}
    except Exception as exc:
        return {"stdout": "", "stderr": str(exc), "returncode": -1}


# ---------------------------------------------------------------------------
# Container status
# ---------------------------------------------------------------------------

def get_running_containers() -> list[str]:
    """Return list of running Docker container names."""
    r = _wsl(["docker", "ps", "--format", "{{.Names}}"])
    if r["returncode"] != 0:
        return []
    return [name for name in r["stdout"].splitlines() if name.strip()]


def get_all_containers() -> list[str]:
    """Return all container names (including stopped)."""
    r = _wsl(["docker", "ps", "-a", "--format", "{{.Names}}"])
    if r["returncode"] != 0:
        return []
    return [name for name in r["stdout"].splitlines() if name.strip()]


# ---------------------------------------------------------------------------
# Lab lifecycle
# ---------------------------------------------------------------------------

def list_labs() -> list[dict]:
    """Return all labs with running status."""
    running = set(get_running_containers())
    all_containers = set(get_all_containers())
    labs = []
    for key, lab in LAB_CATALOG.items():
        labs.append({
            "key": key,
            "name": lab["name"],
            "description": lab["description"],
            "url": lab["url"],
            "default_creds": lab["default_creds"],
            "challenges": lab["challenges"],
            "running": key in running,
            "exists": key in all_containers,
        })
    return labs


def spin_up_lab(lab_key: str) -> dict:
    """Start a lab container. Returns {"success", "url", "lab", "message"}."""
    if lab_key not in LAB_CATALOG:
        return {"success": False, "url": "", "lab": lab_key, "message": f"Unknown lab: {lab_key}"}

    lab = LAB_CATALOG[lab_key]
    running = get_running_containers()

    # Already running
    if lab_key in running:
        return {
            "success": True,
            "url": lab["url"],
            "lab": lab_key,
            "message": f"{lab['name']} is already running at {lab['url']}",
        }

    # Container exists but is stopped — restart it
    all_containers = get_all_containers()
    if lab_key in all_containers:
        r = _wsl(["docker", "start", lab_key], timeout=30)
        if r["returncode"] != 0:
            return {"success": False, "url": "", "lab": lab_key, "message": f"Failed to start container: {r['stderr']}"}
    else:
        # Fresh pull and run
        docker_cmd = lab["docker_cmd"].split()
        r = _wsl(docker_cmd, timeout=120)
        if r["returncode"] != 0:
            return {"success": False, "url": "", "lab": lab_key, "message": f"Failed to start lab: {r['stderr']}"}

    # Wait for lab to become reachable
    url = lab["url"]
    ready = wait_for_lab(url, timeout=60)
    if not ready:
        return {
            "success": True,  # Container started even if not yet HTTP-ready
            "url": url,
            "lab": lab_key,
            "message": f"{lab['name']} started but may still be initialising. Check {url} in a moment.",
        }

    return {
        "success": True,
        "url": url,
        "lab": lab_key,
        "message": f"{lab['name']} is running at {url}",
    }


def tear_down_lab(lab_key: str, remove: bool = False) -> dict:
    """Stop (and optionally remove) a lab container."""
    if lab_key not in LAB_CATALOG:
        return {"success": False, "message": f"Unknown lab: {lab_key}"}

    r = _wsl(["docker", "stop", lab_key], timeout=30)
    if r["returncode"] != 0:
        return {"success": False, "message": f"Failed to stop: {r['stderr']}"}

    if remove:
        _wsl(["docker", "rm", lab_key], timeout=15)

    return {"success": True, "message": f"{lab_key} stopped" + (" and removed" if remove else "")}


def wait_for_lab(url: str, timeout: int = 30) -> bool:
    """Poll URL every 2 seconds until it responds or timeout expires."""
    if not REQUESTS_AVAILABLE:
        time.sleep(3)
        return True  # Optimistic if requests not available

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(url, timeout=3)
            if resp.status_code < 500:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


# ---------------------------------------------------------------------------
# Lab command runner (security-gated)
# ---------------------------------------------------------------------------

_LOCALHOST_PATTERN = re.compile(
    r"(?:localhost|127\.0\.0\.1|::1)"
    r"(?::\d+)?(?:/[^\s]*)?"
)

_EXTERNAL_IP_PATTERN = re.compile(
    r"\b(?!127\.|10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.)"
    r"(?:\d{1,3}\.){3}\d{1,3}\b"
)


def _command_targets_only_localhost(command: str) -> bool:
    """Return True if the command does not appear to target external IPs/hosts."""
    # Strip localhost references to check what remains
    stripped = _LOCALHOST_PATTERN.sub("", command)
    if _EXTERNAL_IP_PATTERN.search(stripped):
        return False
    # Block obvious external hostname patterns (not localhost/127.x)
    suspicious = re.findall(r"(?:https?://|@|--host\s+)([a-zA-Z0-9._-]+)", stripped)
    for host in suspicious:
        if host and host not in ("localhost", "127.0.0.1", "::1"):
            return False
    return True


def run_command_in_lab(command: str, timeout: int = 30) -> dict:
    """
    Run a shell command via WSL2 against the lab environment.
    SECURITY: Rejects any command that appears to target external IPs/hosts.
    """
    if not _command_targets_only_localhost(command):
        return {
            "success": False,
            "stdout": "",
            "stderr": "BLOCKED: Lab commands may only target localhost/127.0.0.1.",
            "returncode": -1,
        }

    r = _wsl(["bash", "-c", command], timeout=timeout)
    return {
        "success": r["returncode"] == 0,
        "stdout": r["stdout"],
        "stderr": r["stderr"],
        "returncode": r["returncode"],
    }


# ---------------------------------------------------------------------------
# Lab discovery
# ---------------------------------------------------------------------------

def discover_new_labs(query: str = "vulnerable docker image CTF hacking training") -> list[dict]:
    """
    Search for additional CTF lab Docker images.
    Returns list of dicts with name/docker_cmd/description.
    """
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=8))
        return [
            {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
            for r in results
        ]
    except Exception:
        return []
