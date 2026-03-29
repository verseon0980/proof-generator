import os
import json
import hashlib
import asyncio
import datetime
import re
from http.server import BaseHTTPRequestHandler

import opengradient as og

PRIVATE_KEY = os.environ.get("OG_PRIVATE_KEY")


def generate_cert_id():
    now = datetime.datetime.utcnow()
    rand = hashlib.sha256(str(now.timestamp()).encode()).hexdigest()[:4].upper()
    return f"PG-{now.strftime('%Y%m%d')}-{rand}"


def hash_idea(idea: str) -> str:
    return "0x" + hashlib.sha256(idea.encode()).hexdigest()


def extract_text_from_result(result) -> str:
    """
    Safely extract the text string from an OpenGradient completion result.
    Handles: plain string, object with .completion_output (str or list),
    object with .content (list of blocks), or dict.
    """
    # 1. Already a plain string
    if isinstance(result, str):
        return result

    # 2. Dict-like
    if isinstance(result, dict):
        for key in ("completion_output", "content", "text", "output"):
            val = result.get(key)
            if val:
                return extract_text_from_result(val)
        return json.dumps(result)

    # 3. List — could be a list of content blocks or a list of strings
    if isinstance(result, list):
        parts = []
        for item in result:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                # Anthropic-style block: {"type": "text", "text": "..."}
                text = item.get("text") or item.get("content") or ""
                if text:
                    parts.append(text)
            elif hasattr(item, "text"):
                parts.append(str(item.text))
        return " ".join(parts)

    # 4. Object with .completion_output attribute
    if hasattr(result, "completion_output"):
        return extract_text_from_result(result.completion_output)

    # 5. Object with .content attribute
    if hasattr(result, "content"):
        return extract_text_from_result(result.content)

    # 6. Object with .text attribute
    if hasattr(result, "text"):
        return str(result.text)

    # 7. Fallback: stringify whatever we got
    return str(result)


def parse_ai_response(raw: str) -> dict:
    """Parse JSON from AI response, stripping markdown fences if present."""
    clean = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()

    # Try to find a JSON object even if there's surrounding text
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
            "analysis": raw[:500] if raw else "Analysis unavailable.",
            "similar": []
        }


def run_inference_sync(idea: str, author: str) -> dict:
    """
    Synchronous wrapper around OpenGradient inference.
    Handles both sync and async SDK variants gracefully.
    """
    prompt = f"""You are an AI that evaluates originality of ideas for a verifiable certificate system.

A user has submitted the following idea:
\"\"\"{idea}\"\"\"

Your task:
1. Search your knowledge for similar existing products, startups, and patents.
2. Score the idea's originality across 4 dimensions (0-100 each).
3. Write a concise analysis of what makes it unique (2-3 sentences).
4. List 2-4 similar things that already exist, with what makes this idea different.

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
      "name": "<name of similar product or patent>",
      "difference": "<one sentence: how this idea differs from it>",
      "risk": "low"
    }}
  ]
}}"""

    llm = og.LLM(private_key=PRIVATE_KEY)

    # Some SDK versions require approval; wrap in try/except so it doesn't crash
    try:
        llm.ensure_opg_approval(0.1)
    except Exception:
        pass

    payment_hash = None

    # Try async completion first, then fall back to sync
    try:
        result = asyncio.run(
            llm.completion(
                model='gpt-4o-mini',
                prompt=prompt,
                max_tokens=600,
                temperature=0.2
            )
        )
    except (RuntimeError, AttributeError):
        # asyncio.run fails if there's already a running loop,
        # or if the method is synchronous
        result = llm.completion(
            model='gpt-4o-mini',
            prompt=prompt,
            max_tokens=600,
            temperature=0.2
        )

    # Safely pull the payment hash if the SDK provides it
    if hasattr(result, 'payment_hash'):
        payment_hash = result.payment_hash
    elif isinstance(result, dict):
        payment_hash = result.get('payment_hash')

    raw_text = extract_text_from_result(result)
    parsed = parse_ai_response(raw_text)

    return {
        "cert_id": generate_cert_id(),
        "author": author,
        "idea": idea,
        "idea_hash": hash_idea(idea),
        "timestamp": datetime.datetime.utcnow().strftime("%B %d, %Y · %H:%M UTC"),
        "payment_hash": payment_hash,
        "title": parsed.get("title", "Idea certificate"),
        "scores": parsed.get("scores", {
            "overall": 70,
            "novelty": 70,
            "market_gap": 70,
            "technical": 70,
            "prior_art_risk": 30
        }),
        "analysis": parsed.get("analysis", ""),
        "similar": parsed.get("similar", [])
    }


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self._set_cors()
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
                self._error(500, "Server configuration error: missing OG_PRIVATE_KEY.")
                return

            result = run_inference_sync(idea, author)
            self._json(200, result)

        except json.JSONDecodeError:
            self._error(400, "Invalid JSON in request body.")
        except Exception as e:
            self._error(500, f"Internal error: {str(e)}")

    def _set_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code, data):
        payload = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(payload))
        self._set_cors()
        self.end_headers()
        self.wfile.write(payload)

    def _error(self, code, msg):
        self._json(code, {"error": msg})

    def log_message(self, *args):
        pass
