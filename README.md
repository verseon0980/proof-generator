# Proof Generator — Deployment Guide

## Your project structure
```
proof-generator/
├── api/
│   └── certify.py        ← Python backend (OpenGradient SDK)
├── public/
│   └── index.html        ← Frontend (single file)
├── requirements.txt
└── vercel.json
```

---

## Step 1 — Push to GitHub

1. Go to https://github.com and create a new repo called `proof-generator` (private is fine)
2. On your computer, open terminal in the `proof-generator` folder and run:

```bash
git init
git add .
git commit -m "initial"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/proof-generator.git
git push -u origin main
```

---

## Step 2 — Deploy on Vercel

1. Go to https://vercel.com and sign up free with your GitHub account
2. Click **"Add New Project"**
3. Import your `proof-generator` repo
4. Vercel auto-detects everything from `vercel.json` — click **Deploy**

---

## Step 3 — Add your private key (secret)

After deploy, in Vercel dashboard:

1. Go to your project → **Settings** → **Environment Variables**
2. Add:
   - Name: `OG_PRIVATE_KEY`
   - Value: your wallet private key (e.g. `0xabc123...`)
   - Environment: Production + Preview + Development
3. Click **Save**
4. Go to **Deployments** → click the 3 dots on latest → **Redeploy**

Your app is now live at `your-project.vercel.app`

---

## What uses your testnet tokens

Only one API call per user submission — `llm.completion()` with `SETTLE_METADATA` mode. This uses the least tokens possible while still recording the TEE attestation on-chain for the competition demo.

`ensure_opg_approval(opg_amount=5.0)` only sends a transaction the first time — after that it's free until your allowance drops below 5 OPG.

---

## Testing locally (optional)

```bash
pip install opengradient flask
export OG_PRIVATE_KEY=your_private_key_here
python -c "
from http.server import HTTPServer
from api.certify import handler
HTTPServer(('localhost', 8000), handler).serve_forever()
"
```
Then open `public/index.html` directly in your browser and change the fetch URL to `http://localhost:8000/api/certify`.
