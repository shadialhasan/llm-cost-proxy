# -*- coding: utf-8 -*-
"""
LLM Token Cost & Quota Monitoring Proxy
Author: Eng. MHD. Shadi AL-Hasan <mhd.shadi.alhasan@gmail.com>
Phone: +963934005922
Copyright (c) 2026 MHD. Shadi AL-Hasan
"""

import os
import time
import json
from http.server import HTTPServer, BaseHTTPRequestHandler

# Standard Pricing per 1M tokens (USD)
PRICING_TABLE = {
    "gpt-4o": {"prompt": 2.50, "completion": 10.00},
    "gpt-4o-mini": {"prompt": 0.15, "completion": 0.60},
    "claude-3-5-sonnet": {"prompt": 3.00, "completion": 15.00},
    "claude-3-haiku": {"prompt": 0.25, "completion": 1.25},
    "gemini-1.5-pro": {"prompt": 1.25, "completion": 5.00},
    "gemini-1.5-flash": {"prompt": 0.075, "completion": 0.30},
}

# Rate Limiting Presets (RPM: Requests Per Minute, TPM: Tokens Per Minute)
RATE_LIMIT_PRESETS = {
    "strict": {"rpm": 20, "tpm": 20_000},
    "standard": {"rpm": 60, "tpm": 100_000},
    "relaxed": {"rpm": 120, "tpm": 500_000},
}

# Production Security Headers
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cache-Control": "no-store, no-cache, must-revalidate",
}

TOTAL_TOKENS_LOGGED = 0
TOTAL_COST_USD = 0.0


def calculate_tokens(text: str) -> int:
    """Approximates token count based on standard ~4 characters per token heuristic."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def get_pricing(model: str) -> dict:
    """Retrieves pricing specification for a model with default fallback."""
    return PRICING_TABLE.get(model, PRICING_TABLE.get("gpt-4o", {"prompt": 2.50, "completion": 10.00}))


def calculate_cost(prompt_tokens: int, completion_tokens: int, model: str) -> float:
    """Calculates total estimated cost in USD for given token arithmetic."""
    pricing = get_pricing(model)
    prompt_cost = (prompt_tokens / 1_000_000) * pricing["prompt"]
    completion_cost = (completion_tokens / 1_000_000) * pricing["completion"]
    return prompt_cost + completion_cost


class TokenRateLimiter:
    """Sliding-window in-memory rate limiter tracking RPM and TPM."""

    def __init__(self, preset: str = "standard", window_seconds: float = 60.0):
        preset_config = RATE_LIMIT_PRESETS.get(preset, RATE_LIMIT_PRESETS["standard"])
        self.rpm_limit = preset_config["rpm"]
        self.tpm_limit = preset_config["tpm"]
        self.window_seconds = window_seconds
        self.clients = {}  # ip -> {"requests": [timestamp, ...], "tokens": [(timestamp, token_count), ...]}

    def check_and_record(self, client_ip: str, tokens: int = 0) -> tuple[bool, str, dict]:
        now = time.time()
        cutoff = now - self.window_seconds

        client_data = self.clients.setdefault(client_ip, {"requests": [], "tokens": []})
        # Evict expired events
        client_data["requests"] = [t for t in client_data["requests"] if t > cutoff]
        client_data["tokens"] = [entry for entry in client_data["tokens"] if entry[0] > cutoff]

        current_rpm = len(client_data["requests"])
        current_tpm = sum(entry[1] for entry in client_data["tokens"])

        if current_rpm >= self.rpm_limit:
            return False, f"RPM limit exceeded ({self.rpm_limit} req/min)", {
                "limit_rpm": self.rpm_limit,
                "current_rpm": current_rpm,
                "retry_after": max(1, int(self.window_seconds - (now - client_data["requests"][0])))
            }

        if (current_tpm + tokens) > self.tpm_limit:
            return False, f"TPM limit exceeded ({self.tpm_limit} tokens/min)", {
                "limit_tpm": self.tpm_limit,
                "current_tpm": current_tpm,
                "retry_after": max(1, int(self.window_seconds - (now - client_data["tokens"][0][0])))
            }

        # Record activity
        client_data["requests"].append(now)
        client_data["tokens"].append((now, tokens))

        remaining_rpm = max(0, self.rpm_limit - (current_rpm + 1))
        return True, "", {"limit_rpm": self.rpm_limit, "remaining_rpm": remaining_rpm}


# Global rate limiter instance configured from environment
ACTIVE_PRESET = os.getenv("RATE_LIMIT_PRESET", "standard")
RATE_LIMITER = TokenRateLimiter(preset=ACTIVE_PRESET)
BUDGET_CAP_USD = float(os.getenv("BUDGET_CAP_USD", "0.0"))


class ProxyHandler(BaseHTTPRequestHandler):
    def apply_security_headers(self):
        for header, value in SECURITY_HEADERS.items():
            self.send_header(header, value)

    def do_GET(self):
        """Health check and metric query endpoint."""
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.apply_security_headers()
        self.end_headers()

        payload = {
            "status": "healthy",
            "active_preset": ACTIVE_PRESET,
            "total_tokens_logged": TOTAL_TOKENS_LOGGED,
            "total_cost_usd": round(TOTAL_COST_USD, 4),
            "supported_models": list(PRICING_TABLE.keys()),
            "author": "Eng. MHD. Shadi AL-Hasan"
        }
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def do_POST(self):
        global TOTAL_TOKENS_LOGGED, TOTAL_COST_USD
        client_ip = self.client_address[0] if self.client_address else "127.0.0.1"

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"

        try:
            data = json.loads(body)
            model = data.get("model", os.getenv("DEFAULT_MODEL", "gpt-4o"))
            messages = data.get("messages", "")

            # Serialize messages if dict/list
            if isinstance(messages, (dict, list)):
                prompt_str = json.dumps(messages)
            else:
                prompt_str = str(messages)

            prompt_tokens = calculate_tokens(prompt_str)
            completion_tokens = int(data.get("completion_tokens", 50))
            request_tokens = prompt_tokens + completion_tokens

            # Check rate limits
            allowed, limit_msg, meta = RATE_LIMITER.check_and_record(client_ip, request_tokens)
            if not allowed:
                self.send_response(429)
                self.send_header("Content-Type", "application/json")
                if "retry_after" in meta:
                    self.send_header("Retry-After", str(meta["retry_after"]))
                self.apply_security_headers()
                self.end_headers()
                self.wfile.write(json.dumps({
                    "error": "Rate limit exceeded",
                    "reason": limit_msg,
                    "metadata": meta
                }).encode("utf-8"))
                return

            # Check budget cap if configured
            if BUDGET_CAP_USD > 0.0 and TOTAL_COST_USD >= BUDGET_CAP_USD:
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.apply_security_headers()
                self.end_headers()
                self.wfile.write(json.dumps({
                    "error": "Budget quota exceeded",
                    "budget_cap_usd": BUDGET_CAP_USD,
                    "total_cost_usd": round(TOTAL_COST_USD, 4)
                }).encode("utf-8"))
                return

            cost = calculate_cost(prompt_tokens, completion_tokens, model)
            TOTAL_TOKENS_LOGGED += request_tokens
            TOTAL_COST_USD += cost

            response = {
                "status": "authorized",
                "model": model,
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": request_tokens,
                    "estimated_cost_usd": round(cost, 6)
                },
                "total_session_cost_usd": round(TOTAL_COST_USD, 4)
            }

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.apply_security_headers()
            self.end_headers()
            self.wfile.write(json.dumps(response).encode("utf-8"))
            print(f"[AUDIT] Model: {model} | Cost: ${cost:.6f} | Total: ${TOTAL_COST_USD:.4f}")

        except Exception as e:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.apply_security_headers()
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))


def run_server(port=None, host=None):
    host = host or os.getenv("HOST", "0.0.0.0")
    port = port or int(os.getenv("PORT", 8080))
    server = HTTPServer((host, port), ProxyHandler)
    print(f"[*] LLM Cost Proxy running on http://{host}:{port} [Preset: {ACTIVE_PRESET}]...")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[!] Stopping server.")


if __name__ == "__main__":
    run_server()
