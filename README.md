# Pinterest → WhatsApp Stickers

Paste a Pinterest board URL, get a `.wastickers` file back.

## Deploy in 5 minutes

### 1. Push to GitHub
```bash
git init
git add .
git commit -m "initial commit"
gh repo create pinterest-stickers --public --push
```

### 2. Deploy on Render
1. Go to https://render.com → New → Web Service
2. Connect your GitHub repo
3. Settings:
   - **Environment**: Python 3
   - **Build command**: `pip install -r requirements.txt`
   - **Start command**: `gunicorn app:app --workers 2 --timeout 120`
4. Click **Deploy**

That's it. Render gives you a public URL like `https://pinterest-stickers.onrender.com`.

## Run locally
```bash
pip install -r requirements.txt
python app.py
# open http://localhost:5000
```

## Notes
- Public Pinterest boards only (no login required)
- Max 30 stickers per pack (WhatsApp limit)
- Each sticker: 512×512 WebP, max 100KB
- Free Render tier sleeps after inactivity — first request may take ~30s to wake up
