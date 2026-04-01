import os
import json
import hashlib
import asyncio
import datetime
import re
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler

import opengradient as og
from eth_account import Account

PRIVATE_KEY = os.environ.get("OG_PRIVATE_KEY")
BASESCAN_API_KEY = os.environ.get("BASESCAN_API_KEY", "")

# OPG token contract on Base Sepolia
OPG_TOKEN = "0x240b09731D96979f50B2C649C9CE10FcF9C7987F"

try:
    WALLET_ADDRESS = Account.from_key(PRIVATE_KEY).address if PRIVATE_KEY else None
except Exception:
    WALLET_ADDRESS = None


def get_latest_opg_tx(wallet: str) -> str | None:
    """Fetch the latest OPG token transfer tx hash from Basescan API."""
    if not wallet:
        return None
    try:
        url = (
            f"https://api-sepolia.basescan.org/api"
            f"?module=account&action=tokentx"
            f"&contractaddress={OPG_TOKEN}"
            f"&address={wallet}"
            f"&page=1&offset=1&sort=desc"
            f"&apikey={BASESCAN_API_KEY}"
        )
        print(f"[certify] querying Basescan for wallet {wallet}")
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        print(f"[certify] Basescan status={data.get('status')} message={data.get('message')}")
        if data.get("status") == "1" and data.get("result"):
            tx = data["result"][0].get("hash", "")
            print(f"[certify] got tx: {tx}")
            return tx if tx else None
        return None
    except Exception as e:
        print(f"[certify] Basescan error: {e}")
        return None


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
    # Exact pattern from official example: og.LLM + llm.chat()
    llm = og.LLM(private_key=PRIVATE_KEY)
    llm.ensure_opg_approval(0.1)

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

    # Debug: log all result fields so we can see what the SDK actually returns
    print(f"[certify] result type: {type(result)}")
    print(f"[certify] result attrs: {[a for a in dir(result) if not a.startswith('_')]}")
    raw_tx = getattr(result, "transaction_hash", None)
    tee_id = getattr(result, "tee_id", None)
    print(f"[certify] transaction_hash={raw_tx!r}  tee_id={tee_id!r}")

    # Wait a few seconds for the tx to be indexed on Basescan, then fetch it
    time.sleep(4)
    tx_hash = get_latest_opg_tx(WALLET_ADDRESS)

    explorer_url = f"https://sepolia.basescan.org/tx/{tx_hash}" if tx_hash else None

    # Parse LLM content
    raw_content = ""
    if result.chat_output:
        if isinstance(result.chat_output, dict):
            raw_content = result.chat_output.get("content", "")
        elif isinstance(result.chat_output, str):
            raw_content = result.chat_output

    parsed = parse_ai_response(raw_content)

    return {
        "cert_id": generate_cert_id(),
        "author": author,
        "idea": idea,
        "idea_hash": hash_idea(idea),
        "timestamp": datetime.datetime.utcnow().strftime("%B %d, %Y · %H:%M UTC"),
        "transaction_hash": tx_hash or "",
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
