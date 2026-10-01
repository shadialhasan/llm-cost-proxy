# -*- coding: utf-8 -*-
"""
Unit Tests for LLM Cost Proxy Token Arithmetic & Security Features
Author: Eng. MHD. Shadi AL-Hasan <mhd.shadi.alhasan@gmail.com>
"""

import unittest
import threading
import json
import urllib.request
import urllib.error
from http.server import HTTPServer

from proxy_server import (
    calculate_tokens,
    get_pricing,
    calculate_cost,
    TokenRateLimiter,
    PRICING_TABLE,
    SECURITY_HEADERS,
    ProxyHandler,
)


class TestTokenArithmetic(unittest.TestCase):
    """Test suite verifying LLM token arithmetic and pricing calculations."""

    def test_calculate_tokens_empty(self):
        self.assertEqual(calculate_tokens(""), 0)
        self.assertEqual(calculate_tokens(None), 0)

    def test_calculate_tokens_proportional(self):
        # 4 chars = 1 token
        self.assertEqual(calculate_tokens("abcd"), 1)
        # 40 chars = 10 tokens
        self.assertEqual(calculate_tokens("a" * 40), 10)
        # short non-empty string defaults to minimum 1 token
        self.assertEqual(calculate_tokens("hi"), 1)

    def test_get_pricing_known_models(self):
        gpt4o = get_pricing("gpt-4o")
        self.assertEqual(gpt4o["prompt"], 2.50)
        self.assertEqual(gpt4o["completion"], 10.00)

        claude = get_pricing("claude-3-5-sonnet")
        self.assertEqual(claude["prompt"], 3.00)
        self.assertEqual(claude["completion"], 15.00)

    def test_get_pricing_fallback(self):
        fallback = get_pricing("non-existent-model")
        # Defaults to gpt-4o pricing
        self.assertEqual(fallback["prompt"], 2.50)
        self.assertEqual(fallback["completion"], 10.00)

    def test_cost_arithmetic_exact(self):
        # 1M prompt tokens and 1M completion tokens for gpt-4o
        cost = calculate_cost(1_000_000, 1_000_000, "gpt-4o")
        self.assertAlmostEqual(cost, 12.50, places=6)

        # 1,000 prompt tokens and 50 completion tokens for gpt-4o-mini
        # Prompt: (1,000 / 1,000,000) * 0.15 = 0.00015
        # Completion: (50 / 1,000,000) * 0.60 = 0.00003
        # Total = 0.00018
        cost_mini = calculate_cost(1000, 50, "gpt-4o-mini")
        self.assertAlmostEqual(cost_mini, 0.00018, places=6)

    def test_cost_arithmetic_zero_tokens(self):
        cost = calculate_cost(0, 0, "gpt-4o")
        self.assertEqual(cost, 0.0)


class TestRateLimiter(unittest.TestCase):
    """Test suite for rate limiting presets and sliding-window logic."""

    def test_rate_limiter_rpm_enforcement(self):
        limiter = TokenRateLimiter(preset="strict", window_seconds=60.0)
        # 'strict' allows 20 RPM
        for i in range(20):
            allowed, _, meta = limiter.check_and_record("127.0.0.1", tokens=10)
            self.assertTrue(allowed, f"Request {i+1} should be allowed")

        # 21st request should be rejected
        allowed, msg, meta = limiter.check_and_record("127.0.0.1", tokens=10)
        self.assertFalse(allowed)
        self.assertIn("RPM limit exceeded", msg)
        self.assertGreater(meta["retry_after"], 0)

    def test_rate_limiter_tpm_enforcement(self):
        limiter = TokenRateLimiter(preset="strict", window_seconds=60.0)
        # 'strict' allows 20,000 TPM
        # First request consumes 15,000 tokens (allowed)
        allowed, _, _ = limiter.check_and_record("10.0.0.1", tokens=15000)
        self.assertTrue(allowed)

        # Second request attempts 6,000 tokens (15k + 6k = 21k > 20k, rejected)
        allowed, msg, _ = limiter.check_and_record("10.0.0.1", tokens=6000)
        self.assertFalse(allowed)
        self.assertIn("TPM limit exceeded", msg)

    def test_rate_limiter_distinct_ips(self):
        limiter = TokenRateLimiter(preset="strict")
        for _ in range(20):
            limiter.check_and_record("192.168.1.1", tokens=5)

        # Another IP is unaffected
        allowed, _, _ = limiter.check_and_record("192.168.1.2", tokens=5)
        self.assertTrue(allowed)


class TestSecurityHeadersAndHTTP(unittest.TestCase):
    """Test suite for security headers and HTTP server integration."""

    @classmethod
    def setUpClass(cls):
        # Run test server on ephemeral port
        cls.server = HTTPServer(("127.0.0.1", 0), ProxyHandler)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_security_headers_dict(self):
        expected_keys = [
            "X-Content-Type-Options",
            "X-Frame-Options",
            "X-XSS-Protection",
            "Strict-Transport-Security",
            "Content-Security-Policy"
        ]
        for key in expected_keys:
            self.assertIn(key, SECURITY_HEADERS)

    def test_get_health_endpoint_and_headers(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            headers = dict(resp.getheaders())
            self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
            self.assertEqual(headers.get("X-Frame-Options"), "DENY")
            self.assertIn("max-age", headers.get("Strict-Transport-Security", ""))

            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "healthy")
            self.assertIn("gpt-4o", data["supported_models"])

    def test_post_proxy_token_arithmetic(self):
        payload = json.dumps({
            "model": "gpt-4o-mini",
            "messages": "Hello world, what is quantum computing?",
            "completion_tokens": 100
        }).encode("utf-8")

        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "authorized")
            self.assertEqual(data["model"], "gpt-4o-mini")
            self.assertIn("usage", data)
            self.assertEqual(data["usage"]["completion_tokens"], 100)
            self.assertGreater(data["usage"]["prompt_tokens"], 0)
            self.assertGreater(data["usage"]["estimated_cost_usd"], 0)


if __name__ == "__main__":
    unittest.main()
