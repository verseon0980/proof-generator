import os
import json
import hashlib
import datetime
import re
import traceback
from http.server import BaseHTTPRequestHandler

import requests
from eth_account import Account
from x402v2 import x402Client
from x402v2.mechanisms.evm import EthAccountSigner
from x402v2.mechanisms.evm.exact.register import register_exact_evm_client

PRIVATE_KEY = os.environ.get("OG_PRIVATE_KEY")

TEE_URL = "https://3.15.214.21/v1/chat/completions"


def generate_cert_id():
    now = datetime.datetime.utcnow()
    rand = hashlib.sha256(str(now.timestamp()).encode()).hexdigest()[:4].upper()
    return f"PG-{now.strftime('%Y%m%d')}-{rand}"


def hash_idea(idea: str) -> str:
    return "0x" + hashlib.sha256(idea.encode()).hexdigest()


def parse_ai_response(raw: str) -> dict:
    clean = re.sub(r"```(?:json)?", "", raw or "").strip().rstrip("`").strip()
    match = re.search(r'\{.*\}', clean, re.DOTALL)
    if match:
        clean = match.group(0)
    try:
        return json.loads(clean)
    except Exception:
        return {
            "title": "Idea certificate",
            "scores": {
                "overall": 70,
                "novelty": 70,
                "market_gap": 70,
                "technical": 70,
                "prior_art_risk": 30
            },
            "analysis": (raw or "")[:500] or "Analysis unavailable.",
            "similar": []
        }


def run_inference(idea: str, author: str) -> dict:
    try:
        account = Account.from_key(PRIVATE_KEY)
        signer = EthAccountSigner(account)

        xclient = x402Client()
        register_exact_evm_client(xclient, signer)

        messages = [{
            "role": "user",
            "content": f"""You are an AI that evaluates the originality of ideas.

Idea: \"\"\"{idea}\"\"\"

Return ONLY valid JSON:
{{
  "title": "<short 5-8 word title>",
  "scores": {{
    "overall": <0-100>,
    "novelty": <0-100>,
    "market_gap": <0-100>,
    "technical": <0-100>,
    "prior_art_risk": <0-100>
  }},
  "analysis": "<2-3 sentence analysis>",
  "similar": []
}}"""
        }]

        payload = {
            "model": "gpt-4.1",
            "messages": messages,
            "max_tokens": 600,
            "temperature": 0.2
        }

        # 1️⃣ First request (will return 402)
        res = requests.post(TEE_URL, json=payload)

        if res.status_code == 402:
            # 2️⃣ Extract payment requirements
            try:
                requirements = res.json()
            except Exception:
                raise Exception("Failed to parse payment requirements from 402")

            # 3️⃣ Generate payment headers
            payment_headers = xclient.create_payment_headers(requirements)

            # 4️⃣ Retry request with payment
            res = requests.post(TEE_URL, json=payload, headers=payment_headers)

        if res.status_code != 200:
            raise Exception(f"TEE request failed: {res.text}")

        data = res.json()

        raw = ""
        if "choices" in data and len(data["choices"]) > 0:
            raw = data["choices"][0]["message"]["content"]

        parsed = parse_ai_response(raw)

        return {
            "cert_id": generate_cert_id(),
            "author": author,
            "idea": idea,
            "idea_hash": hash_idea(idea),
            "timestamp": datetime.datetime.utcnow().strftime("%B %d, %Y · %H:%M UTC"),
            "payment_hash": res.headers.get("x-payment-hash"),
            "title": parsed.get("title", "Idea certificate"),
            "scores": parsed.get("scores", {}),
            "analysis": parsed.get("analysis", ""),
            "similar": parsed.get("similar", [])
        }

    except Exception as e:
        print("FULL ERROR:\n", traceback.format_exc())
        raise


# ✅ VERCEL HANDLER (DO NOT TOUCH STRUCTURE)
class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)

            try:
                body = json.loads(raw)
            except Exception:
                self._error(400, "Invalid JSON body.")
                return

            idea = (body.get("idea") or "").strip()
            author = (body.get("author") or "").strip()

            if len(idea) < 30:
                self._error(400, "Idea must be at least 30 characters.")
                return

            if not author:
                self._error(400, "Author name is required.")
                return

            if not PRIVATE_KEY:
                self._error(500, "Missing OG_PRIVATE_KEY environment variable.")
                return

            result = run_inference(idea, author)
            self._json(200, result)

        except Exception as e:
            self._error(500, str(e))

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code, data):
        try:
            payload = json.dumps(data).encode()
        except Exception:
            payload = b'{"error":"serialization failed"}'

        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(payload))
        self._cors()
        self.end_headers()
        self.wfile.write(payload)

    def _error(self, code, msg):
        self._json(code, {"error": msg})

    def log_message(self, *args):
        return
