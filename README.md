# Sammamish Market Tracker
**Skyline HS · 4BR · 2,400–3,200 sqft · Spring vs Fall 2026 timing**

Live dashboard powered by Zillow Research public data, auto-updated every Monday via GitHub Actions. Completely free — no API keys, no backend, no hosting costs.

---

## How it works

```
Zillow Research CSVs (free, public)
        ↓  every Monday
  GitHub Action runs fetch_data.py
        ↓
  data.json committed to repo
        ↓
  GitHub Pages serves index.html
        ↓
  Your browser reads data.json
```

---

## Setup (one time, ~10 minutes)

### 1. Create a GitHub account
Go to https://github.com and sign up if you don't have one. Free.

### 2. Create a new repository
- Click the **+** icon → **New repository**
- Name it: `sammamish-tracker` (or anything you like)
- Set it to **Public** ← important for free GitHub Pages
- Don't initialize with README (you'll upload these files)
- Click **Create repository**

### 3. Upload the files
You can drag-and-drop all files into the GitHub web UI, or use Git.

**Option A — drag and drop (no Git needed):**
1. On your new repo page, click **uploading an existing file**
2. Drag in: `index.html`, `data.json`, `fetch_data.py`
3. Then create the folder `.github/workflows/` and upload `update-data.yml` into it
4. Click **Commit changes**

**Option B — Git (if you have it):**
```bash
cd sammamish-tracker
git init
git add .
git commit -m "initial commit"
git remote add origin https://github.com/YOUR_USERNAME/sammamish-tracker.git
git push -u origin main
```

### 4. Enable GitHub Pages
1. Go to your repo → **Settings** → **Pages** (left sidebar)
2. Under **Source**, select **Deploy from a branch**
3. Branch: **main**, folder: **/ (root)**
4. Click **Save**
5. Wait ~60 seconds, then your site is live at:
   `https://YOUR_USERNAME.github.io/sammamish-tracker/`

### 5. Run the data fetch for the first time
1. Go to **Actions** tab in your repo
2. Click **Update Zillow Market Data** (left sidebar)
3. Click **Run workflow** → **Run workflow**
4. Wait ~30 seconds for it to complete
5. It will commit a fresh `data.json` with real Zillow data

After that, it runs automatically every Monday. You never touch it again.

---

## Files

| File | Purpose |
|------|---------|
| `index.html` | The dashboard — reads data.json |
| `data.json` | Market data (auto-updated by Action) |
| `fetch_data.py` | Fetches Zillow CSVs, writes data.json |
| `.github/workflows/update-data.yml` | GitHub Action schedule |

---

## Updating the zip code or criteria

Open `fetch_data.py` and change line 14:
```python
ZIP = "98075"  # change to any US zip code
```

Zip codes for the Skyline HS area:
- `98075` — Sammamish (main)
- `98074` — Sammamish (north/Beaver Lake area)

---

## Data sources

- **Zillow Research**: https://www.zillow.com/research/data/
- Median sale price, days to pending, for-sale inventory, new listings, % sold above list
- All single-family + condo, weekly frequency
- Publicly available, no API key or account required

---

## Troubleshooting

**Dashboard shows "Could not load data.json"**
→ Make sure GitHub Pages is enabled and pointing to the main branch root.

**GitHub Action fails**
→ Click the failed run → see the error log. Usually a Zillow URL change.
→ Check https://www.zillow.com/research/data/ for updated CSV links and update `SOURCES` in `fetch_data.py`.

**data.json shows old seed data**
→ Go to Actions tab and manually trigger "Update Zillow Market Data".
