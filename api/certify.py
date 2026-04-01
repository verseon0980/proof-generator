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
            "scores": {"overall": 70, "novelty": 70, "market_gap": 70, "technical": 70, "prior_art_risk": 30},
            "analysis": (raw or "")[:500] or "Analysis unavailable.",
            "similar": []
        }


async def _infer(idea: str, author: str) -> dict:
    llm = og.LLM(private_key=PRIVATE_KEY)
    llm.ensure_opg_approval(opg_amount=1.0)

    messages = [
        {
            "role": "user",
            "content": f"""You are an AI that evaluates the originality of ideas.

Idea: \"\"\"{idea}\"\"\"

Return ONLY valid JSON, no markdown, no extra text:
{{
  "title": "<short 5-8 word title>",
  "scores": {{
    "overall": <integer 0-100>,
    "novelty": <integer 0-100>,
    "market_gap": <integer 0-100>,
    "technical": <integer 0-100>,
    "prior_art_risk": <integer 0-100>
  }},
  "analysis": "<2-3 sentence analysis>",
  "similar": [
    {{
      "name": "<similar product>",
      "difference": "<one sentence>",
      "risk": "low"
    }}
  ]
}}"""
        }
    ]

    result = await llm.chat(
        model=og.TEE_LLM.GEMINI_2_5_FLASH,
        messages=messages,
        max_tokens=600,
        x402_settlement_mode=og.x402SettlementMode.INDIVIDUAL_FULL,
    )

    raw = result.chat_output.get("content", "") if result.chat_output else ""
    parsed = parse_ai_response(raw)

    # ============================================================
    # DUMP EVERYTHING — check Vercel function logs after deploying
    # ============================================================
    print("=== RESULT TYPE ===", type(result).__name__)
    try:
        print("=== RESULT __dict__ ===", result.__dict__)
    except:
        pass
    for attr in dir(result):
        if attr.startswith("_"):
            continue
        try:
            val = getattr(result, attr)
            if not callable(val):
                print(f"  result.{attr} = {repr(val)}")
        except Exception as e:
            print(f"  result.{attr} ERROR: {e}")
    # ============================================================

    # Find whichever field has a real 0x... hash
    tx_hash = ""
    for field in ["transaction_hash", "payment_hash", "tx_hash", "hash", "receipt_hash", "settlement_hash"]:
        val = getattr(result, field, None)
        if val and isinstance(val, str) and val.startswith("0x") and len(val) > 20:
            tx_hash = val
            print(f"=== FOUND HASH in result.{field} = {val} ===")
            break

    explorer_url = f"https://sepolia.basescan.org/tx/{tx_hash}" if tx_hash else None

    return {
        "cert_id": generate_cert_id(),
        "author": author,
        "idea": idea,
        "idea_hash": hash_idea(idea),
        "timestamp": datetime.datetime.utcnow().strftime("%B %d, %Y · %H:%M UTC"),
        "transaction_hash": tx_hash,
        "explorer_url": explorer_url,
        "title": parsed.get("title", "Idea certificate"),
        "scores": parsed.get("scores", {"overall": 70, "novelty": 70, "market_gap": 70, "technical": 70, "prior_art_risk": 30}),
        "analysis": parsed.get("analysis", ""),
        "similar": parsed.get("similar", [])
    }


def run_inference(idea: str, author: str) -> dict:
    out = {}
    err = {}

    def target():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            out['data'] = loop.run_until_complete(_infer(idea, author))
        except Exception as e:
            err['e'] = str(e)
        finally:
            loop.close()

    t = threading.Thread(target=target)
    t.start()
    t.join()

    if 'e' in err:
        raise RuntimeError(err['e'])
    return out['data']


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
                self._error(400, "Author name is required.")
                return
            if not PRIVATE_KEY:
                self._error(500, "Missing OG_PRIVATE_KEY environment variable.")
                return

            self._json(200, run_inference(idea, author))

        except Exception as e:
            self._error(500, str(e))

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
