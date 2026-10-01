# -*- coding: utf-8 -*-
"""
LLM Token Cost & Quota Monitoring Proxy
Author: Eng. MHD. Shadi AL-Hasan <mhd.shadi.alhasan@gmail.com>
Phone: +963934005922
Copyright (c) 2026 MHD. Shadi AL-Hasan
"""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler

# Standard Pricing per 1M tokens (USD)
PRICING_TABLE = {
    "gpt-4o": {"prompt": 2.50, "completion": 10.00},
    "gpt-4o-mini": {"prompt": 0.15, "completion": 0.60},
    "claude-3-5-sonnet": {"prompt": 3.00, "completion": 15.00},
    "gemini-1.5-pro": {"prompt": 1.25, "completion": 5.00}
}

TOTAL_TOKENS_LOGGED = 0
TOTAL_COST_USD = 0.0

class ProxyHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        global TOTAL_TOKENS_LOGGED, TOTAL_COST_USD
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8')
        
        try:
            data = json.loads(body)
            model = data.get("model", "gpt-4o")
            prompt = str(data.get("messages", ""))
            
            # Simple approximation: ~4 characters per token
            prompt_tokens = max(1, len(prompt) // 4)
            completion_tokens = 50 # Default sample estimate
            
            pricing = PRICING_TABLE.get(model, PRICING_TABLE["gpt-4o"])
            cost = (prompt_tokens / 1_000_000 * pricing["prompt"]) + (completion_tokens / 1_000_000 * pricing["completion"])

            TOTAL_TOKENS_LOGGED += (prompt_tokens + completion_tokens)
            TOTAL_COST_USD += cost

            response = {
                "status": "authorized",
                "model": model,
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "estimated_cost_usd": round(cost, 6)
                },
                "total_session_cost_usd": round(TOTAL_COST_USD, 4)
            }

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode('utf-8'))
            print(f"[AUDIT] Model: {model} | Cost: ${cost:.6f} | Total: ${TOTAL_COST_USD:.4f}")

        except Exception as e:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))

def run_server(port=8080):
    server = HTTPServer(('0.0.0.0', port), ProxyHandler)
    print(f"[*] LLM Cost Proxy running on port {port}...")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[!] Stopping server.")

if __name__ == "__main__":
    run_server()
