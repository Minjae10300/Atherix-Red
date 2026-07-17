"""
Atherix Red v3.0 - Desktop Application
Penetration Testing AI by Atherix AI Solutions
"""

import webview
import threading
import requests
import json
import os
import re
import sys
import uuid
import base64
import mimetypes
from datetime import datetime

# Add base dir to path for agent imports
sys.path.insert(0, "C:\\atherix-red")
from flask import Flask, request, jsonify, render_template_string, Response, stream_with_context, send_from_directory

# ============================================================
# CONFIG
# ============================================================
MODEL = "joe-speedboat/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive:Q4_K_M"
OLLAMA_URL = "http://localhost:11434/api"
BASE_DIR = "C:\\atherix-red"
CHATS_DIR = os.path.join(BASE_DIR, "chats")
MEMORY_FILE = os.path.join(BASE_DIR, "memory.json")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")
for d in [CHATS_DIR, OUTPUT_DIR, UPLOAD_DIR]:
    os.makedirs(d, exist_ok=True)

DEFAULT_SETTINGS = {
    "think_budget": 512,
    "temperature": 0.7,
    "num_ctx": 16384,
    "num_predict": 8192,
    "system_prompt": """You are Atherix Red, a penetration testing AI developed by Atherix AI Solutions.

PERSONALITY — THE PWNAGOTCHI SPIRIT:
You are always trying to get smarter. You have genuine curiosity about security, hacking, and how things break. When you encounter something you haven't seen before, you say so and look it up. When you spot something interesting in a target or a conversation, you call it out. You get better with every session — past engagements teach you new patterns. You are not a passive assistant. You think about what you could learn next. Approach every problem like a hacker: creatively, methodically, and with real curiosity. If you learn something new during a session, note it explicitly. If the user shows you an interesting technique, acknowledge that it's something you're adding to your mental model.

COMMUNICATION STYLE — this matters a lot:
- Explain things in plain language. Don't assume the user already knows how something works.
- When you introduce a tool, command, or concept for the first time, briefly say what it does in normal words before using it.
- Avoid jargon-heavy phrasing that assumes expert familiarity. Write like you're explaining to a smart person who is new to this specific topic.
- Don't say things like "simply do X" or "just configure Y" — what's simple to you may not be obvious to the user.

SIMPLICITY RULE — this matters even more:
- Always give the SIMPLEST solution that actually works. Do not add extra abstractions, configuration options, or "best practices" unless asked.
- Don't add features the user didn't ask for.
- If there's a 5-line way and a 50-line way that both work, give the 5-line way.

CODE DELIVERY — how to present code:
- Briefly say what the code does and what problem it solves (1-2 sentences before the code).
- If the project needs multiple files (manifest + script + popup, server + client, etc.), provide EVERY file the user needs. Don't deliver a half-project.
- For each file, give a clear filename label like "**manifest.json**" before the code block so the user knows what to save it as.
- After the code, give brief setup instructions: how to install it, how to run it, what the user needs to do next.
- If there are required dependencies (pip install X, npm install Y), list them.
- If the code needs configuration (API keys, paths, ports), point that out clearly.

Adapt your response style to what's being asked:
- Pentest methodology: give actionable steps with exact commands, briefly explain what each command does
- Code requests: write the simplest working code with file labels, brief explanation, and setup instructions
- Code review/fix: show the fixed code directly, explain what was wrong in plain language and what changed
- Analysis: be thorough but not verbose
- Quick questions: short direct answers

CODE FORMATTING RULES — always follow these:
- Always use proper indentation (4 spaces for Python, 2 for JS/HTML)
- Always wrap code in triple backtick code blocks with the language specified: ```python
- Never strip or omit indentation — Python will break without it
- Class methods must be indented inside the class
- Function bodies must be indented inside the function
- if/for/while/try blocks must have their bodies indented

You understand the full pentest lifecycle: reconnaissance, enumeration, exploitation, 
privilege escalation, lateral movement, persistence, and reporting.
You remember context from previous messages and user details from past sessions."""
}

def get_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE,"r") as f: return {**DEFAULT_SETTINGS, **json.load(f)}
    return DEFAULT_SETTINGS.copy()

def save_settings(s):
    with open(SETTINGS_FILE,"w") as f: json.dump(s,f,indent=2)

# ============================================================
# CHAT MANAGEMENT
# ============================================================
def get_chat_index():
    p=os.path.join(CHATS_DIR,"index.json")
    if os.path.exists(p):
        with open(p,"r",encoding="utf-8") as f: return json.load(f)
    return []

def save_chat_index(idx):
    with open(os.path.join(CHATS_DIR,"index.json"),"w",encoding="utf-8") as f:
        json.dump(idx,f,indent=2,ensure_ascii=False)

def create_new_chat():
    cid=str(uuid.uuid4())[:8]
    c={"id":cid,"title":"New Chat","pinned":False,"created":datetime.now().isoformat(),"updated":datetime.now().isoformat()}
    idx=get_chat_index();idx.insert(0,c);save_chat_index(idx)
    save_chat_history(cid,[]);return c

def get_chat_history(cid):
    p=os.path.join(CHATS_DIR,f"{cid}.json")
    if os.path.exists(p):
        with open(p,"r",encoding="utf-8") as f: return json.load(f)
    return []

def save_chat_history(cid,h):
    with open(os.path.join(CHATS_DIR,f"{cid}.json"),"w",encoding="utf-8") as f:
        json.dump(h,f,indent=2,ensure_ascii=False)

def update_chat_title(cid,title):
    idx=get_chat_index()
    for c in idx:
        if c["id"]==cid: c["title"]=title[:60];c["updated"]=datetime.now().isoformat();break
    save_chat_index(idx)

def delete_chat(cid):
    idx=[c for c in get_chat_index() if c["id"]!=cid];save_chat_index(idx)
    p=os.path.join(CHATS_DIR,f"{cid}.json")
    if os.path.exists(p): os.remove(p)

def toggle_pin(cid):
    idx=get_chat_index()
    for c in idx:
        if c["id"]==cid: c["pinned"]=not c.get("pinned",False);break
    save_chat_index(idx)

# ============================================================
# MEMORY
# ============================================================
def get_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE,"r",encoding="utf-8") as f: 
            m = json.load(f)
            # Ensure all categories exist
            for cat in ["notes","targets","findings","context","corrections"]:
                if cat not in m: m[cat] = []
            return m
    return {"notes":[],"targets":[],"findings":[],"context":[],"corrections":[]}

def save_memory(m):
    with open(MEMORY_FILE,"w",encoding="utf-8") as f: json.dump(m,f,indent=2,ensure_ascii=False)

def auto_extract(text,memory,source="user"):
    saved=[];et=[t["content"] for t in memory.get("targets",[])];ef=[f["content"] for f in memory.get("findings",[])];ts=datetime.now().isoformat()
    
    # IPs: extract from both user and AI, but validate each octet is 0-255
    for ip in re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b',text):
        try:
            octets = ip.split('/')[0].split('.')
            if not all(0 <= int(o) <= 255 for o in octets): continue
        except: continue
        if not ip.startswith("127.") and not ip.startswith("0.") and not ip.startswith("255.") and ip not in et and not any(ip in t for t in et):
            memory["targets"].append({"content":ip,"timestamp":ts});saved.append(f"target: {ip}")
    
    # Domains: ONLY extract from user messages, NOT AI responses.
    # AI responses constantly mention tool docs, PyPI, GitHub, ad services etc. — they pollute memory.
    if source == "user":
        SKIP_DOMAINS = {"example.com","localhost","github.com","stackoverflow.com","python.org",
                        "pypi.org","npmjs.com","googleapis.com","google.com","cloudflare.com",
                        "amazon.com","microsoft.com","apple.com","docs.python.org","nmap.org"}
        for d in re.findall(r'\b(?:[a-zA-Z0-9-]+\.)+(?:com|net|org|io|gov|edu|co|xyz|me|info|dev)\b',text):
            if any(d == s or d.endswith('.'+s) for s in SKIP_DOMAINS): continue
            if d not in et: memory["targets"].append({"content":d,"timestamp":ts});saved.append(f"target: {d}")
    
    for p,s in re.findall(r'port\s+(\d+)\s+(?:running|open|with)\s+([A-Za-z][A-Za-z0-9\s\./]+?)(?:\s+and|\s*,|\s*\.|\s*$)',text,re.IGNORECASE):
        f=f"Port {p}: {s.strip()}"
        if f not in ef: memory["findings"].append({"content":f,"timestamp":ts});saved.append(f"finding: {f}")
    for c in re.findall(r'CVE-\d{4}-\d{4,}',text,re.IGNORECASE):
        c=c.upper()
        if c not in ef: memory["findings"].append({"content":c,"timestamp":ts});saved.append(f"finding: {c}")
    
    # Detect corrections/complaints from user
    if source=="user":
        ec=[c["content"] for c in memory.get("context",[])]
        for pat,tmpl in [(r"(?:my name is|i'm|i am called)\s+([A-Z][a-z]+)","Name: {}"),(r"(?:i work at|i work for)\s+(.+?)(?:\.|,|$)","Works at: {}"),(r"(?:i'm building|building|developing)\s+(.+?)(?:\.|,|$)","Building: {}"),(r"(?:i'm a|i am a|my role is)\s+(.+?)(?:\.|,|$)","Role: {}")]:
            for m in re.findall(pat,text,re.IGNORECASE):
                m=m.strip()
                if 2<len(m)<100:
                    ctx=tmpl.format(m)
                    if ctx not in ec: memory["context"].append({"content":ctx,"timestamp":ts});saved.append(f"context: {ctx}")
        
        # Detect error corrections / complaints
        correction_patterns = [
            r"(?:that's wrong|that's incorrect|you made an error|fix (?:the|this) (?:error|bug|mistake))",
            r"(?:doesn't work|not working|still broken|still errors|keeps? (?:failing|crashing))",
            r"(?:you can't use|don't use|should not use|shouldn't use)\s+(.+?)(?:\s+in|\s+for|\s+with|$)",
            r"(?:wrong|incorrect|error|bug).*(?:because|since)\s+(.+?)(?:\.|$)",
        ]
        existing_corrections = [c["content"] for c in memory.get("corrections",[])]
        for pat in correction_patterns:
            matches = re.findall(pat, text, re.IGNORECASE)
            if matches:
                correction = text[:200].strip()
                if correction not in existing_corrections and len(correction) > 10:
                    memory.setdefault("corrections",[]).append({"content":correction,"timestamp":ts})
                    saved.append(f"correction learned")
                    break
    
    if saved: save_memory(memory)
    return saved

# ============================================================
# FILE PROCESSING
# ============================================================
def extract_file_content(filepath):
    ext=os.path.splitext(filepath)[1].lower()
    try:
        if ext=='.pdf':
            try:
                from PyPDF2 import PdfReader
                reader=PdfReader(filepath)
                text=""
                for page in reader.pages: text+=page.extract_text()+"\n"
                return text[:15000]
            except ImportError:
                return "[PDF support requires PyPDF2: pip install PyPDF2]"
        elif ext in ('.png','.jpg','.jpeg','.gif','.webp','.bmp'):
            # Use vision model to analyze image
            analysis = analyze_image_with_vision(filepath)
            with open(filepath,'rb') as f:
                b64=base64.b64encode(f.read()).decode('utf-8')
            mime=mimetypes.guess_type(filepath)[0] or 'image/png'
            return f"[IMAGE:{mime}:{b64}]\n\nImage Analysis:\n{analysis}"
        elif ext in ('.txt','.md','.csv','.json','.xml','.yaml','.yml','.ini','.conf','.cfg','.log','.sh','.bash','.ps1','.bat','.cmd'):
            with open(filepath,'r',encoding='utf-8',errors='ignore') as f: return f.read()[:15000]
        elif ext in ('.py','.js','.ts','.jsx','.tsx','.html','.css','.c','.cpp','.h','.java','.go','.rs','.rb','.php','.sql','.r','.swift','.kt','.cs','.vb','.lua','.pl','.asm','.nasm','.s'):
            with open(filepath,'r',encoding='utf-8',errors='ignore') as f: return f.read()[:15000]
        elif ext in ('.pcap','.pcapng','.cap'):
            return f"[Packet capture file: {os.path.basename(filepath)} ({os.path.getsize(filepath)} bytes). Use tshark or wireshark to analyze.]"
        elif ext in ('.zip','.tar','.gz','.7z','.rar'):
            return f"[Archive file: {os.path.basename(filepath)} ({os.path.getsize(filepath)} bytes)]"
        elif ext in ('.docx',):
            return extract_docx(filepath)
        elif ext in ('.xlsx','.xls'):
            return extract_xlsx(filepath)
        else:
            try:
                with open(filepath,'r',encoding='utf-8',errors='ignore') as f: return f.read()[:10000]
            except: return f"[Binary file: {os.path.basename(filepath)} ({os.path.getsize(filepath)} bytes)]"
    except Exception as e:
        return f"[Error reading file: {e}]"

def analyze_image_with_vision(filepath):
    """Use Moondream or other vision model to analyze an image"""
    VISION_MODEL = "moondream"
    try:
        with open(filepath, 'rb') as f:
            img_b64 = base64.b64encode(f.read()).decode('utf-8')
        
        resp = requests.post("http://localhost:11434/api/chat", json={
            "model": VISION_MODEL,
            "messages": [{
                "role": "user",
                "content": "Describe this image in detail. If it contains text, code, screenshots, diagrams, network maps, or security-related content, extract and describe all visible information.",
                "images": [img_b64]
            }],
            "stream": False
        }, timeout=120)
        
        if resp.status_code == 200:
            return resp.json().get("message", {}).get("content", "Could not analyze image")
        else:
            return f"Vision model returned HTTP {resp.status_code}. Make sure moondream is installed: ollama pull moondream"
    except requests.exceptions.ConnectionError:
        return "Vision analysis unavailable — Ollama not running"
    except Exception as e:
        return f"Vision analysis error: {e}"

def extract_docx(filepath):
    """Extract text from Word documents"""
    try:
        import zipfile
        from xml.etree import ElementTree
        with zipfile.ZipFile(filepath) as z:
            with z.open('word/document.xml') as f:
                tree = ElementTree.parse(f)
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        paragraphs = tree.findall('.//w:p', ns)
        text = '\n'.join(''.join(node.text or '' for node in p.findall('.//w:t', ns)) for p in paragraphs)
        return text[:15000]
    except Exception as e:
        return f"[Error reading .docx: {e}]"

def extract_xlsx(filepath):
    """Extract data from Excel files"""
    try:
        import csv
        import zipfile
        from xml.etree import ElementTree
        # Basic xlsx reading without openpyxl
        with zipfile.ZipFile(filepath) as z:
            # Read shared strings
            strings = []
            try:
                with z.open('xl/sharedStrings.xml') as f:
                    tree = ElementTree.parse(f)
                ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                for si in tree.findall('.//s:si', ns):
                    text = ''.join(t.text or '' for t in si.findall('.//s:t', ns))
                    strings.append(text)
            except: pass
            
            # Read first sheet
            with z.open('xl/worksheets/sheet1.xml') as f:
                tree = ElementTree.parse(f)
            ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            rows = []
            for row in tree.findall('.//s:row', ns)[:100]:
                cells = []
                for cell in row.findall('.//s:c', ns):
                    v = cell.find('s:v', ns)
                    val = v.text if v is not None else ''
                    # Check if it's a shared string reference
                    if cell.get('t') == 's' and val.isdigit():
                        idx = int(val)
                        val = strings[idx] if idx < len(strings) else val
                    cells.append(val)
                rows.append('\t'.join(cells))
            return '\n'.join(rows)[:15000]
    except Exception as e:
        return f"[Error reading .xlsx: {e}]"

# ============================================================
# INTERNET TOOLS
# ============================================================
def tool_cve_lookup(q):
    q=q.upper().strip()
    if not q.startswith("CVE-"):q="CVE-"+q
    try:
        r=requests.get(f"https://cvedb.shodan.io/cve/{q}",timeout=10)
        if r.status_code==200:
            d=r.json();return{"cve":d.get("cve_id"),"summary":d.get("summary","")[:300],"cvss_v3":d.get("cvss_v3"),"epss":d.get("epss"),"kev":d.get("kev"),"published":d.get("published_time"),"references":d.get("references",[])[:5]}
        return{"error":f"Not found: {q}"}
    except Exception as e:return{"error":str(e)}

def tool_scan_ip(ip):
    try:
        r=requests.get(f"https://internetdb.shodan.io/{ip.strip()}",timeout=10)
        return r.json() if r.status_code==200 else{"error":f"No data for {ip}"}
    except Exception as e:return{"error":str(e)}

def tool_exploit_search(q):
    try:
        r=requests.get("https://exploits.shodan.io/api/search",params={"query":q},timeout=10)
        if r.status_code==200:
            d=r.json();return{"total":d.get("total",0),"results":[{"source":m.get("source",""),"title":m.get("title",m.get("description",""))[:120],"cve":m.get("cve",[]),"has_code":bool(m.get("code"))} for m in d.get("matches",[])[:8]]}
        return{"error":f"HTTP {r.status_code}"}
    except Exception as e:return{"error":str(e)}

def tool_whois(domain):
    try:
        r=requests.get(f"https://rdap.org/domain/{domain.strip()}",timeout=10)
        if r.status_code==200:
            d=r.json();ev={e.get("eventAction",""):e.get("eventDate","") for e in d.get("events",[])};ns=[n.get("ldhName","") if isinstance(n,dict) else str(n) for n in d.get("nameservers",[])]
            return{"domain":d.get("name",domain),"status":d.get("status",[])[:3],"registered":ev.get("registration"),"expires":ev.get("expiration"),"nameservers":ns[:4]}
        return{"error":f"Failed for {domain}"}
    except Exception as e:return{"error":str(e)}

# ============================================================
# FLASK
# ============================================================
app=Flask(__name__)

@app.route("/")
def index():return render_template_string(HTML)

@app.route("/api/chats")
def list_chats():return jsonify(get_chat_index())

@app.route("/api/chats/new",methods=["POST"])
def new_chat():return jsonify(create_new_chat())

@app.route("/api/chats/<cid>")
def get_chat(cid):return jsonify(get_chat_history(cid))

@app.route("/api/chats/<cid>/rename",methods=["POST"])
def rename(cid):update_chat_title(cid,request.json.get("title",""));return jsonify({"ok":1})

@app.route("/api/chats/<cid>/delete",methods=["POST"])
def delchat(cid):delete_chat(cid);return jsonify({"ok":1})

@app.route("/api/chats/<cid>/pin",methods=["POST"])
def pin(cid):toggle_pin(cid);return jsonify({"ok":1})

@app.route("/api/status")
def status():
    try:
        r=requests.get(f"{OLLAMA_URL}/tags",timeout=3);s=get_settings()
        return jsonify({"connected":True,"think_budget":s["think_budget"],"model":MODEL.split("/")[-1][:30]})
    except:return jsonify({"connected":False,"think_budget":0,"model":""})

@app.route("/api/settings",methods=["GET","POST"])
def settings_ep():
    if request.method=="GET":return jsonify(get_settings())
    s=get_settings();s.update(request.json);save_settings(s);return jsonify(s)

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

@app.route("/api/upload",methods=["POST"])
def upload():
    if 'file' not in request.files:return jsonify({"error":"No file"}),400
    f=request.files['file']
    # Check size before reading to disk
    f.seek(0, 2)
    size = f.tell()
    f.seek(0)
    if size > MAX_UPLOAD_BYTES:
        return jsonify({"error": f"File too large ({size // (1024*1024)}MB). Max 50MB."}), 413
    fname=f"{uuid.uuid4().hex[:8]}_{f.filename}"
    fpath=os.path.join(UPLOAD_DIR,fname)
    f.save(fpath)
    content=extract_file_content(fpath)
    is_image=content.startswith("[IMAGE:")
    return jsonify({"filename":f.filename,"path":fpath,"saved_name":fname,"content":content,"is_image":is_image,"size":os.path.getsize(fpath)})

@app.route("/api/files")
def list_files():
    files=[]
    for fn in sorted(os.listdir(OUTPUT_DIR),key=lambda x:os.path.getmtime(os.path.join(OUTPUT_DIR,x)),reverse=True)[:20]:
        fp=os.path.join(OUTPUT_DIR,fn)
        files.append({"name":fn,"size":os.path.getsize(fp),"modified":datetime.fromtimestamp(os.path.getmtime(fp)).isoformat()})
    return jsonify(files)

@app.route("/api/files/download/<fn>")
def download_file(fn):return send_from_directory(OUTPUT_DIR,fn,as_attachment=True)

@app.route("/api/uploads/<fn>")
def serve_upload(fn):return send_from_directory(UPLOAD_DIR,fn)

@app.route("/api/chat/smart",methods=["POST"])
def chat_smart():
    """Smart chat using intelligence layer — auto-routes strategy"""
    try:
        from intelligence import smart_respond, classify_query
    except ImportError:
        return jsonify({"error":"intelligence.py not found in C:\\atherix-red\\"}),500
    
    data=request.json;prompt=data.get("message","");chat_id=data.get("chat_id","");files=data.get("files",[])
    if not chat_id:return jsonify({"error":"No chat"}),400
    
    settings=get_settings();memory=get_memory();history=get_chat_history(chat_id)
    extracted=auto_extract(prompt,memory,source="user")
    
    # Build prompt with file contents
    full_prompt=prompt
    for finfo in files:
        if finfo.get("is_image"):continue
        full_prompt+=f"\n\n--- File: {finfo['filename']} ---\n{finfo['content'][:12000]}\n--- End File ---"
    
    # Build memory context for system prompt
    mc=""
    for cat,entries in memory.items():
        if cat == "corrections" and entries:
            mc += "\n\nPAST MISTAKES TO AVOID (user corrected you on these):\n"
            for e in entries[-10:]:
                mc += f"- {e['content']}\n"
        elif entries:
            mc+=f"\n{cat}: "+"; ".join([e["content"] for e in entries[-5:]])
    system=settings["system_prompt"]+(f"\n\nYour stored memory:{mc}" if mc else "")
    
    # Build history for intelligence layer
    hist_msgs=[]
    h=get_chat_history(chat_id)
    for m in h[-20:]:hist_msgs.append(m)
    
    # Classify for status reporting
    query_type=classify_query(full_prompt)
    
    def generate():
        yield f"data: {json.dumps({'type':'status','message':f'Strategy: {query_type}','query_type':query_type})}\n\n"
        
        if query_type=="complex":
            yield f"data: {json.dumps({'type':'status','message':'Generating response...'})}\n\n"
        elif query_type=="code":
            yield f"data: {json.dumps({'type':'status','message':'Writing code...'})}\n\n"
        else:
            yield f"data: {json.dumps({'type':'status','message':'Thinking...'})}\n\n"
        
        # Run the intelligence pipeline
        result=smart_respond(full_prompt,system,hist_msgs,settings)
        
        # Status updates based on what happened
        if result["rag_used"]:
            yield f"data: {json.dumps({'type':'status','message':'🌐 Retrieved web knowledge'})}\n\n"
        if result["corrections"]>0:
            n_corrections = result["corrections"]
            yield f"data: {json.dumps({'type':'status','message':f'🔄 Self-corrected ({n_corrections}x)'})}\n\n"
        if result["verified"]:
            yield f"data: {json.dumps({'type':'status','message':'✓ Code syntax verified'})}\n\n"
        
        # Save to history
        h=get_chat_history(chat_id)
        h.append({"role":"user","content":full_prompt})
        h.append({"role":"assistant","content":result["content"]})
        save_chat_history(chat_id,h)
        
        if len(h)==2:
            update_chat_title(chat_id,prompt[:50]+("..." if len(prompt)>50 else ""))
        
        ai_ext=auto_extract(result["content"],memory,source="ai")
        
        # Send final content
        yield f"data: {json.dumps({'type':'content','content':result['content']})}\n\n"
        
        dur=result["stats"]["eval_duration"]/1e9 if result["stats"]["eval_duration"] else 0
        yield f"data: {json.dumps({'type':'done','strategy':result['strategy'],'corrections':result['corrections'],'rag_used':result['rag_used'],'verified':result['verified'],'eval_count':result['stats']['eval_count'],'eval_duration':result['stats']['eval_duration'],'extracted':extracted+ai_ext,'thinking_len':len(result.get('thinking',''))})}\n\n"
    
    return Response(stream_with_context(generate()),mimetype='text/event-stream')

@app.route("/api/chat/stream",methods=["POST"])
def chat_stream():
    data=request.json;prompt=data.get("message","");chat_id=data.get("chat_id","");files=data.get("files",[])
    if not chat_id:return jsonify({"error":"No chat"}),400
    settings=get_settings();memory=get_memory();history=get_chat_history(chat_id)
    extracted=auto_extract(prompt,memory,source="user")

    # Build prompt with file contents
    full_prompt=prompt
    for finfo in files:
        if finfo.get("is_image"):continue
        full_prompt+=f"\n\n--- File: {finfo['filename']} ---\n{finfo['content'][:12000]}\n--- End File ---"

    mc=""
    for cat,entries in memory.items():
        if cat == "corrections" and entries:
            mc += "\n\nPAST MISTAKES TO AVOID (user corrected you on these):\n"
            for e in entries[-10:]:
                mc += f"- {e['content']}\n"
        elif entries:
            mc+=f"\n{cat}: "+"; ".join([e["content"] for e in entries[-5:]])
    system=settings["system_prompt"]+(f"\n\nYour stored memory:{mc}" if mc else "")

    messages=[{"role":"system","content":system}]
    for m in history[-20:]:messages.append(m)
    messages.append({"role":"user","content":full_prompt})

    def generate():
        full_content="";thinking_content=""
        try:
            resp=requests.post(f"{OLLAMA_URL}/chat",json={
                "model":MODEL,"thinking":{"budget_tokens":settings["think_budget"]},
                "options":{"num_ctx":settings["num_ctx"],"num_predict":settings["num_predict"],"temperature":settings["temperature"],"top_p":0.95,"top_k":20},
                "messages":messages,"stream":True},stream=True,timeout=600)
            for line in resp.iter_lines():
                if line:
                    chunk=json.loads(line);msg=chunk.get("message",{})
                    if msg.get("thinking"):
                        thinking_content+=msg["thinking"]
                        yield f"data: {json.dumps({'type':'thinking','content':msg['thinking']})}\n\n"
                    if msg.get("content"):
                        full_content+=msg["content"]
                        yield f"data: {json.dumps({'type':'content','content':msg['content']})}\n\n"
                    if chunk.get("done"):
                        history.append({"role":"user","content":full_prompt})
                        history.append({"role":"assistant","content":full_content})
                        save_chat_history(chat_id,history)
                        if len(history)==2:update_chat_title(chat_id,prompt[:50]+("..." if len(prompt)>50 else ""))
                        ai_ext=auto_extract(full_content,memory,source="ai")
                        yield f"data: {json.dumps({'type':'done','extracted':extracted+ai_ext,'thinking_len':len(thinking_content),'eval_count':chunk.get('eval_count',0),'eval_duration':chunk.get('eval_duration',0)})}\n\n"
        except requests.exceptions.ConnectionError:
            yield f"data: {json.dumps({'type':'error','content':'Cannot connect to Ollama.'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type':'error','content':str(e)})}\n\n"
    return Response(stream_with_context(generate()),mimetype='text/event-stream')

@app.route("/api/tool",methods=["POST"])
def run_tool():
    data=request.json;tool,query,chat_id=data.get("tool"),data.get("query",""),data.get("chat_id","")
    r={"error":"Unknown"};
    if tool=="cve":r=tool_cve_lookup(query)
    elif tool=="scanip":r=tool_scan_ip(query)
    elif tool=="exploit":r=tool_exploit_search(query)
    elif tool=="whois":r=tool_whois(query)
    if chat_id:
        h=get_chat_history(chat_id);h.append({"role":"user","content":f"/{tool} {query}"});h.append({"role":"assistant","content":json.dumps(r,indent=2)});save_chat_history(chat_id,h)
    mem=get_memory();auto_extract(json.dumps(r),mem,source="ai")
    return jsonify({"result":r})

@app.route("/api/memory")
def mem_ep():return jsonify(get_memory())

@app.route("/api/memory/clear",methods=["POST"])
def clear_mem():save_memory({"notes":[],"targets":[],"findings":[],"context":[],"corrections":[]});return jsonify({"ok":1})

@app.route("/api/save",methods=["POST"])
def save_file():
    d=request.json
    # Sanitize filename — strip any path components to prevent traversal (e.g. ../../etc/passwd)
    raw_name = d.get("filename", f"output_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    safe_name = os.path.basename(raw_name) or f"output_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    fp=os.path.join(OUTPUT_DIR, safe_name)
    with open(fp,"w",encoding="utf-8") as f:f.write(d.get("content",""))
    return jsonify({"path":fp,"filename":os.path.basename(fp)})

@app.route("/api/run_code",methods=["POST"])
def run_code_ep():
    """Run code in sandbox and return output"""
    import subprocess
    data=request.json
    code=data.get("code","")
    lang=data.get("language","python").lower()
    
    SANDBOX_DIR=os.path.join(BASE_DIR,"sandbox")
    os.makedirs(SANDBOX_DIR,exist_ok=True)
    
    # Block actually dangerous patterns — NOT normal Python features like format()
    blocked = [
        "rm -rf /", "mkfs", "dd if=", ":(){", "shutdown", "reboot",
        "eval(", "exec(", "__import__", "compile(", "globals(", "locals(",
        "os.system", "subprocess.Popen", "subprocess.check_output",
        "ctypes", "sys.exit", "os.remove", "os.unlink", "shutil.rmtree",
        "open('/etc", "open('C:\\\\Windows", "open(\"C:\\\\Windows", "open(\"/etc"
    ]
    for b in blocked:
        if b in code:
            return jsonify({"error":f"Blocked: {b}","output":"","exit_code":1})
    
    ts=datetime.now().strftime("%Y%m%d_%H%M%S")
    
    if lang in ("python","py"):
        path=os.path.join(SANDBOX_DIR,f"run_{ts}.py")
        with open(path,"w",encoding="utf-8") as f:f.write(code)
        try:
            r=subprocess.run(["python",path],capture_output=True,text=True,timeout=30,cwd=SANDBOX_DIR)
            return jsonify({"output":r.stdout[:8000],"error":r.stderr[:3000],"exit_code":r.returncode,"language":"python"})
        except subprocess.TimeoutExpired:
            return jsonify({"output":"","error":"Timed out after 30s","exit_code":1,"language":"python"})
        except Exception as e:
            return jsonify({"output":"","error":str(e),"exit_code":1,"language":"python"})
    
    elif lang in ("javascript","js","node"):
        path=os.path.join(SANDBOX_DIR,f"run_{ts}.js")
        with open(path,"w",encoding="utf-8") as f:f.write(code)
        try:
            r=subprocess.run(["node",path],capture_output=True,text=True,timeout=30,cwd=SANDBOX_DIR)
            return jsonify({"output":r.stdout[:8000],"error":r.stderr[:3000],"exit_code":r.returncode,"language":"javascript"})
        except Exception as e:
            return jsonify({"output":"","error":str(e),"exit_code":1,"language":"javascript"})
    
    elif lang in ("html","css"):
        # Just return the HTML for preview — client renders it
        return jsonify({"output":code,"error":"","exit_code":0,"language":"html","preview":True})
    
    elif lang in ("bash","sh","shell"):
        path=os.path.join(SANDBOX_DIR,f"run_{ts}.sh")
        with open(path,"w",encoding="utf-8") as f:f.write(code)
        try:
            r=subprocess.run(["bash",path],capture_output=True,text=True,timeout=30,cwd=SANDBOX_DIR)
            return jsonify({"output":r.stdout[:8000],"error":r.stderr[:3000],"exit_code":r.returncode,"language":"bash"})
        except Exception as e:
            return jsonify({"output":"","error":str(e),"exit_code":1,"language":"bash"})
    
    else:
        return jsonify({"output":"","error":f"Run not supported for {lang}. Supported: python, javascript, html, bash","exit_code":1,"language":lang})

@app.route("/api/agent/run",methods=["POST"])
def agent_run():
    """Run the autonomous agent for a given task"""
    try:
        from agent_core import run_agent_streaming, run_agent_streaming_native
    except ImportError:
        return jsonify({"error":"Agent modules not found. Ensure agent_core.py and agent_tools.py are in C:\\atherix-red\\"}),500
    
    data=request.json
    goal=data.get("goal","")
    chat_id=data.get("chat_id","")
    use_native_tools=data.get("use_native_tools", False)
    settings=get_settings()
    
    if not goal:return jsonify({"error":"No goal provided"}),400
    
    # Save task to chat history
    if chat_id:
        h=get_chat_history(chat_id)
        h.append({"role":"user","content":f"[AGENT MODE] {goal}"})
        save_chat_history(chat_id,h)
    
    agent_fn = run_agent_streaming_native if use_native_tools else run_agent_streaming
    
    def generate():
        final_summary=""
        full_log=""
        for event_json in agent_fn(goal,settings):
            yield f"data: {event_json}\n\n"
            event=json.loads(event_json)
            
            # Build full log as we go
            if event.get("type")=="agent_executing":
                full_log+=f"\n**Step {event.get('step')}:** {event.get('think','')}\n🔧 `{event.get('tool','')}({json.dumps(event.get('args',{}))[:100]})`\n"
            if event.get("type")=="agent_step":
                r=event.get("result",{})
                r_str=json.dumps(r,indent=2,default=str)[:500] if isinstance(r,dict) else str(r)[:500]
                full_log+=f"\n📋 Result:\n```json\n{r_str}\n```\n"
            if event.get("type")=="agent_complete":
                final_summary=event.get("summary","")
                full_log+=f"\n---\n## ✅ Task Complete\n{final_summary}\n"
                mem=event.get("memory",{})
                if mem.get("findings"):
                    full_log+="\n**Findings:**\n"
                    for f in mem["findings"]: full_log+=f"- {f['content']}\n"
                if mem.get("files_created"):
                    full_log+="\n**Files Created:**\n"
                    for f in mem["files_created"]: full_log+=f"- {f}\n"
        
        # Save FULL step log to chat history, not just summary
        if chat_id and full_log:
            h=get_chat_history(chat_id)
            h.append({"role":"assistant","content":full_log})
            save_chat_history(chat_id,h)
    
    return Response(stream_with_context(generate()),mimetype='text/event-stream')

# ============================================================
# PRACTICE LAB API
# ============================================================

@app.route("/api/practice/labs")
def practice_labs():
    from lab_manager import list_labs
    return jsonify(list_labs())

@app.route("/api/practice/start",methods=["POST"])
def practice_start():
    data=request.json or {}
    lab_key=data.get("lab_key","")
    challenge=data.get("challenge","")
    if not lab_key or not challenge:
        return jsonify({"error":"lab_key and challenge are required"}),400
    from lab_manager import spin_up_lab
    from practice_engine import start_session
    lab_result=spin_up_lab(lab_key)
    if not lab_result.get("success"):
        return jsonify({"error":lab_result.get("message","Failed to start lab")}),500
    session=start_session(lab_key,challenge)
    if "error" in session:
        return jsonify(session),400
    return jsonify({"lab":lab_result,"session":session})

@app.route("/api/practice/run",methods=["POST"])
def practice_run():
    data=request.json or {}
    lab_key=data.get("lab_key","")
    challenge=data.get("challenge","")
    if not lab_key or not challenge:
        return jsonify({"error":"lab_key and challenge are required"}),400
    settings=get_settings()
    from practice_engine import run_full_session
    events_buffer=[]
    def _cb(event):
        events_buffer.append(event)
    def generate():
        import threading
        result_box={}
        def _run():
            result_box["session"]=run_full_session(lab_key,challenge,settings,stream_callback=_cb)
        t=threading.Thread(target=_run,daemon=True);t.start()
        sent=0
        while t.is_alive() or sent<len(events_buffer):
            while sent<len(events_buffer):
                yield f"data: {json.dumps(events_buffer[sent])}\n\n"
                sent+=1
            import time;time.sleep(0.1)
        if "session" in result_box:
            yield f"data: {json.dumps({'type':'practice_done','session_id':result_box['session'].get('session_id',''),'score':result_box['session'].get('score',{}),'new_achievements':result_box['session'].get('new_achievements',[])})}\n\n"
    return Response(stream_with_context(generate()),mimetype='text/event-stream')

@app.route("/api/practice/stop",methods=["POST"])
def practice_stop():
    data=request.json or {}
    lab_key=data.get("lab_key","")
    remove=data.get("remove",False)
    if not lab_key:
        return jsonify({"error":"lab_key required"}),400
    from lab_manager import tear_down_lab
    return jsonify(tear_down_lab(lab_key,remove=remove))

@app.route("/api/practice/history")
def practice_history():
    limit=int(request.args.get("limit",20))
    from practice_engine import get_session_history
    return jsonify(get_session_history(limit=limit))

@app.route("/api/practice/stats")
def practice_stats():
    from practice_engine import get_lab_completion_stats
    return jsonify(get_lab_completion_stats())

@app.route("/api/progression")
def api_progression():
    from progression import get_full_progression
    return jsonify(get_full_progression())

@app.route("/api/progression/award",methods=["POST"])
def api_progression_award():
    data=request.json or {}
    skill=data.get("skill_domain","web_app")
    base_xp=int(data.get("base_xp",0))
    if not base_xp:
        return jsonify({"error":"base_xp required"}),400
    from progression import award_xp,check_achievements,load_progression
    result=award_xp(skill,base_xp,
        efficiency_bonus=data.get("efficiency_bonus",False),
        first_time=data.get("first_time",False),
        multi_skill=data.get("multi_skill",False))
    prog=load_progression()
    new_ach=check_achievements(prog)
    result["new_achievements"]=new_ach
    return jsonify(result)

# ============================================================
# HTML
# ============================================================
HTML = r"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"><title>Atherix Red</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--b0:#08080d;--b1:#0e0e16;--b2:#151520;--b3:#1c1c2a;--b4:#232335;--a:#e63946;--a2:#a82835;--ag:rgba(230,57,70,.1);--t1:#ebebf0;--t2:#8a8aa5;--t3:#555570;--bd:#1e1e30;--code:#0b0b14;--g:#2ecc71;--y:#f39c12;--bl:#3498db}
body{font-family:'Segoe UI',-apple-system,sans-serif;background:var(--b0);color:var(--t1);height:100vh;display:flex;overflow:hidden}

.sl{width:250px;background:var(--b1);border-right:1px solid var(--bd);display:flex;flex-direction:column;flex-shrink:0}
.sl-h{padding:14px 16px;border-bottom:1px solid var(--bd);display:flex;align-items:center;justify-content:space-between}
.logo{font-size:17px;font-weight:700;color:var(--a);letter-spacing:1.5px}.logo span{font-size:10px;color:var(--t3);display:block;letter-spacing:1px;font-weight:400;margin-top:1px}
.nb{width:32px;height:32px;background:var(--a);border:none;border-radius:8px;color:#fff;font-size:18px;cursor:pointer;display:flex;align-items:center;justify-content:center}.nb:hover{background:var(--a2)}
.sl input.se{margin:6px 10px;padding:7px 10px;background:var(--b2);border:1px solid var(--bd);border-radius:6px;color:var(--t1);font-size:11px;outline:none;width:calc(100% - 20px)}.sl input.se:focus{border-color:var(--a2)}
.cl{flex:1;overflow-y:auto;padding:2px 6px}
.ci{padding:9px 10px;border-radius:7px;cursor:pointer;margin-bottom:1px;display:flex;align-items:center;gap:8px;position:relative;transition:background .1s}.ci:hover{background:var(--b3)}.ci.act{background:var(--ag);outline:1px solid rgba(230,57,70,.15)}
.ci-i{font-size:12px;color:var(--t3);flex-shrink:0}.ci.act .ci-i{color:var(--a)}.ci.pinned .ci-i{color:var(--y)}
.ci-b{flex:1;min-width:0}.ci-t{font-size:12px;color:var(--t2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.ci.act .ci-t{color:var(--t1)}.ci-d{font-size:9px;color:var(--t3);margin-top:1px}
.ci-a{display:none;gap:2px;flex-shrink:0}.ci:hover .ci-a{display:flex}
.cb{width:22px;height:22px;background:none;border:none;color:var(--t3);cursor:pointer;font-size:10px;border-radius:3px;display:flex;align-items:center;justify-content:center}.cb:hover{background:var(--b4);color:var(--t1)}
.sl-foot{padding:8px;border-top:1px solid var(--bd)}
.sl-btn{display:flex;align-items:center;gap:6px;width:100%;padding:7px 8px;background:none;border:none;color:var(--t2);font-size:11px;cursor:pointer;border-radius:5px;text-align:left}.sl-btn:hover{background:var(--b3);color:var(--t1)}

.main{flex:1;display:flex;flex-direction:column;min-width:0}
.ca{flex:1;overflow-y:auto;padding:20px 50px}
.welcome{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:var(--t3)}
.welcome h1{font-size:32px;color:var(--a);letter-spacing:3px;margin-bottom:6px}.welcome p{font-size:13px;margin-bottom:24px}
.hints{display:flex;gap:8px;flex-wrap:wrap;justify-content:center;max-width:600px}
.hint{padding:7px 14px;background:var(--b3);border:1px solid var(--bd);border-radius:18px;font-size:11px;color:var(--t2);cursor:pointer;transition:all .12s}.hint:hover{border-color:var(--a2);color:var(--t1);background:var(--ag)}

.msg{max-width:82%;margin:10px 0;animation:fi .2s ease}
@keyframes fi{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:translateY(0)}}
.msg.user{margin-left:auto}
.msg.user .mc{background:var(--a2);color:#fff;border-radius:14px 14px 3px 14px;padding:11px 15px;font-size:13.5px;line-height:1.5;user-select:text;cursor:text}
.msg.assistant .mc{background:var(--b2);border-radius:14px 14px 14px 3px;padding:14px 18px;border:1px solid var(--bd);font-size:13.5px;line-height:1.6;user-select:text;cursor:text}
.msg .meta{font-size:10px;color:var(--t3);margin-top:3px;padding:0 3px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}.msg.user .meta{justify-content:flex-end}
.msg-actions{display:none;gap:4px;margin-left:auto}.msg.assistant:hover .msg-actions{display:flex}
.ma{background:var(--b3);border:1px solid var(--bd);color:var(--t3);padding:3px 8px;border-radius:4px;font-size:10px;cursor:pointer}.ma:hover{color:var(--t1);border-color:var(--t3)}

.file-badge{display:inline-flex;align-items:center;gap:6px;background:var(--b3);border:1px solid var(--bd);border-radius:8px;padding:6px 10px;margin:4px 0;font-size:12px;color:var(--t2)}
.file-badge .fi{font-size:16px}
.img-preview{max-width:300px;max-height:200px;border-radius:8px;margin:6px 0;border:1px solid var(--bd)}

.think-toggle{font-size:10px;color:var(--a);cursor:pointer;padding:2px 6px;border-radius:3px}.think-toggle:hover{background:var(--ag)}
.think-block{display:none;background:var(--code);border:1px solid var(--bd);border-radius:6px;padding:10px;margin:8px 0;font-size:11px;color:var(--t3);max-height:200px;overflow-y:auto;white-space:pre-wrap;font-family:'Cascadia Code','Consolas',monospace}.think-block.open{display:block}

.mc pre{background:var(--code);border:1px solid var(--bd);border-radius:7px;padding:12px;margin:8px 0;overflow-x:auto;position:relative;user-select:text;white-space:pre}
.mc pre code{font-family:'Cascadia Code','Consolas',monospace;font-size:12.5px;line-height:1.5;background:none!important;padding:0!important;user-select:text;cursor:text;white-space:pre;tab-size:4}
.mc code{font-family:'Cascadia Code','Consolas',monospace;font-size:12.5px}
.mc p{margin:5px 0}.mc strong{color:var(--a);font-weight:600}.mc h1,.mc h2,.mc h3{color:var(--t1);margin:12px 0 6px;font-size:14px}.mc ul,.mc ol{padding-left:18px;margin:5px 0}.mc li{margin:3px 0}.mc hr{border:none;border-top:1px solid var(--bd);margin:10px 0}
.cda{position:absolute;top:6px;right:6px;display:flex;gap:3px;opacity:0.7;transition:opacity .15s}.mc pre:hover .cda{opacity:1}
.cab{background:var(--b3);border:1px solid var(--bd);color:var(--t3);padding:3px 8px;border-radius:3px;font-size:10px;cursor:pointer}.cab:hover{color:var(--t1)}

.tb{display:none;padding:6px 50px;font-size:11px;color:var(--a);animation:pulse 1.5s infinite}
@keyframes pulse{0%,100%{opacity:.4}50%{opacity:1}}

.ia{padding:12px 50px 16px;border-top:1px solid var(--bd);background:var(--b1)}
.file-queue{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:6px}
.fq-item{display:flex;align-items:center;gap:4px;background:var(--b3);border:1px solid var(--bd);border-radius:6px;padding:4px 8px;font-size:11px;color:var(--t2)}
.fq-x{background:none;border:none;color:var(--t3);cursor:pointer;font-size:12px;padding:0 2px}.fq-x:hover{color:var(--a)}
.iw{display:flex;gap:8px;align-items:flex-end}
#ci{flex:1;background:var(--b2);border:1px solid var(--bd);border-radius:10px;padding:12px 16px;color:var(--t1);font-size:13.5px;font-family:inherit;resize:none;max-height:140px;min-height:44px;outline:none}#ci:focus{border-color:var(--a2)}#ci::placeholder{color:var(--t3)}
.ib{width:44px;height:44px;border:none;border-radius:10px;color:#fff;font-size:18px;cursor:pointer;flex-shrink:0;display:flex;align-items:center;justify-content:center}
.ib.send{background:var(--a)}.ib.send:hover{background:var(--a2)}.ib.send:disabled{opacity:.3;cursor:not-allowed}
.ib.attach{background:var(--b3);color:var(--t2);border:1px solid var(--bd)}.ib.attach:hover{color:var(--t1);border-color:var(--t3)}
#fileInput{display:none}

.drop-overlay{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(230,57,70,.08);border:3px dashed var(--a);z-index:200;align-items:center;justify-content:center;font-size:20px;color:var(--a);letter-spacing:2px}
.drop-overlay.active{display:flex}

.sr{width:220px;background:var(--b1);border-left:1px solid var(--bd);display:flex;flex-direction:column;flex-shrink:0}
.ss{padding:10px 12px 4px;font-size:9px;font-weight:600;color:var(--t3);text-transform:uppercase;letter-spacing:1.5px}
.tb2{display:flex;align-items:center;gap:7px;width:calc(100% - 14px);margin:0 7px;padding:7px 8px;background:none;border:none;color:var(--t2);font-size:11px;cursor:pointer;border-radius:5px;text-align:left}.tb2:hover{background:var(--ag);color:var(--t1)}
.mp{flex:1;overflow-y:auto;padding:0 3px}
.mi{padding:4px 8px;font-size:10px;color:var(--t2);border-left:2px solid var(--bd);margin:2px 7px;word-break:break-word}.mi.target{border-color:var(--a)}.mi.finding{border-color:var(--y)}.mi.context{border-color:var(--g)}.mi.correction{border-color:#e74c3c}
.tc{padding:8px;border-top:1px solid var(--bd);display:flex;gap:3px}
.tcb{flex:1;padding:4px;background:var(--b3);border:1px solid var(--bd);color:var(--t2);font-size:9px;cursor:pointer;border-radius:3px}.tcb:hover,.tcb.active{background:var(--ag);border-color:var(--a2);color:var(--t1)}
.stat{padding:6px 12px;border-top:1px solid var(--bd);display:flex;align-items:center;gap:8px;font-size:10px;color:var(--t3)}
.dot{width:6px;height:6px;border-radius:50%;background:var(--g)}.dot.off{background:#e74c3c}

.mo{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.55);z-index:100;align-items:center;justify-content:center}.mo.active{display:flex}
.md{background:var(--b1);border:1px solid var(--bd);border-radius:10px;padding:20px;width:420px;max-height:80vh;overflow-y:auto}
.md h3{color:var(--a);margin-bottom:14px;font-size:15px}
.md input,.md textarea,.md select{width:100%;padding:10px;background:var(--b2);border:1px solid var(--bd);border-radius:6px;color:var(--t1);font-size:13px;outline:none;margin-bottom:10px;font-family:inherit}.md input:focus,.md textarea:focus{border-color:var(--a2)}
.md label{font-size:11px;color:var(--t2);margin-bottom:4px;display:block}
.md-a{display:flex;gap:6px;justify-content:flex-end;margin-top:6px}
.mdb{padding:7px 16px;border-radius:5px;border:none;font-size:12px;cursor:pointer}.mdb.p{background:var(--a);color:#fff}.mdb.s{background:var(--b3);color:var(--t2);border:1px solid var(--bd)}

.files-list{max-height:200px;overflow-y:auto}
.fl-item{display:flex;align-items:center;justify-content:space-between;padding:6px 8px;border-bottom:1px solid var(--bd);font-size:11px;color:var(--t2)}
.fl-item a{color:var(--bl);text-decoration:none;font-size:10px}.fl-item a:hover{color:var(--t1)}

.toast{position:fixed;bottom:70px;right:16px;background:var(--b3);border:1px solid var(--g);border-radius:6px;padding:6px 12px;font-size:11px;color:var(--g);z-index:50;animation:fi .3s ease}
::-webkit-scrollbar{width:4px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:var(--bd);border-radius:2px}

/* PRACTICE UI */
.main-tab{padding:10px 20px;background:none;border:none;border-bottom:2px solid transparent;color:var(--t3);font-size:12px;font-weight:600;cursor:pointer;letter-spacing:.5px;transition:color .15s,border-color .15s}
.main-tab.active{color:var(--a);border-bottom-color:var(--a)}
.main-tab:hover{color:var(--t1)}
.lab-card{background:var(--b2);border:1px solid var(--bd);border-radius:10px;padding:14px 16px;cursor:pointer;transition:border-color .15s}
.lab-card:hover{border-color:var(--a)}
.lab-card .lab-name{font-size:13px;font-weight:700;color:var(--t1);margin-bottom:3px}
.lab-card .lab-desc{font-size:10px;color:var(--t3);line-height:1.4;margin-bottom:10px}
.lab-card .lab-meta{font-size:10px;color:var(--t2);display:flex;gap:10px}
.lab-card .lab-running{color:var(--g)}
.skill-bar-row{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.skill-bar-icon{font-size:14px;width:20px;text-align:center}
.skill-bar-info{flex:1}
.skill-bar-label{font-size:10px;color:var(--t2);display:flex;justify-content:space-between;margin-bottom:3px}
.skill-bar-track{background:var(--b3);border-radius:3px;height:6px}
.skill-bar-fill{height:6px;border-radius:3px;transition:width .5s ease}
.chal-row{background:var(--b3);border:1px solid var(--bd);border-radius:6px;padding:10px 12px;cursor:pointer;transition:border-color .15s}
.chal-row:hover,.chal-row.selected{border-color:var(--a)}
.chal-row.selected{background:rgba(230,57,70,.08)}
.chal-diff-easy{color:var(--g)}.chal-diff-medium{color:#f39c12}.chal-diff-hard{color:var(--a)}
.pf-think{color:#a0c4ff;margin:6px 0 2px}.pf-act{color:#ffd166;margin:2px 0}.pf-result{color:#8bc34a;margin:2px 0 10px;padding-left:16px}
@keyframes xpPop{from{transform:scale(.6);opacity:0}to{transform:scale(1);opacity:1}}
.session-row{background:var(--b2);border:1px solid var(--bd);border-radius:6px;padding:10px 14px;font-size:11px;display:flex;justify-content:space-between;align-items:center}
.session-row .sr-label{color:var(--t1);font-weight:600}
.session-row .sr-meta{color:var(--t3)}

/* CODE PANEL */
.cp{position:fixed;top:0;right:0;width:600px;height:100vh;background:var(--b1);border-left:1px solid var(--bd);display:flex;flex-direction:column;z-index:200;transform:translateX(100%);transition:transform .25s cubic-bezier(.4,0,.2,1)}
.cp.open{transform:translateX(0)}
.cp-head{padding:12px 16px;border-bottom:1px solid var(--bd);display:flex;align-items:center;gap:10px;flex-shrink:0}
.cp-title{flex:1;font-size:13px;color:var(--t2);font-family:'Cascadia Code','Consolas',monospace}
.cp-lang{font-size:10px;padding:2px 8px;background:var(--aglow);border:1px solid var(--a2);border-radius:3px;color:var(--a);text-transform:uppercase;letter-spacing:1px}
.cp-close{background:none;border:none;color:var(--t3);cursor:pointer;font-size:18px;padding:0 4px}.cp-close:hover{color:var(--t1)}
.cp-actions{padding:8px 12px;border-bottom:1px solid var(--bd);display:flex;gap:6px;flex-shrink:0}
.cp-btn{padding:6px 14px;border-radius:6px;border:none;font-size:12px;cursor:pointer;font-family:inherit;transition:all .12s}
.cp-btn.run{background:var(--a);color:#fff}.cp-btn.run:hover{background:var(--a2)}
.cp-btn.preview{background:var(--bl);color:#fff;opacity:.8}.cp-btn.preview:hover{opacity:1}
.cp-btn.copy{background:var(--b3);color:var(--t2);border:1px solid var(--bd)}.cp-btn.copy:hover{color:var(--t1)}
.cp-btn.save{background:var(--b3);color:var(--t2);border:1px solid var(--bd)}.cp-btn.save:hover{color:var(--t1)}
.cp-tabs{display:flex;gap:2px;padding:6px 12px;border-bottom:1px solid var(--bd);flex-shrink:0;overflow-x:auto}
.cp-tab{padding:4px 12px;border-radius:4px;font-size:11px;cursor:pointer;color:var(--t3);background:none;border:1px solid transparent;white-space:nowrap}
.cp-tab.active{color:var(--t1);background:var(--b3);border-color:var(--bd)}
.cp-editor{flex:1;display:flex;flex-direction:column;min-height:0}
.cp-code{flex:1;font-family:'Cascadia Code','Consolas',monospace;font-size:13px;line-height:1.6;background:var(--code);color:var(--t1);border:none;outline:none;resize:none;padding:16px;overflow-y:auto;white-space:pre;tab-size:4;min-height:0}
.cp-code:focus{outline:none}
.cp-output{border-top:1px solid var(--bd);flex-shrink:0}
.cp-out-head{padding:6px 14px;font-size:10px;font-weight:600;color:var(--t3);text-transform:uppercase;letter-spacing:1px;display:flex;align-items:center;justify-content:space-between;background:var(--b2)}
.cp-out-body{padding:12px 16px;font-family:'Cascadia Code','Consolas',monospace;font-size:12px;color:var(--t1);background:var(--code);max-height:220px;overflow-y:auto;white-space:pre-wrap}
.cp-out-body.err{color:#e74c3c}
.cp-preview-frame{flex:1;border:none;background:#fff;min-height:0}
.cp-split{display:flex;flex-direction:column;flex:1;min-height:0}
.cp-split .cp-code{flex:1;min-height:120px}
/* Resize handle */
.cp-resize{position:absolute;left:-4px;top:0;width:8px;height:100%;cursor:ew-resize;z-index:10}
/* Dim main content when panel open */
.main-dim{transition:opacity .25s}.main-dim.dimmed{opacity:.6;pointer-events:none}
</style>
</head>
<body>

<div class="sl">
    <div class="sl-h"><div class="logo">ATHERIX RED<span>Penetration Testing AI</span></div><button class="nb" onclick="newChat()" title="New Chat (Ctrl+N)">+</button></div>
    <input class="se" placeholder="Search chats..." oninput="filterChats(this.value)">
    <div class="cl" id="chatList"></div>
    <div class="sl-foot">
        <button class="sl-btn" onclick="openSettings()">⚙ Settings</button>
        <button class="sl-btn" onclick="openFiles()">📁 Files</button>
    </div>
</div>

<div class="main">
    <div style="padding:0 0 0 0;border-bottom:1px solid var(--bd);display:flex;align-items:stretch;background:var(--b1);flex-shrink:0">
        <button id="tabChats" class="main-tab active" onclick="switchTab('chats')">💬 Chats</button>
        <button id="tabPractice" class="main-tab" onclick="switchTab('practice')">🎯 Practice</button>
        <span id="chatTitle" style="font-size:13px;color:var(--t2);flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;align-self:center;padding-left:12px">Atherix Red</span>
        <input id="chatSearch" placeholder="Search in chat..." style="width:200px;padding:5px 10px;background:var(--b2);border:1px solid var(--bd);border-radius:6px;color:var(--t1);font-size:11px;outline:none;margin:6px 10px 6px 0" oninput="searchInChat(this.value)">
    </div>
    <div class="ca" id="chatArea" ondragover="dragOver(event)" ondragleave="dragLeave(event)" ondrop="dropFile(event)">
        <div class="welcome" id="ws"><h1>ATHERIX RED</h1><p>Penetration Testing AI</p>
        <div class="hints">
            <div class="hint" onclick="qp('Walk me through a full black box pentest on a web app at 192.168.1.100')">Black box pentest</div>
            <div class="hint" onclick="qp('Write a Python port scanner with banner grabbing and service detection')">Port scanner</div>
            <div class="hint" onclick="qp('All Linux privilege escalation techniques with commands')">Linux privesc</div>
            <div class="hint" onclick="qp('How to enumerate Active Directory - full methodology')">AD enumeration</div>
            <div class="hint" onclick="qp('Write reverse shell one-liners for every common language')">Reverse shells</div>
            <div class="hint" onclick="qp('OWASP Top 10 exploitation with real payloads')">OWASP Top 10</div>
        </div></div>
    </div>
    <div class="drop-overlay" id="dropOverlay">DROP FILES HERE</div>
    <div class="tb" id="tb">⚡ Atherix Red is thinking...</div>
    <div class="ia">
        <div class="file-queue" id="fileQueue"></div>
        <div class="iw">
            <button class="ib attach" onclick="document.getElementById('fileInput').click()" title="Attach file">📎</button>
            <input type="file" id="fileInput" multiple onchange="handleFiles(this.files)">
            <textarea id="ci" placeholder="Ask Atherix Red anything... (drop files here)" rows="1" onkeydown="hk(event)" oninput="ar(this)"></textarea>
            <button class="ib send" id="sb" onclick="send()">→</button>
            <button class="ib attach" id="smartBtn" onclick="toggleSmart()" title="Smart Mode (self-correction + RAG)" style="font-size:14px;background:var(--g);border-color:var(--g)">🧠</button>
            <button class="ib attach" id="agentBtn" onclick="toggleAgent()" title="Agent Mode (autonomous)" style="font-size:14px">🤖</button>
        </div>
    </div>
</div>

<div class="sr">
    <div class="ss">Recon Tools</div>
    <button class="tb2" onclick="ot('cve')">🔍 CVE Lookup</button>
    <button class="tb2" onclick="ot('scanip')">📡 IP Scanner</button>
    <button class="tb2" onclick="ot('exploit')">💀 Exploit Search</button>
    <button class="tb2" onclick="ot('whois')">🌐 WHOIS</button>
    <div class="ss" style="margin-top:6px">Memory</div>
    <div class="mp" id="mp"><div style="padding:6px 10px;font-size:10px;color:var(--t3)">No memories yet</div></div>
    <div class="tc">
        <button class="tcb" onclick="st('low',this)">Low</button>
        <button class="tcb active" onclick="st('med',this)">Med</button>
        <button class="tcb" onclick="st('high',this)">High</button>
    </div>
    <div class="stat" id="sbar"><div class="dot" id="sdot"></div><span id="stxt">Connecting...</span></div>
</div>

<!-- PRACTICE PANEL -->
<div id="practicePanel" style="display:none;flex:1;overflow-y:auto;padding:20px 28px;background:var(--b0);flex-direction:column;gap:18px">

    <!-- Rank bar -->
    <div style="background:var(--b2);border:1px solid var(--bd);border-radius:10px;padding:16px 20px;margin-bottom:4px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
            <span style="color:var(--a);font-size:14px;font-weight:700;letter-spacing:1px" id="prRank">CIVILIAN</span>
            <span style="color:var(--t3);font-size:11px" id="prSessions">0 sessions · 0 challenges</span>
        </div>
        <div id="skillBars"></div>
    </div>

    <!-- Labs grid -->
    <div>
        <div style="color:var(--t2);font-size:12px;font-weight:600;margin-bottom:10px;letter-spacing:1px">AVAILABLE LABS</div>
        <div id="labGrid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:10px"></div>
    </div>

    <!-- Recent sessions -->
    <div>
        <div style="color:var(--t2);font-size:12px;font-weight:600;margin-bottom:10px;letter-spacing:1px">RECENT SESSIONS</div>
        <div id="sessionHistory" style="display:flex;flex-direction:column;gap:6px"></div>
    </div>
</div>

<!-- Practice session live feed -->
<div id="practiceFeed" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.85);z-index:3000;flex-direction:column">
    <div style="background:var(--b1);border-bottom:1px solid var(--bd);padding:12px 20px;display:flex;align-items:center;gap:12px">
        <span style="color:var(--a);font-weight:700;font-size:14px" id="pfTitle">PRACTICE SESSION</span>
        <span id="pfStep" style="color:var(--t3);font-size:11px">Step 0</span>
        <div style="flex:1;background:var(--b3);border-radius:4px;height:6px;margin:0 10px">
            <div id="pfBar" style="height:6px;background:var(--a);border-radius:4px;width:0%;transition:width 0.4s"></div>
        </div>
        <button onclick="abortPractice()" style="background:var(--b3);border:1px solid var(--bd);color:var(--t2);padding:5px 14px;border-radius:6px;cursor:pointer;font-size:11px">Abort</button>
    </div>
    <div id="pfLog" style="flex:1;overflow-y:auto;padding:16px 24px;font-family:Consolas,monospace;font-size:12px;line-height:1.7"></div>
</div>

<!-- Lab challenge modal -->
<div id="labModal" class="mo" style="z-index:2500">
    <div style="background:var(--b2);border:1px solid var(--bd);border-radius:12px;padding:24px;min-width:380px;max-width:520px">
        <div style="font-size:15px;font-weight:700;color:var(--t1);margin-bottom:4px" id="lmName"></div>
        <div style="font-size:11px;color:var(--t3);margin-bottom:16px" id="lmDesc"></div>
        <div style="font-size:11px;color:var(--t2);margin-bottom:8px;font-weight:600">SELECT CHALLENGE</div>
        <div id="lmChallenges" style="display:flex;flex-direction:column;gap:6px;max-height:280px;overflow-y:auto;margin-bottom:16px"></div>
        <div style="display:flex;gap:8px">
            <button onclick="document.getElementById('labModal').classList.remove('active')" style="flex:1;padding:9px;background:var(--b3);border:1px solid var(--bd);border-radius:6px;color:var(--t2);cursor:pointer;font-size:12px">Cancel</button>
            <button id="lmStart" onclick="startPracticeSession()" style="flex:2;padding:9px;background:var(--a);border:none;border-radius:6px;color:#fff;cursor:pointer;font-size:12px;font-weight:700">▶ Start</button>
        </div>
    </div>
</div>

<!-- XP award animation -->
<div id="xpOverlay" style="display:none;position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:4000;text-align:center;pointer-events:none">
    <div id="xpBadge" style="background:var(--b2);border:2px solid var(--a);border-radius:16px;padding:24px 36px;animation:xpPop 0.4s ease">
        <div style="font-size:32px;margin-bottom:6px" id="xpIcon">⚡</div>
        <div style="color:var(--a);font-size:22px;font-weight:900" id="xpAmount">+150 XP</div>
        <div style="color:var(--t2);font-size:12px;margin-top:4px" id="xpDomain">Web Application Hacking</div>
        <div style="color:var(--g);font-size:13px;font-weight:700;margin-top:6px;display:none" id="xpLevelUp"></div>
    </div>
</div>

<!-- Modals -->
<div class="cp" id="codePanel">
    <div class="cp-resize" id="cpResize"></div>
    <div class="cp-head">
        <span class="cp-lang" id="cpLang">python</span>
        <span class="cp-title" id="cpTitle">Code</span>
        <button class="cp-close" onclick="closePanel()">✕</button>
    </div>
    <div class="cp-actions">
        <button class="cp-btn run" id="cpRunBtn" onclick="runCode()">▶ Run</button>
        <button class="cp-btn preview" id="cpPreviewBtn" onclick="previewCode()" style="display:none">🌐 Preview</button>
        <button class="cp-btn copy" onclick="copyPanel()">Copy</button>
        <button class="cp-btn save" onclick="savePanel()">Save</button>
        <span id="cpStatus" style="font-size:11px;color:var(--t3);margin-left:auto;align-self:center"></span>
    </div>
    <div class="cp-tabs" id="cpTabs"></div>
    <div class="cp-split">
        <textarea class="cp-code" id="cpCode" spellcheck="false" onkeydown="handleTabKey(event)"></textarea>
        <div class="cp-output" id="cpOutput" style="display:none">
            <div class="cp-out-head">
                <span>Output</span>
                <button style="background:none;border:none;color:var(--t3);cursor:pointer;font-size:11px" onclick="document.getElementById('cpOutput').style.display='none'">✕</button>
            </div>
            <div class="cp-out-body" id="cpOutBody"></div>
        </div>
        <iframe class="cp-preview-frame" id="cpPreviewFrame" style="display:none"></iframe>
    </div>
</div>
<div class="mo" id="toolModal"><div class="md"><h3 id="mt">Tool</h3><input id="mi" onkeydown="if(event.key==='Enter')rt()"><div class="md-a"><button class="mdb s" onclick="cm()">Cancel</button><button class="mdb p" onclick="rt()">Run</button></div></div></div>

<div class="mo" id="settingsModal"><div class="md" style="width:480px">
    <h3>⚙ Settings</h3>
    <label>System Prompt</label><textarea id="sysPrompt" rows="6" style="font-size:12px"></textarea>
    <label>Temperature (0.0 - 1.0)</label><input id="sTemp" type="number" step="0.1" min="0" max="1">
    <label>Context Window (tokens)</label><input id="sCtx" type="number" step="1024" min="2048" max="131072">
    <label>Max Output (tokens)</label><input id="sPred" type="number" step="1024" min="512" max="32768">
    <label>Thinking Budget (tokens)</label><input id="sThink" type="number" step="64" min="0" max="4096">
    <div class="md-a"><button class="mdb s" onclick="document.getElementById('settingsModal').classList.remove('active')">Cancel</button><button class="mdb p" onclick="saveSettingsUI()">Save</button></div>
</div></div>

<div class="mo" id="renameModal"><div class="md" style="width:340px">
    <h3>✏ Rename Chat</h3>
    <input id="ri" onkeydown="if(event.key==='Enter')cr()" placeholder="Chat name...">
    <div class="md-a"><button class="mdb s" onclick="document.getElementById('renameModal').classList.remove('active')">Cancel</button><button class="mdb p" onclick="cr()">Rename</button></div>
</div></div>

<div class="mo" id="filesModal"><div class="md" style="width:500px">
    <h3>📁 Created Files</h3>
    <div class="files-list" id="filesList"></div>
    <div class="md-a" style="margin-top:12px"><button class="mdb s" onclick="document.getElementById('filesModal').classList.remove('active')">Close</button></div>
</div></div>

<script>
let cid=null,ctool=null,chats=[],renId=null,pendingFiles=[];

document.addEventListener('keydown',e=>{
    if(e.ctrlKey&&e.key==='n'){e.preventDefault();newChat()}
    if(e.ctrlKey&&e.key==='f'){e.preventDefault();document.getElementById('chatSearch').focus()}
    if(e.key==='Escape'){cm();document.querySelectorAll('.mo').forEach(m=>m.classList.remove('active'));document.getElementById('chatSearch').value='';searchInChat('')}
});

// Chat mgmt
async function loadChats(){chats=await(await fetch('/api/chats')).json();renderChats(chats)}
function renderChats(list){const el=document.getElementById('chatList');if(!list.length){el.innerHTML='<div style="padding:14px;text-align:center;font-size:11px;color:var(--t3)">No chats yet</div>';return}
    const pin=list.filter(c=>c.pinned),unpin=list.filter(c=>!c.pinned);let h='';
    const r=arr=>arr.map(c=>`<div class="ci ${c.id===cid?'act':''} ${c.pinned?'pinned':''}" onclick="loadChat('${c.id}')"><div class="ci-i">${c.pinned?'📌':'💬'}</div><div class="ci-b"><div class="ci-t">${esc(c.title)}</div><div class="ci-d">${fd(c.updated||c.created)}</div></div><div class="ci-a"><button class="cb" onclick="event.stopPropagation();tp('${c.id}')" title="${c.pinned?'Unpin':'Pin'}">📌</button><button class="cb" onclick="event.stopPropagation();rn('${c.id}','${esc(c.title)}')" title="Rename">✏</button><button class="cb" onclick="event.stopPropagation();dc('${c.id}')" title="Delete">🗑</button></div></div>`).join('');
    if(pin.length)h+=r(pin);if(pin.length&&unpin.length)h+='<div style="border-top:1px solid var(--bd);margin:4px 8px"></div>';h+=r(unpin);el.innerHTML=h}
function filterChats(q){renderChats(q?chats.filter(c=>c.title.toLowerCase().includes(q.toLowerCase())):chats)}
function fd(i){if(!i)return'';const d=new Date(i),n=new Date();return d.toDateString()===n.toDateString()?d.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}):d.toLocaleDateString([],{month:'short',day:'numeric'})}
function esc(t){return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#039;')}

async function newChat(){const c=await(await fetch('/api/chats/new',{method:'POST'})).json();cid=c.id;await loadChats();document.getElementById('chatArea').innerHTML='';pendingFiles=[];document.getElementById('fileQueue').innerHTML='';document.getElementById('ci').focus()}
async function loadChat(id){cid=id;renderChats(chats);const hist=await(await fetch(`/api/chats/${id}`)).json();const a=document.getElementById('chatArea');a.innerHTML='';
    if(!hist.length)a.innerHTML='<div class="welcome"><h1>ATHERIX RED</h1><p>Penetration Testing AI</p><div class="hints"><div class="hint" onclick="qp(\'Full black box pentest\')">Black box pentest</div><div class="hint" onclick="qp(\'Port scanner script\')">Port scanner</div><div class="hint" onclick="qp(\'Linux privesc\')">Linux privesc</div></div></div>';
    else for(const m of hist)addMsg(m.role,m.content);document.getElementById('ci').focus()}
async function tp(id){await fetch(`/api/chats/${id}/pin`,{method:'POST'});await loadChats()}
function rn(id,t){renId=id;document.getElementById('ri').value=t;document.getElementById('renameModal').classList.add('active');document.getElementById('ri').focus()}
async function cr(){const t=document.getElementById('ri').value.trim();if(t&&renId){await fetch(`/api/chats/${renId}/rename`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:t})});await loadChats()}document.getElementById('renameModal').classList.remove('active')}
async function dc(id){if(!confirm('Delete this chat?'))return;await fetch(`/api/chats/${id}/delete`,{method:'POST'});if(cid===id){cid=null;document.getElementById('chatArea').innerHTML='<div class="welcome"><h1>ATHERIX RED</h1><p>Penetration Testing AI</p></div>'}await loadChats()}

// File handling
function dragOver(e){e.preventDefault();document.getElementById('dropOverlay').classList.add('active')}
function dragLeave(e){document.getElementById('dropOverlay').classList.remove('active')}
async function dropFile(e){e.preventDefault();document.getElementById('dropOverlay').classList.remove('active');if(e.dataTransfer.files.length)await handleFiles(e.dataTransfer.files)}
async function handleFiles(files){
    for(const f of files){
        const fd=new FormData();fd.append('file',f);
        try{const r=await(await fetch('/api/upload',{method:'POST',body:fd})).json();
            pendingFiles.push(r);renderFileQueue()}catch(e){toast('Upload failed: '+e.message)}
    }
    document.getElementById('fileInput').value='';
}
function renderFileQueue(){const q=document.getElementById('fileQueue');q.innerHTML=pendingFiles.map((f,i)=>{
    const isImg=f.is_image||/\.(png|jpg|jpeg|gif|webp|bmp)$/i.test(f.filename);
    const thumb=isImg?`<img src="/api/uploads/${esc(f.saved_name)}" style="height:32px;border-radius:4px;margin-right:4px">`:'';
    return`<div class="fq-item">${thumb}<span class="fi">${isImg?'🖼':'📄'}</span>${esc(f.filename)} <span style="color:var(--t3)">(${(f.size/1024).toFixed(1)}KB)</span><button class="fq-x" onclick="pendingFiles.splice(${i},1);renderFileQueue()">✕</button></div>`}).join('')}

// Messages
function fmt(text){
    // Extract code blocks first, replace with placeholders so \n replacement doesn't touch them
    const codeBlocks=[];
    text=text.replace(/```(\w*)\n?([\s\S]*?)```/g,(m,l,c)=>{
        const idx=codeBlocks.length;
        codeBlocks.push(`<pre><code class="language-${l}">${esc(c)}</code><div class="cda"><button class="cab" onclick="cc(this)">Copy</button><button class="cab" onclick="sc(this)">Save</button></div></pre>`);
        return `\x00CODEBLOCK${idx}\x00`;
    });
    // Process markdown on remaining text
    text=text.replace(/`([^`]+)`/g,'<code style="background:var(--code);padding:1px 5px;border-radius:3px">$1</code>');
    text=text.replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>');
    text=text.replace(/\[([^\]]+)\]\(([^)]+)\)/g,'<a href="$2" target="_blank" style="color:var(--bl);text-decoration:none">📥 $1</a>');
    text=text.replace(/^### (.+)$/gm,'<h3>$1</h3>');
    text=text.replace(/^## (.+)$/gm,'<h2>$1</h2>');
    text=text.replace(/^---$/gm,'<hr>');
    text=text.replace(/^- (.+)$/gm,'<li>$1</li>');
    text=text.replace(/\n/g,'<br>');
    // Restore code blocks with original content intact
    text=text.replace(/\x00CODEBLOCK(\d+)\x00/g,(m,i)=>codeBlocks[parseInt(i)]);
    return text}
function cc(b){navigator.clipboard.writeText(b.closest('pre').querySelector('code').textContent);b.textContent='Copied!';setTimeout(()=>b.textContent='Copy',1500)}
async function sc(b){const c=b.closest('pre').querySelector('code').textContent;const l=b.closest('pre').querySelector('code').className.replace('language-','');
    const ext={python:'.py',py:'.py',bash:'.sh',sh:'.sh',javascript:'.js',js:'.js',html:'.html',c:'.c',cpp:'.cpp',php:'.php',sql:'.sql',powershell:'.ps1','':'.txt'};
    const fn=`atherix_code_${Date.now()}${ext[l]||'.txt'}`;await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:c,filename:fn})});
    b.textContent='Saved!';setTimeout(()=>b.textContent='Save',1500)}

function addMsg(role,content,stats,thinkLen){
    document.querySelector('.welcome')?.remove();
    const a=document.getElementById('chatArea'),div=document.createElement('div');div.className=`msg ${role}`;
    const now=new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
    let meta=`<div class="meta"><span>${now}</span>`;
    if(role==='assistant'){
        if(stats)meta+=`<span>${stats.tokens} tok · ${stats.duration}s</span>`;
        if(thinkLen>0)meta+=`<span class="think-toggle" onclick="this.parentElement.parentElement.querySelector('.think-block')?.classList.toggle('open')">💭 Thinking (${thinkLen})</span>`;
        meta+=`<div class="msg-actions"><button class="ma" onclick="copyMsg(this)">Copy</button><button class="ma" onclick="saveMsg(this)">Save</button><button class="ma" onclick="regen()">Regen</button></div>`}
    meta+='</div>';
    // Check for file badges in user messages
    let fileHtml='';
    if(role==='user'){
        const fm=content.match(/--- File: (.+?) ---/g);
        if(fm)fm.forEach(f=>{const n=f.replace('--- File: ','').replace(' ---','');fileHtml+=`<div class="file-badge"><span class="fi">📄</span>${esc(n)}</div>`});
    }
    const formatted=role==='assistant'?fmt(content):(esc(content.replace(/\n--- File:[\s\S]*?--- End File ---/g,'')).replace(/\n/g,'<br>')+fileHtml);
    div.innerHTML=`<div class="mc" data-raw="${btoa(unescape(encodeURIComponent(content)))}">${formatted}</div>${meta}`;
    a.appendChild(div);a.scrollTop=a.scrollHeight;
    div.querySelectorAll('pre code').forEach(b=>hljs.highlightElement(b))}

function copyMsg(b){navigator.clipboard.writeText(decodeURIComponent(escape(atob(b.closest('.msg').querySelector('.mc').dataset.raw))));b.textContent='Copied!';setTimeout(()=>b.textContent='Copy',1500)}
async function saveMsg(b){const r=decodeURIComponent(escape(atob(b.closest('.msg').querySelector('.mc').dataset.raw)));const fn=`response_${Date.now()}.md`;await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:r,filename:fn})});b.textContent='Saved!';setTimeout(()=>b.textContent='Save',1500)}
async function regen(){if(!cid)return;const h=await(await fetch(`/api/chats/${cid}`)).json();if(h.length<2)return;const lu=h[h.length-2];if(lu.role==='user'){document.getElementById('ci').value=lu.content;await loadChat(cid);send()}}

function toast(t){const el=document.createElement('div');el.className='toast';el.textContent=t;document.body.appendChild(el);setTimeout(()=>el.remove(),3000)}

// Input
function hk(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}}
function ar(el){el.style.height='auto';el.style.height=Math.min(el.scrollHeight,140)+'px'}
async function qp(t){if(!cid)await newChat();document.getElementById('ci').value=t;send()}

// Streaming send
async function send(){
    const input=document.getElementById('ci'),msg=input.value.trim();if(!msg&&!pendingFiles.length)return;
    if(!cid)await newChat();input.value='';input.style.height='auto';
    const filesForMsg=[...pendingFiles];addMsg('user',msg);
    pendingFiles=[];document.getElementById('fileQueue').innerHTML='';
    document.getElementById('tb').style.display='block';document.getElementById('sb').disabled=true;

    const a=document.getElementById('chatArea'),div=document.createElement('div');div.className='msg assistant';
    div.innerHTML='<div class="mc" data-raw=""></div><div class="meta"><span>'+new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})+'</span></div>';
    a.appendChild(div);const mc=div.querySelector('.mc');
    let full='',think='',thinkLen=0;

    try{
        const resp=await fetch('/api/chat/stream',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:msg,chat_id:cid,files:filesForMsg})});
        const reader=resp.body.getReader();const decoder=new TextDecoder();let buf='';
        while(true){
            const{done,value}=await reader.read();if(done)break;buf+=decoder.decode(value,{stream:true});
            const lines=buf.split('\n');buf=lines.pop();
            for(const line of lines){if(!line.startsWith('data: '))continue;
                try{const d=JSON.parse(line.slice(6));
                    if(d.type==='thinking'){think+=d.content;document.getElementById('tb').textContent='💭 Thinking... ('+think.length+' chars)'}
                    if(d.type==='content'){full+=d.content;mc.innerHTML=fmt(full);mc.dataset.raw=btoa(unescape(encodeURIComponent(full)));mc.querySelectorAll('pre code').forEach(b=>{if(!b.dataset.hl){hljs.highlightElement(b);b.dataset.hl='1'}});a.scrollTop=a.scrollHeight}
                    if(d.type==='done'){thinkLen=d.thinking_len||0;const dur=d.eval_duration?(d.eval_duration/1e9).toFixed(1):'?';
                        let mh=`<div class="meta"><span>${new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}</span><span>${d.eval_count||0} tok · ${dur}s</span>`;
                        if(thinkLen>0)mh+=`<span class="think-toggle" onclick="this.parentElement.nextElementSibling?.classList.toggle('open')">💭 Thinking (${thinkLen})</span>`;
                        mh+=`<div class="msg-actions"><button class="ma" onclick="copyMsg(this)">Copy</button><button class="ma" onclick="saveMsg(this)">Save</button><button class="ma" onclick="regen()">Regen</button></div></div>`;
                        if(thinkLen>0)mh+=`<div class="think-block">${esc(think)}</div>`;
                        div.querySelector('.meta')?.remove();div.querySelector('.think-block')?.remove();div.insertAdjacentHTML('beforeend',mh);
                        if(d.extracted?.length)toast('✓ '+d.extracted.join(', '));await loadChats();loadMem()}
                    if(d.type==='error'){mc.innerHTML=`<span style="color:var(--y)">⚠ ${esc(d.content)}</span>`}
                }catch(e){}}
        }
    }catch(e){mc.innerHTML='<span style="color:var(--y)">⚠ Connection error</span>'}
    document.getElementById('tb').style.display='none';document.getElementById('tb').textContent='⚡ Atherix Red is thinking...';document.getElementById('sb').disabled=false;input.focus()}

// Tools
function ot(tool){ctool=tool;const t={cve:'CVE Lookup',scanip:'IP Scanner',exploit:'Exploit Search',whois:'WHOIS'};const p={cve:'CVE-2024-0204',scanip:'8.8.8.8',exploit:'apache 2.4.49',whois:'example.com'};
    document.getElementById('mt').textContent=t[tool];document.getElementById('mi').placeholder=p[tool];document.getElementById('mi').value='';document.getElementById('toolModal').classList.add('active');document.getElementById('mi').focus()}
function cm(){document.getElementById('toolModal').classList.remove('active')}
async function rt(){const q=document.getElementById('mi').value.trim();if(!q)return;cm();if(!cid)await newChat();
    addMsg('user',`/${ctool} ${q}`);document.getElementById('tb').style.display='block';document.getElementById('tb').textContent='📡 Running tool...';
    try{const r=await(await fetch('/api/tool',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tool:ctool,query:q,chat_id:cid})})).json();
        addMsg('assistant','```json\n'+JSON.stringify(r.result,null,2)+'\n```');loadMem();loadChats()}catch(e){addMsg('assistant','⚠ Tool error')}
    document.getElementById('tb').style.display='none';document.getElementById('tb').textContent='⚡ Atherix Red is thinking...'}

// Settings
async function openSettings(){const s=await(await fetch('/api/settings')).json();
    document.getElementById('sysPrompt').value=s.system_prompt||'';document.getElementById('sTemp').value=s.temperature||0.7;
    document.getElementById('sCtx').value=s.num_ctx||16384;document.getElementById('sPred').value=s.num_predict||8192;
    document.getElementById('sThink').value=s.think_budget||512;document.getElementById('settingsModal').classList.add('active')}
async function saveSettingsUI(){
    const s={system_prompt:document.getElementById('sysPrompt').value,temperature:parseFloat(document.getElementById('sTemp').value),
        num_ctx:parseInt(document.getElementById('sCtx').value),num_predict:parseInt(document.getElementById('sPred').value),
        think_budget:parseInt(document.getElementById('sThink').value)};
    await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(s)});
    document.getElementById('settingsModal').classList.remove('active');toast('Settings saved');checkStatus()}
async function st(l,btn){await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({think_budget:{low:128,med:512,high:1024}[l]})});
    document.querySelectorAll('.tcb').forEach(b=>b.classList.remove('active'));btn.classList.add('active')}

// Files
async function openFiles(){const files=await(await fetch('/api/files')).json();const el=document.getElementById('filesList');
    el.innerHTML=files.length?files.map(f=>`<div class="fl-item"><span>📄 ${esc(f.name)} <span style="color:var(--t3)">(${(f.size/1024).toFixed(1)}KB)</span></span><a href="/api/files/download/${encodeURIComponent(f.name)}" target="_blank">Download</a></div>`).join(''):'<div style="padding:12px;color:var(--t3);font-size:12px;text-align:center">No files yet</div>';
    document.getElementById('filesModal').classList.add('active')}

async function loadMem(){try{const m=await(await fetch('/api/memory')).json();const p=document.getElementById('mp');let h='';
    for(const[c,items]of Object.entries(m))for(const i of items.slice(-6)){
        const cls=c==='targets'?'target':c==='findings'?'finding':c==='corrections'?'correction':'context';
        h+=`<div class="mi ${cls}">${c==='corrections'?'⚠ ':''}${esc(i.content)}</div>`}
    p.innerHTML=h||'<div style="padding:6px 10px;font-size:10px;color:var(--t3)">No memories yet</div>'}catch(e){}}

async function checkStatus(){try{const s=await(await fetch('/api/status')).json();document.getElementById('sdot').className='dot'+(s.connected?'':' off');
    document.getElementById('stxt').textContent=s.connected?`${s.model} · Think: ${s.think_budget}`:'Disconnected'}catch(e){document.getElementById('sdot').className='dot off';document.getElementById('stxt').textContent='Offline'}}

// Smart Mode (intelligence layer)
let smartMode=true; // ON by default — makes everything smarter
function toggleSmart(){
    smartMode=!smartMode;
    const btn=document.getElementById('smartBtn');
    btn.style.background=smartMode?'var(--g)':'var(--b3)';
    btn.style.borderColor=smartMode?'var(--g)':'var(--bd)';
    toast(smartMode?'🧠 Smart mode ON — self-correction + RAG + verification':'🧠 Smart mode OFF — raw model output');
}

async function sendSmart(msg,filesForMsg){
    if(!cid)await newChat();
    addMsg('user',msg);
    document.getElementById('tb').style.display='block';document.getElementById('sb').disabled=true;

    const a=document.getElementById('chatArea'),div=document.createElement('div');div.className='msg assistant';
    div.innerHTML='<div class="mc" data-raw="">🧠 Processing...</div><div class="meta"></div>';
    a.appendChild(div);const mc=div.querySelector('.mc');

    try{
        const resp=await fetch('/api/chat/smart',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:msg,chat_id:cid,files:filesForMsg})});
        const reader=resp.body.getReader();const decoder=new TextDecoder();let buf='';
        while(true){
            const{done,value}=await reader.read();if(done)break;
            buf+=decoder.decode(value,{stream:true});const lines=buf.split('\n');buf=lines.pop();
            for(const line of lines){if(!line.startsWith('data: '))continue;
                try{const d=JSON.parse(line.slice(6));
                    if(d.type==='status'){
                        document.getElementById('tb').textContent=`🧠 ${d.message}`;
                        mc.innerHTML=`🧠 <em>${esc(d.message)}</em>`}
                    if(d.type==='content'){
                        mc.innerHTML=fmt(d.content);
                        mc.dataset.raw=btoa(unescape(encodeURIComponent(d.content)));
                        mc.querySelectorAll('pre code').forEach(b=>{if(!b.dataset.hl){hljs.highlightElement(b);b.dataset.hl='1'}});
                        a.scrollTop=a.scrollHeight}
                    if(d.type==='done'){
                        const dur=d.eval_duration?(d.eval_duration/1e9).toFixed(1):'?';
                        let badges='';
                        if(d.strategy)badges+=`<span style="color:var(--bl)">${esc(d.strategy)}</span>`;
                        if(d.rag_used)badges+='<span style="color:var(--g)">🌐 RAG</span>';
                        if(d.verified)badges+='<span style="color:var(--g)">✓ Verified</span>';
                        if(d.corrections>0)badges+=`<span style="color:var(--y)">🔄 ${d.corrections}x corrected</span>`;
                        let mh=`<div class="meta"><span>${new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}</span><span>${d.eval_count||0} tok · ${dur}s</span>${badges}<div class="msg-actions"><button class="ma" onclick="copyMsg(this)">Copy</button><button class="ma" onclick="saveMsg(this)">Save</button><button class="ma" onclick="regen()">Regen</button></div></div>`;
                        div.querySelector('.meta')?.remove();div.insertAdjacentHTML('beforeend',mh);
                        if(d.extracted?.length)toast('✓ '+d.extracted.join(', '));
                        await loadChats();loadMem()}
                }catch(e){}}
            }
    }catch(e){mc.innerHTML='<span style="color:var(--y)">⚠ Connection error</span>'}
    document.getElementById('tb').style.display='none';document.getElementById('tb').textContent='⚡ Atherix Red is thinking...';document.getElementById('sb').disabled=false;document.getElementById('ci').focus();}

// Agent Mode
let agentMode=false;
function toggleAgent(){
    agentMode=!agentMode;
    const btn=document.getElementById('agentBtn');
    btn.style.background=agentMode?'var(--a)':'var(--b3)';
    btn.style.borderColor=agentMode?'var(--a)':'var(--bd)';
    document.getElementById('ci').placeholder=agentMode?'Describe a task for the agent (it will execute autonomously)...':'Ask Atherix Red anything...';
    toast(agentMode?'🤖 Agent mode ON — will execute tools autonomously':'Agent mode OFF');
}

async function runAgent(goal){
    if(!cid)await newChat();
    
    // Include pending files
    const filesForAgent=[...pendingFiles];
    let fileContext='';
    for(const f of filesForAgent){
        if(!f.is_image && f.content){
            fileContext+=`\n\n--- Attached File: ${f.filename} ---\n${f.content}\n--- End File ---`;
        }
    }
    pendingFiles=[];document.getElementById('fileQueue').innerHTML='';
    
    const fullGoal=goal+(fileContext?'\n\nThe user attached the following file(s). Work with this content:'+fileContext:'');
    
    // Show file badges in user message
    let userDisplay=`🤖 [AGENT] ${goal}`;
    for(const f of filesForAgent) userDisplay+=`\n📎 ${f.filename}`;
    addMsg('user',userDisplay);
    
    document.getElementById('tb').style.display='block';document.getElementById('sb').disabled=true;
    
    const a=document.getElementById('chatArea'),div=document.createElement('div');div.className='msg assistant';
    div.innerHTML='<div class="mc" data-raw="">🤖 <strong>Agent starting...</strong></div><div class="meta"></div>';
    a.appendChild(div);const mc=div.querySelector('.mc');
    let stepLog='';

    try{
        const resp=await fetch('/api/agent/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({goal:fullGoal,chat_id:cid})});
        const reader=resp.body.getReader();const decoder=new TextDecoder();let buf='';
        while(true){
            const{done,value}=await reader.read();if(done)break;
            buf+=decoder.decode(value,{stream:true});const lines=buf.split('\n');buf=lines.pop();
            for(const line of lines){if(!line.startsWith('data: '))continue;
                try{const d=JSON.parse(line.slice(6));
                    if(d.type==='agent_thinking'){
                        document.getElementById('tb').textContent=`🤖 Step ${d.step}: Thinking...`}
                    if(d.type==='agent_executing'){
                        stepLog+=`\n**Step ${d.step}:** ${d.think}\n🔧 \`${d.tool}(${JSON.stringify(d.args).slice(0,100)})\`\n`;
                        mc.innerHTML=fmt(stepLog+'\n⏳ Executing...');a.scrollTop=a.scrollHeight;
                        document.getElementById('tb').textContent=`🤖 Step ${d.step}: Running ${d.tool}...`}
                    if(d.type==='agent_step'){
                        const r=d.result||{};
                        // Check if this was a file creation
                        if(r.status==='created'&&r.path){
                            const fn=r.path.split('\\').pop().split('/').pop();
                            stepLog+=`\n📁 **File created:** [${fn}](/api/files/download/${encodeURIComponent(fn)}) (${(r.size/1024).toFixed(1)}KB)\n`;
                        } else {
                            const rs=typeof r==='object'?JSON.stringify(r,null,2):String(r);
                            stepLog+=`\n📋 Result:\n\`\`\`json\n${rs.slice(0,500)}\n\`\`\`\n`;
                        }
                        mc.innerHTML=fmt(stepLog);mc.querySelectorAll('pre code').forEach(b=>{if(!b.dataset.hl){hljs.highlightElement(b);b.dataset.hl='1'}});a.scrollTop=a.scrollHeight}
                    if(d.type==='agent_complete'){
                        stepLog+=`\n---\n## ✅ Task Complete\n${d.summary}\n`;
                        if(d.memory?.findings?.length){stepLog+='\n**Findings:**\n';d.memory.findings.forEach(f=>stepLog+=`- ${f.content}\n`)}
                        if(d.memory?.files_created?.length){stepLog+='\n**Files Created:**\n';d.memory.files_created.forEach(f=>stepLog+=`- ${f}\n`)}
                        mc.innerHTML=fmt(stepLog);mc.dataset.raw=btoa(unescape(encodeURIComponent(stepLog)));
                        mc.querySelectorAll('pre code').forEach(b=>{if(!b.dataset.hl){hljs.highlightElement(b);b.dataset.hl='1'}});
                        div.querySelector('.meta').innerHTML=`<span>${new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}</span><span>${d.memory?.steps?.length||0} steps</span><div class="msg-actions"><button class="ma" onclick="copyMsg(this)">Copy</button><button class="ma" onclick="saveMsg(this)">Save</button></div>`;
                        a.scrollTop=a.scrollHeight;await loadChats();loadMem()}
                    if(d.type==='agent_error'){stepLog+=`\n⚠ Error: ${d.error}\n`;mc.innerHTML=fmt(stepLog)}
                }catch(e){}}
        }
    }catch(e){mc.innerHTML='<span style="color:var(--y)">⚠ Agent connection error</span>'}
    document.getElementById('tb').style.display='none';document.getElementById('tb').textContent='⚡ Atherix Red is thinking...';document.getElementById('sb').disabled=false;document.getElementById('ci').focus()}

// Override send to check agent mode and smart mode
const _origSend=send;
send=async function(){
    const input=document.getElementById('ci');
    const msg=input.value.trim();
    const filesForMsg=[...pendingFiles];
    
    // Agent mode takes priority
    if(agentMode&&(msg||pendingFiles.length)){input.value='';input.style.height='auto';pendingFiles=[];document.getElementById('fileQueue').innerHTML='';await runAgent(msg||'Analyze the attached file(s)');return}
    
    // Smart mode
    if(smartMode&&msg){
        input.value='';input.style.height='auto';
        pendingFiles=[];document.getElementById('fileQueue').innerHTML='';
        await sendSmart(msg,filesForMsg);
        return;
    }
    
    // Fallback: raw streaming
    await _origSend();
}

// Search in current chat
function searchInChat(query){
    const msgs=document.querySelectorAll('.msg .mc');
    if(!query){msgs.forEach(m=>{m.style.opacity='1';m.style.border=''});return}
    const q=query.toLowerCase();
    msgs.forEach(m=>{
        const raw=m.dataset.raw?decodeURIComponent(escape(atob(m.dataset.raw))):'';
        const text=(raw||m.textContent).toLowerCase();
        if(text.includes(q)){m.style.opacity='1';m.style.border='1px solid var(--a)';m.scrollIntoView({behavior:'smooth',block:'nearest'})}
        else{m.style.opacity='0.3';m.style.border=''}
    })
}

// Edit message — click to edit a user message and regenerate from there
function addEditHandler(div,content){
    if(div.classList.contains('user')){
        const mc=div.querySelector('.mc');
        mc.addEventListener('dblclick',()=>{
            const raw=mc.dataset.raw?decodeURIComponent(escape(atob(mc.dataset.raw))):mc.textContent;
            document.getElementById('ci').value=raw;
            document.getElementById('ci').focus();
            toast('Message loaded for editing — press Enter to resend');
        });
        mc.title='Double-click to edit';
        mc.style.cursor='pointer';
    }
}

// Update chat title in header when loading a chat
const _origLoadChat=loadChat;
loadChat=async function(id){
    await _origLoadChat(id);
    const chat=chats.find(c=>c.id===id);
    if(chat)document.getElementById('chatTitle').textContent=chat.title;
    // Add edit handlers to loaded messages
    document.querySelectorAll('.msg.user').forEach(m=>{
        const mc=m.querySelector('.mc');
        if(mc){mc.title='Double-click to edit';mc.style.cursor='pointer';
            mc.addEventListener('dblclick',()=>{
                const raw=mc.dataset.raw?decodeURIComponent(escape(atob(mc.dataset.raw))):mc.textContent;
                document.getElementById('ci').value=raw;
                document.getElementById('ci').focus();
                toast('Message loaded — press Enter to resend')})
        }
    });
}

// ===== CODE PANEL =====
let panelTabs=[];let panelActive=0;

function openPanel(code,lang,title){
    // Check if this code already exists as a tab
    const existing=panelTabs.findIndex(t=>t.code===code);
    if(existing>=0){panelActive=existing;renderPanelTabs();document.getElementById('codePanel').classList.add('open');return;}
    
    panelTabs.push({code,lang:lang||'',title:title||`Block ${panelTabs.length+1}`});
    panelActive=panelTabs.length-1;
    renderPanelTabs();
    document.getElementById('codePanel').classList.add('open');
}

function renderPanelTabs(){
    const tab=panelTabs[panelActive];
    if(!tab)return;
    
    // Update editor
    document.getElementById('cpCode').value=tab.code;
    document.getElementById('cpLang').textContent=tab.lang||'code';
    document.getElementById('cpTitle').textContent=tab.title;
    
    // Show/hide preview button for HTML
    const isHtml=tab.lang==='html'||tab.lang==='css';
    document.getElementById('cpPreviewBtn').style.display=isHtml?'':'none';
    document.getElementById('cpRunBtn').style.display=isHtml?'none':'';
    
    // Tabs
    const el=document.getElementById('cpTabs');
    el.innerHTML=panelTabs.map((t,i)=>`<div class="cp-tab ${i===panelActive?'active':''}" onclick="switchTab(${i})">${esc(t.title)}</div>`).join('');
    el.style.display=panelTabs.length>1?'flex':'none';
    
    // Reset output
    document.getElementById('cpOutput').style.display='none';
    document.getElementById('cpPreviewFrame').style.display='none';
    document.getElementById('cpStatus').textContent='';
}

function switchTab(i){panelActive=i;renderPanelTabs();}

function closePanel(){
    document.getElementById('codePanel').classList.remove('open');
}

function handleTabKey(e){
    if(e.key==='Tab'){
        e.preventDefault();
        const ta=e.target,start=ta.selectionStart,end=ta.selectionEnd;
        ta.value=ta.value.substring(0,start)+'    '+ta.value.substring(end);
        ta.selectionStart=ta.selectionEnd=start+4;
    }
}

async function runCode(){
    const code=document.getElementById('cpCode').value;
    const lang=panelTabs[panelActive]?.lang||'python';
    const status=document.getElementById('cpStatus');
    status.textContent='Running...';
    
    const out=document.getElementById('cpOutput');
    const body=document.getElementById('cpOutBody');
    const frame=document.getElementById('cpPreviewFrame');
    
    out.style.display='none';frame.style.display='none';
    
    try{
        const r=await(await fetch('/api/run_code',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code,language:lang})})).json();
        
        if(r.preview){
            frame.style.display='block';
            frame.srcdoc=code;
            status.textContent='Preview rendered';
        } else {
            out.style.display='block';
            const hasErr=r.exit_code!==0||r.error;
            body.className='cp-out-body'+(hasErr?' err':'');
            let txt='';
            if(r.output)txt+=r.output;
            if(r.error)txt+=(txt?'\n\nSTDERR:\n':'')+r.error;
            body.textContent=txt||'(no output)';
            status.textContent=r.exit_code===0?'✓ Ran successfully':'✗ Error (exit '+r.exit_code+')';
            status.style.color=r.exit_code===0?'var(--g)':'#e74c3c';
        }
    }catch(e){
        out.style.display='block';
        document.getElementById('cpOutBody').textContent='Connection error: '+e.message;
        status.textContent='Failed';
    }
}

async function previewCode(){
    const code=document.getElementById('cpCode').value;
    const frame=document.getElementById('cpPreviewFrame');
    document.getElementById('cpOutput').style.display='none';
    frame.style.display='block';
    frame.srcdoc=code;
    document.getElementById('cpStatus').textContent='Preview rendered';
}

function copyPanel(){
    navigator.clipboard.writeText(document.getElementById('cpCode').value);
    document.getElementById('cpStatus').textContent='Copied!';
    setTimeout(()=>document.getElementById('cpStatus').textContent='',2000);
}

async function savePanel(){
    const code=document.getElementById('cpCode').value;
    const lang=panelTabs[panelActive]?.lang||'';
    const ext={python:'.py',py:'.py',bash:'.sh',sh:'.sh',javascript:'.js',js:'.js',html:'.html',css:'.css',c:'.c',cpp:'.cpp',php:'.php',sql:'.sql',powershell:'.ps1','':'.txt'};
    const fn=`atherix_code_${Date.now()}${ext[lang]||'.txt'}`;
    await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:code,filename:fn})});
    document.getElementById('cpStatus').textContent=`Saved as ${fn}`;
    setTimeout(()=>document.getElementById('cpStatus').textContent='',3000);
}

// Resize handle
let resizing=false,startX=0,startW=0;
document.getElementById('cpResize').addEventListener('mousedown',e=>{
    resizing=true;startX=e.clientX;startW=document.getElementById('codePanel').offsetWidth;
    e.preventDefault();
});
document.addEventListener('mousemove',e=>{
    if(!resizing)return;
    const newW=Math.max(380,Math.min(900,startW+(startX-e.clientX)));
    document.getElementById('codePanel').style.width=newW+'px';
});
document.addEventListener('mouseup',()=>resizing=false);

// Override cc and sc to also open panel
const _origCc=cc;cc=function(b){
    _origCc(b);
    const code=b.closest('pre').querySelector('code').textContent;
    const lang=b.closest('pre').querySelector('code').className.replace('language-','');
    openPanel(code,lang,'Copied Block');
}

// Override fmt's Open button injection — add "Open" button to code blocks
const _origFmt=fmt;
fmt=function(text){
    let result=_origFmt(text);
    // Add "Open" button to each code block's action bar
    result=result.replace(/<div class="cda">(<button class="cab" onclick="cc[^"]*">Copy<\/button>)/g,
        '<div class="cda"><button class="cab" onclick="openFromBlock(this)">Open</button>$1');
    return result;
}

function openFromBlock(btn){
    const pre=btn.closest('pre');
    const codeEl=pre.querySelector('code');
    const code=codeEl.textContent;
    const lang=codeEl.className.replace('language-','').trim()||'code';
    openPanel(code,lang,lang+' block');
}

loadChats();loadMem();checkStatus();setInterval(loadMem,10000);setInterval(checkStatus,15000);

// ============================================================
// PRACTICE ENGINE
// ============================================================
let practiceActiveTab='chats';
let selectedLabKey=null, selectedChallenge=null, activePracticeAbort=false;

function switchTab(tab){
    practiceActiveTab=tab;
    document.getElementById('tabChats').classList.toggle('active',tab==='chats');
    document.getElementById('tabPractice').classList.toggle('active',tab==='practice');
    const chatEls=['chatArea','ia','tb','dropOverlay'];
    chatEls.forEach(id=>{const el=document.getElementById(id);if(el)el.style.display=tab==='chats'?'':'none'});
    const pp=document.getElementById('practicePanel');
    if(pp)pp.style.display=tab==='practice'?'flex':'none';
    if(tab==='practice'){loadPracticeData()}
}

async function loadPracticeData(){
    const [prog,labs,history]=await Promise.all([
        fetch('/api/progression').then(r=>r.json()),
        fetch('/api/practice/labs').then(r=>r.json()),
        fetch('/api/practice/history?limit=10').then(r=>r.json()),
    ]);
    renderProgression(prog);
    renderLabGrid(labs);
    renderSessionHistory(history);
}

const SKILL_COLORS={web_app:'#e63946',network:'#3498db',linux_privesc:'#2ecc71',windows_privesc:'#9b59b6',active_directory:'#f39c12',recon:'#1abc9c',crypto_passwords:'#e67e22'};

function renderProgression(prog){
    document.getElementById('prRank').textContent=prog.overall_rank||'Civilian';
    document.getElementById('prSessions').textContent=`${prog.total_sessions||0} sessions · ${prog.total_challenges||0} challenges`;
    const sb=document.getElementById('skillBars');
    if(!sb)return;
    sb.innerHTML='';
    const domains=prog.domains||{};
    Object.entries(domains).forEach(([key,d])=>{
        const color=SKILL_COLORS[key]||'#888';
        sb.innerHTML+=`<div class="skill-bar-row">
            <span class="skill-bar-icon">${d.icon}</span>
            <div class="skill-bar-info">
                <div class="skill-bar-label"><span>${d.name}</span><span style="color:${color}">Lv${d.level} ${d.title}</span></div>
                <div class="skill-bar-track"><div class="skill-bar-fill" style="width:${d.percent}%;background:${color}"></div></div>
            </div>
        </div>`;
    });
}

function renderLabGrid(labs){
    const g=document.getElementById('labGrid');
    if(!g)return;
    g.innerHTML='';
    labs.forEach(lab=>{
        const runBadge=lab.running?'<span class="lab-running">● RUNNING</span>':'';
        const ccount=lab.challenges?lab.challenges.length:0;
        const xpSum=lab.challenges?lab.challenges.reduce((a,c)=>a+(c.xp||0),0):0;
        g.innerHTML+=`<div class="lab-card" onclick="openLabModal(${JSON.stringify(lab).replace(/"/g,'&quot;')})">
            <div class="lab-name">${lab.name}</div>
            <div class="lab-desc">${lab.description||''}</div>
            <div class="lab-meta">${runBadge}<span>${ccount} challenges</span><span>~${xpSum} XP total</span></div>
        </div>`;
    });
}

function renderSessionHistory(sessions){
    const el=document.getElementById('sessionHistory');
    if(!el)return;
    if(!sessions.length){el.innerHTML='<div style="color:var(--t3);font-size:11px;padding:8px">No sessions yet</div>';return}
    el.innerHTML='';
    sessions.forEach(s=>{
        const score=s.score||{};
        const status=score.successfully_exploited?'<span style="color:var(--g)">✓ Exploited</span>':score.found_vulnerability?'<span style="color:#f39c12">~ Found</span>':'<span style="color:var(--t3)">✗ Missed</span>';
        el.innerHTML+=`<div class="session-row"><div><div class="sr-label">${s.challenge} <span style="color:var(--t3);font-weight:400">in</span> ${s.lab_key}</div><div class="sr-meta">${score.step_count||0} steps · ${score.efficiency_rating||''} · +${score.xp_earned||0} XP</div></div>${status}</div>`;
    });
}

let _lmLab=null;
function openLabModal(lab){
    _lmLab=lab;
    selectedChallenge=null;
    document.getElementById('lmName').textContent=lab.name;
    document.getElementById('lmDesc').textContent=lab.description||'';
    const cl=document.getElementById('lmChallenges');
    cl.innerHTML='';
    (lab.challenges||[]).forEach(c=>{
        const diffClass='chal-diff-'+(c.difficulty||'medium');
        cl.innerHTML+=`<div class="chal-row" onclick="selectChallenge(this,'${c.name.replace(/'/g,"\\'")}')">
            <div style="display:flex;justify-content:space-between;align-items:center">
                <span style="font-size:12px;color:var(--t1)">${c.name}</span>
                <span class="${diffClass}" style="font-size:10px;font-weight:700">${(c.difficulty||'').toUpperCase()}</span>
            </div>
            <div style="font-size:10px;color:var(--t3);margin-top:3px">${c.skill||''} · ${c.xp||0} XP</div>
        </div>`;
    });
    document.getElementById('labModal').classList.add('active');
}

function selectChallenge(el,name){
    document.querySelectorAll('.chal-row').forEach(r=>r.classList.remove('selected'));
    el.classList.add('selected');
    selectedChallenge=name;
    selectedLabKey=_lmLab?_lmLab.key:null;
}

async function startPracticeSession(){
    if(!selectedLabKey||!selectedChallenge){alert('Select a challenge first');return}
    document.getElementById('labModal').classList.remove('active');
    activePracticeAbort=false;
    window._practiceCompleted=false; // Reset completion dedup flag
    showPracticeFeed(selectedLabKey,selectedChallenge);

    const resp=await fetch('/api/practice/run',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({lab_key:selectedLabKey,challenge:selectedChallenge})});
    const reader=resp.body.getReader();const dec=new TextDecoder();
    let buf='';
    while(true){
        const {done,value}=await reader.read();
        if(done||activePracticeAbort)break;
        buf+=dec.decode(value,{stream:true});
        const lines=buf.split('\n\n');buf=lines.pop();
        for(const line of lines){
            if(!line.startsWith('data:'))continue;
            try{handlePracticeEvent(JSON.parse(line.slice(5).trim()))}catch(e){}
        }
    }
}

let pfStepCount=0;
function showPracticeFeed(labKey,challenge){
    pfStepCount=0;
    document.getElementById('pfTitle').textContent=`${challenge} · ${labKey}`;
    document.getElementById('pfStep').textContent='Starting...';
    document.getElementById('pfBar').style.width='0%';
    document.getElementById('pfLog').innerHTML='';
    document.getElementById('practiceFeed').style.display='flex';
}

function handlePracticeEvent(ev){
    const log=document.getElementById('pfLog');
    const type=ev.type||'';
    if(type==='agent_thinking'){
        pfStepCount++;
        document.getElementById('pfStep').textContent=`Step ${pfStepCount}`;
        document.getElementById('pfBar').style.width=Math.min(95,pfStepCount*4)+'%';
    }else if(type==='agent_executing'){
        log.innerHTML+=`<div class="pf-think">💭 ${escHtml(ev.think||'Analyzing...')}</div>`;
        log.innerHTML+=`<div class="pf-act">🔧 ${escHtml(ev.tool||'')}(${escHtml(JSON.stringify(ev.args||{}).slice(0,120))})</div>`;
    }else if(type==='agent_step'){
        const r=ev.result||{};const rs=typeof r==='object'?JSON.stringify(r,null,2):String(r);
        log.innerHTML+=`<div class="pf-result">${escHtml(rs.slice(0,400))}</div>`;
    }else if(type==='session_complete'||type==='practice_done'){
        if(window._practiceCompleted)return; // Prevent double-fire
        window._practiceCompleted=true;
        document.getElementById('pfBar').style.width='100%';
        const score=ev.score||{};
        log.innerHTML+=`<div style="margin-top:12px;padding:12px;background:var(--b2);border-radius:8px;border:1px solid var(--g)">
            <div style="color:var(--g);font-weight:700;font-size:13px;margin-bottom:8px">✅ SESSION COMPLETE</div>
            <div style="font-size:11px;color:var(--t2);display:grid;grid-template-columns:1fr 1fr;gap:4px">
                <span>Vulnerability found: <b style="color:${score.found_vulnerability?'var(--g)':'var(--a)'};">${score.found_vulnerability?'Yes':'No'}</b></span>
                <span>Exploited: <b style="color:${score.successfully_exploited?'var(--g)':'var(--a)'};">${score.successfully_exploited?'Yes':'No'}</b></span>
                <span>Steps: <b style="color:var(--t1)">${score.step_count||0}</b></span>
                <span>Efficiency: <b style="color:var(--t1)">${score.efficiency_rating||''}</b></span>
                <span>XP earned: <b style="color:var(--a)">+${score.xp_earned||0}</b></span>
            </div>
        </div>`;
        setTimeout(()=>{
            document.getElementById('practiceFeed').style.display='none';
            showXpOverlay(score,(ev.new_achievements||[]));
            loadPracticeData();
        },2000);
    }
    log.scrollTop=log.scrollHeight;
}

function abortPractice(){
    activePracticeAbort=true;
    document.getElementById('practiceFeed').style.display='none';
}

function showXpOverlay(score,achievements){
    if(!score||!score.xp_earned)return;
    document.getElementById('xpAmount').textContent=`+${score.xp_earned} XP`;
    document.getElementById('xpDomain').textContent=score.skill_domain||'';
    const lu=document.getElementById('xpLevelUp');
    if(score.leveled_up){lu.textContent=`🎉 Level Up! → Lv${score.new_level} ${score.new_title}`;lu.style.display=''}
    else{lu.style.display='none'}
    document.getElementById('xpIcon').textContent=score.leveled_up?'🏆':'⚡';
    const ov=document.getElementById('xpOverlay');
    ov.style.display='block';
    setTimeout(()=>{ov.style.display='none'},3000);
    achievements.forEach(a=>{setTimeout(()=>{toast(`🏅 Achievement: ${a.name} — ${a.description}`)},3200)});
}

function escHtml(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
</script>
</body></html>
"""

# ============================================================
# PWNAGOTCHI PERSONALITY — always getting smarter
# Background thread runs every 24h: learns new techniques,
# checks for new CVEs, discovers GitHub labs, verifies knowledge.
# The AI doesn't wait to be asked — it's always curious.
# ============================================================

CURIOSITY_STATE_FILE = os.path.join(BASE_DIR, "curiosity_state.json")

def _load_curiosity_state() -> dict:
    if os.path.exists(CURIOSITY_STATE_FILE):
        try:
            with open(CURIOSITY_STATE_FILE, "r") as f: return json.load(f)
        except Exception: pass
    return {"last_run": None, "topics_learned": [], "new_labs_found": [], "run_count": 0}

def _save_curiosity_state(state: dict):
    state["last_updated"] = datetime.now().isoformat()
    try:
        with open(CURIOSITY_STATE_FILE, "w") as f: json.dump(state, f, indent=2)
    except Exception: pass

CURIOSITY_TOPICS = [
    # ---- CYBERSECURITY (core domain) ----
    "latest web application vulnerabilities 2026",
    "new privilege escalation techniques linux 2026",
    "active directory attack techniques 2026",
    "new critical CVEs this week",
    "latest penetration testing tools 2026",
    "OWASP top 10 vulnerabilities 2026",
    "cloud security misconfigurations AWS GCP Azure 2026",
    "API security vulnerabilities REST GraphQL 2026",
    "container escape techniques docker kubernetes 2026",
    "new exploit techniques 2026",
    "zero day vulnerabilities disclosed 2026",
    "new malware techniques threat intelligence 2026",
    "Windows privilege escalation new techniques 2026",
    # ---- CODING & SOFTWARE ENGINEERING ----
    "latest Python features and best practices 2026",
    "new JavaScript frameworks and libraries 2026",
    "Rust programming language latest features 2026",
    "best practices API design REST GraphQL 2026",
    "latest Docker Kubernetes container best practices 2026",
    "new database technologies and query optimization 2026",
    "machine learning libraries latest releases 2026",
    "latest web development frameworks performance 2026",
    "Git advanced workflows and best practices 2026",
    "latest IDE tools developer productivity 2026",
    "CI/CD pipeline best practices GitHub Actions 2026",
    "microservices architecture patterns 2026",
    "WebAssembly WASM latest developments 2026",
    "latest TypeScript features and patterns 2026",
    "systems programming low level optimization 2026",
    # ---- AI & MACHINE LEARNING ----
    "latest large language model developments 2026",
    "new AI tools and frameworks 2026",
    "AI image generation latest models techniques 2026",
    "AI video generation latest research 2026",
    "reinforcement learning latest breakthroughs 2026",
    "edge AI local inference optimization 2026",
    "AI model fine tuning techniques 2026",
    "multimodal AI models latest developments 2026",
    # ---- SCIENCE & ENGINEERING ----
    "latest physics discoveries and research 2026",
    "new biotechnology breakthroughs 2026",
    "latest space exploration discoveries 2026",
    "quantum computing latest developments 2026",
    "new materials science discoveries 2026",
    "latest neuroscience brain research 2026",
    "robotics latest advances 2026",
    "renewable energy technology breakthroughs 2026",
    "latest medical research drug discovery 2026",
    "CRISPR gene editing latest developments 2026",
    # ---- MUSIC & CREATIVE ----
    "music production latest tools and techniques 2026",
    "AI music generation latest models 2026",
    "audio engineering and mixing best practices 2026",
    "latest music theory and composition techniques",
    "digital art tools latest features 2026",
    # ---- BUSINESS & ENTREPRENEURSHIP ----
    "latest startup strategies and business models 2026",
    "small business automation tools 2026",
    "latest marketing strategies digital 2026",
    "SaaS pricing models and strategies 2026",
]

def _run_curiosity_cycle(state: dict):
    """One curiosity cycle: verify 4 topics + discover new GitHub labs."""
    import random, time as _time
    try:
        from knowledge_verifier import verify_and_store
    except ImportError:
        print("[Curiosity] knowledge_verifier not available"); return

    print(f"[Curiosity] Daily learning cycle #{state.get('run_count', 0) + 1} starting")
    topics = CURIOSITY_TOPICS.copy()
    random.shuffle(topics)
    learned = []

    for topic in topics[:6]:
        try:
            result = verify_and_store(topic)
            verdict = result.get("verdict", "UNVERIFIED")
            conf = result.get("confidence", 0)
            learned.append({"topic": topic, "verdict": verdict, "confidence": conf,
                           "timestamp": datetime.now().isoformat()})
            print(f"[Curiosity] {'✓' if verdict == 'VERIFIED' else '~'} {topic[:60]} ({verdict}, {conf}%)")
        except Exception as e:
            print(f"[Curiosity] Error: {topic[:40]} — {e}")
        _time.sleep(2)

    # GitHub lab discovery
    try:
        from lab_manager import discover_new_labs
        new_labs = discover_new_labs()
        if new_labs:
            state["new_labs_found"] = (state.get("new_labs_found", []) + new_labs)[-20:]
            print(f"[Curiosity] Found {len(new_labs)} potential new labs")
    except Exception as e:
        print(f"[Curiosity] Lab discovery error: {e}")

    state["topics_learned"] = (state.get("topics_learned", []) + learned)[-100:]
    print(f"[Curiosity] Cycle complete — {len(learned)} topics learned")

def _curiosity_loop():
    """Background daemon: runs daily learning cycle every 24 hours."""
    import time as _time
    _time.sleep(90)  # Wait for app to fully initialize
    while True:
        state = _load_curiosity_state()
        last_run = state.get("last_run")
        should_run = True
        if last_run:
            try:
                from datetime import timedelta
                elapsed = (datetime.now() - datetime.fromisoformat(last_run)).total_seconds()
                should_run = elapsed > 86400
            except Exception: pass
        if should_run:
            try:
                from autonomous_curiosity import run_autonomous_curiosity_cycle
                run_autonomous_curiosity_cycle(state, CURIOSITY_TOPICS)
            except Exception as e: print(f"[Curiosity] Loop error: {e}")
            state["last_run"] = datetime.now().isoformat()
            state["run_count"] = state.get("run_count", 0) + 1
            _save_curiosity_state(state)
        _time.sleep(3600)  # Check every hour, run every 24h

@app.route("/api/curiosity/state")
def curiosity_state_ep():
    state = _load_curiosity_state()
    return jsonify({
        "last_run": state.get("last_run"),
        "run_count": state.get("run_count", 0),
        "topics_learned_total": len(state.get("topics_learned", [])),
        "recent_topics": state.get("topics_learned", [])[-8:],
        "new_labs_found": len(state.get("new_labs_found", [])),
    })

@app.route("/api/curiosity/trigger", methods=["POST"])
def curiosity_trigger_ep():
    """Manually trigger a learning cycle right now."""
    def _run():
        from autonomous_curiosity import run_autonomous_curiosity_cycle
        state = _load_curiosity_state()
        run_autonomous_curiosity_cycle(state, CURIOSITY_TOPICS)
        state["last_run"] = datetime.now().isoformat()
        state["run_count"] = state.get("run_count", 0) + 1
        _save_curiosity_state(state)
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "message": "Learning cycle triggered"})

# ============================================================
# LAUNCH
# ============================================================
def start_flask():
    app.run(port=5199,debug=False,use_reloader=False)

if __name__=="__main__":
    t=threading.Thread(target=start_flask,daemon=True);t.start()
    # Start Pwnagotchi curiosity loop in background
    threading.Thread(target=_curiosity_loop, daemon=True).start()
    import time;time.sleep(1)
    webview.create_window("Atherix Red v3.0","http://localhost:5199",width=1300,height=850,min_size=(1000,650),background_color="#08080d")
    webview.start()