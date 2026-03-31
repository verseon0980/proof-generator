import os
import json
import hashlib
import asyncio
import datetime
import re
import threading
from http.server import BaseHTTPRequestHandler

import opengradient as og

PRIVATE_KEY = os.environ.get("OG_PRIVATE_KEY")


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
            "analysis": (raw or "")[:500],
            "similar": []
        }


async def _infer(idea: str, author: str) -> dict:
    if not PRIVATE_KEY:
        raise RuntimeError("Missing OG_PRIVATE_KEY")

    print("=== STARTING REQUEST ===")

    # 🔹 STEP 1: APPROVAL
    llm = og.LLM(private_key=PRIVATE_KEY)

    approval = llm.ensure_opg_approval(0.1)

    print("APPROVAL RESULT:", approval)

    if not approval:
        raise RuntimeError("❌ Approval failed")

    # 🔥 STEP 2: NEW INSTANCE (IMPORTANT FIX)
    llm = og.LLM(private_key=PRIVATE_KEY)

    messages = [
        {
            "role": "user",
            "content": f"""You are an AI that evaluates the originality of ideas.

Idea: \"\"\"{idea}\"\"\"

Return ONLY valid JSON:
{{
  "title": "<short title>",
  "scores": {{
    "overall": <0-100>,
    "novelty": <0-100>,
    "market_gap": <0-100>,
    "technical": <0-100>,
    "prior_art_risk": <0-100>
  }},
  "analysis": "<short analysis>",
  "similar": []
}}"""
        }
    ]

    # 🔹 STEP 3: CHAT (FORCED PAYMENT)
    result = await llm.chat(
        model=og.TEE_LLM.GEMINI_2_5_FLASH,
        messages=messages,
        max_tokens=600,
        temperature=0.7,
        x402_settlement_mode=og.x402SettlementMode.INDIVIDUAL_FULL,
    )

    print("=== CHAT RESULT ===")
    print(result)
    print("===================")

    payment_hash = getattr(result, "payment_hash", None)

    print("PAYMENT HASH:", payment_hash)

    # 🔥 HARD BLOCK: NO TX = FAIL
    if not payment_hash or not str(payment_hash).startswith("0x"):
        raise RuntimeError(
            "❌ PAYMENT NOT EXECUTED\n"
            "No valid transaction hash.\n"
            "Check:\n"
            "1. Wallet has ETH (gas)\n"
            "2. Wallet has OPG\n"
            "3. Correct network (Base Sepolia)\n"
        )

    if not result.chat_output:
        raise RuntimeError("❌ Empty AI response")

    raw = result.chat_output.get("content", "")
    parsed = parse_ai_response(raw)

    return {
        "cert_id": generate_cert_id(),
        "author": author,
        "idea": idea,
        "idea_hash": hash_idea(idea),
        "timestamp": datetime.datetime.utcnow().strftime("%B %d, %Y · %H:%M UTC"),
        "payment_hash": payment_hash,
        "explorer_url": f"https://explorer.opengradient.ai/tx/{payment_hash}",
        "title": parsed.get("title"),
        "scores": parsed.get("scores"),
        "analysis": parsed.get("analysis"),
        "similar": parsed.get("similar", [])
    }


def run_inference(idea: str, author: str) -> dict:
    out = {}
    err = {}

    def target():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            out["data"] = loop.run_until_complete(_infer(idea, author))
        except Exception as e:
            err["e"] = str(e)
        finally:
            loop.close()

    t = threading.Thread(target=target)
    t.start()
    t.join()

    if "e" in err:
        raise RuntimeError(err["e"])

    return out["data"]


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))

            idea = (body.get("idea") or "").strip()
            author = (body.get("author") or "").strip()

            if len(idea) < 30:
                self._error(400, "Idea must be at least 30 characters.")
                return

            if not author:
                self._error(400, "Author required.")
                return

            if not PRIVATE_KEY:
                self._error(500, "Missing OG_PRIVATE_KEY.")
                return

            result = run_inference(idea, author)
            self._json(200, result)

        except Exception as e:
            self._json(500, {"error": str(e)})

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code, data):
        payload = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(payload))
        self._cors()
        self.end_headers()
        self.wfile.write(payload)

    def _error(self, code, msg):
        self._json(code, {"error": msg})

    def log_message(self, *args):
        pass
