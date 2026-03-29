import os
import json
import hashlib
import asyncio
import datetime
import re
import threading
import traceback
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

A user submitted this idea:
\"\"\"{idea}\"\"\"

Return ONLY valid JSON, no markdown, no extra text:
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
  "similar": [
    {{
      "name": "<similar product>",
      "difference": "<one sentence difference>",
      "risk": "low"
    }}
  ]
}}"""

    # result = await llm.completion(
    #     model_cid='gpt-4',
    #     prompt=prompt,
    #     max_tokens=600,
    #     temperature=0.2
    # )
    result = og.global_client.text_generation(
                prompt=prompt,
                model_cid='gpt-4',
                max_tokens=60,
                temperature=1.0  # High temperature for more variety
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
            err['msg'] = traceback.format_exc()
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
        # Always send JSON — never let Python send its own error page
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

            try:
                result = run_inference(idea, author)
                self._json(200, result)
            except Exception as e:
                self._error(500, str(e))

        except Exception as e:
            # Last resort — still send JSON
            self._error(500, f"Unexpected error: {str(e)}")

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code, data):
        try:
            payload = json.dumps(data).encode()
        except Exception:
            payload = b'{"error": "Failed to serialize response"}'
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
