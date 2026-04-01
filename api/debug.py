import os
import json
import urllib.request
from http.server import BaseHTTPRequestHandler
from eth_account import Account

PRIVATE_KEY = os.environ.get("OG_PRIVATE_KEY")
BASESCAN_API_KEY = os.environ.get("BASESCAN_API_KEY", "")
OPG_TOKEN = "0x240b09731D96979f50B2C649C9CE10FcF9C7987F"

try:
    WALLET_ADDRESS = Account.from_key(PRIVATE_KEY).address if PRIVATE_KEY else None
except Exception as e:
    WALLET_ADDRESS = f"ERROR: {e}"


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        result = {
            "wallet_address": WALLET_ADDRESS,
            "has_private_key": bool(PRIVATE_KEY),
            "has_basescan_key": bool(BASESCAN_API_KEY),
            "basescan_key_prefix": BASESCAN_API_KEY[:6] + "..." if BASESCAN_API_KEY else None,
        }

        # Try hitting Basescan
        try:
            url = (
                f"https://api-sepolia.basescan.org/api"
                f"?module=account&action=tokentx"
                f"&contractaddress={OPG_TOKEN}"
                f"&address={WALLET_ADDRESS}"
                f"&page=1&offset=3&sort=desc"
                f"&apikey={BASESCAN_API_KEY}"
            )
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
            result["basescan_status"] = data.get("status")
            result["basescan_message"] = data.get("message")
            result["basescan_tx_count"] = len(data.get("result") or [])
            result["basescan_latest_tx"] = (data.get("result") or [{}])[0].get("hash") if data.get("result") else None
            result["basescan_raw"] = (data.get("result") or [])[:3]
        except Exception as e:
            result["basescan_error"] = str(e)

        payload = json.dumps(result, indent=2).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(payload))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass
