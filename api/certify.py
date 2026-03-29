import os
import json
import hashlib
import asyncio
import datetime
import re
import threading
from http.server import BaseHTTPRequestHandler

import opengradient as og
from opengradient import TEE_LLM

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


async def _infer(idea: str, author: str, llm) -> dict:
    prompt = f"""You are an AI that evaluates originality of ideas for a verifiable certificate system.

A user has submitted the following idea:
\"\"\"{idea}\"\"\"

Return ONLY valid JSON, no markdown, no extra text:
{{
  "title": "<short 5-8 word title for this idea>",
  "scores": {{
    "overall": <integer 0-100>,
    "novelty": <integer 0-100>,
    "market_gap": <integer 0-100>,
    "technical": <integer 0-100>,
    "prior_art_risk": <integer 0-100, where low means low risk>
  }},
  "analysis": "<2-3 sentence analysis of uniqueness>",
  "similar": [
    {{
      "name": "<similar product or patent name>",
      "difference": "<one sentence how this idea differs>",
      "risk": "low"
    }}
  ]
}}"""

    result = await llm.completion(
        model=TEE_LLM.GPT_4_1_2025_04_14,
        prompt=prompt,
        max_tokens=600,
        temperature=0.2
    )

    parsed = parse_ai_response(result.completion_output or "")
    return {
        "cert_id": generate_cert_id(),
        "author": author,
        "idea": idea,
        "idea_hash": hash_idea(idea),
        "timestamp": datetime.datetime.utcnow().strftime("%B %d, %Y · %H:%M UTC"),
        "payment_hash": result.payment_hash,
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
            llm = og.LLM(private_key=PRIVATE_KEY)
            llm.ensure_opg_approval(0.1)
            out['data'] = loop.run_until_complete(_infer(idea, author, llm))
        except Exception as e:
            err['e'] = e
        finally:
            loop.close()

    t = threading.Thread(target=target)
    t.start()
    t.join()

    if 'e' in err:
        raise err['e']
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
