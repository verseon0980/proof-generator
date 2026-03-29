import os
import json
from eth_account import Account
from http.server import BaseHTTPRequestHandler


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        pk = os.environ.get("OG_PRIVATE_KEY", "")
        if not pk:
            self._json(500, {"error": "OG_PRIVATE_KEY not set"})
            return
        wallet = Account.from_key(pk)
        self._json(200, {"address": wallet.address})

    def _json(self, code, data):
        payload = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(payload))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass
