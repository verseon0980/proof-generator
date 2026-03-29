from eth_account import Account
import os

def handler(req, res):
    pk = os.environ.get("OG_PRIVATE_KEY", "")
    if not pk:
        return res.status(500).json({"error": "OG_PRIVATE_KEY not set"})
    wallet = Account.from_key(pk)
    return res.status(200).json({"address": wallet.address})
