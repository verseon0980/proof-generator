import os
import json
import hashlib
import datetime
import re
import traceback
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
            "analysis": (raw or "")[:500] or "Analysis unavailable.",
            "similar": []
        }


def run_inference(idea: str, author: str) -> dict:
    client = og.Client(private_key=PRIVATE_KEY)

    # approval (keep this)
    client.llm.ensure_opg_approval(opg_amount=1.0)

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

    # 🔴 DEBUG + LLM CALL (CORRECT PLACE)
    try:
        result = client.llm.chat(
            model=og.TEE_LLM.GPT_4_1_2025_04_14,
            messages=messages,
            max_tokens=600,
            temperature=0.2
            
        )
    except Exception as e:
        print("FULL ERROR:\n", traceback.format_exc())
        raise

    raw = ""
    if result.chat_output:
        raw = result.chat_output.get("content", "") or ""

    parsed = parse_ai_response(raw)

    return {
        "cert_id": generate_cert_id(),
        "author": author,
        "idea": idea,
        "idea_hash": hash_idea(idea),
        "timestamp": datetime.datetime.utcnow().strftime("%B %d, %Y · %H:%M UTC"),
        "payment_hash": getattr(result, "payment_hash", None),
        "title": parsed.get("title", "Idea certificate"),
        "scores": parsed.get("scores", {}),
        "analysis": parsed.get("analysis", ""),
        "similar": parsed.get("similar", [])
    }


# ✅ THIS MUST BE TOP-LEVEL (DO NOT INDENT)
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
