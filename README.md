# Proof Generator — Deployment Guide

## Your project structure
```
proof-generator/
├── api/
│   └── certify.py        ← Python backend (OpenGradient SDK)
├── index.html        ← Frontend (single file)
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

