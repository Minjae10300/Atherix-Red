import requests
import json

def ask_atherix(prompt, think_budget=512):
    response = requests.post("http://localhost:11434/api/chat", json={
        "model": "joe-speedboat/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive:Q4_K_M",
        "thinking": {"budget_tokens": think_budget},
        "options": {
            "num_ctx": 8192,
            "num_predict": 4096,
            "temperature": 0.7,
            "top_p": 0.95,
            "top_k": 20
        },
        "messages": [
            {
                "role": "system",
                "content": "You are Atherix Red, a penetration testing AI developed by Atherix AI Solutions. Be direct and concise. Give tool commands, payloads, and step-by-step methodology. No essays. No disclaimers."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "stream": False
    })
    
    data = response.json()
    msg = data.get("message", {})
    
    # Show thinking if present
    if msg.get("thinking"):
        print("=== THINKING ===")
        print(msg["thinking"][:500] + "..." if len(msg.get("thinking","")) > 500 else msg["thinking"])
        print()
    
    print("=== RESPONSE ===")
    print(msg.get("content", "No response"))
    
    # Stats
    if "eval_count" in data:
        print(f"\n--- Stats: {data.get('eval_count',0)} tokens | {data.get('eval_duration',0)/1e9:.1f}s ---")

# Test it
ask_atherix("what is nmap", think_budget=256)