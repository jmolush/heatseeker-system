# Heatseeker System — Windows Setup Guide

## Prerequisites

- **Windows 11**
- **Python 3.8+** — [Download](https://www.python.org/downloads/) (check "Add Python to PATH" during install)
- **Google Chrome**
- **Moomoo OpenD** — [Download](https://www.moomoo.com/download/OpenAPI) (for market data, not needed for first test)

---

## Step 1: Clone the Repo

Open PowerShell or Command Prompt:

```
cd C:\Users\Justin
git clone https://github.com/jmolush/heatseeker-system.git
cd heatseeker-system
```

## Step 2: Backend Setup

```
cd backend
setup.bat
```

This creates a virtual environment, installs dependencies, and copies `.env.example` → `.env`.

**Edit `.env`** with your settings:
```
CAPTURE_BASE_PATH=C:/heatseeker/captures
BACKEND_HOST=0.0.0.0
BACKEND_PORT=5555
```

Leave `ANTHROPIC_API_KEY` blank for now — we'll add it when we're ready to test Claude analysis.

## Step 3: Start the Backend

```
run.bat
```

You should see:
```
[Heatseeker] Starting capture server on 0.0.0.0:5555
[Heatseeker] Captures saving to: C:\heatseeker\captures
```

**Verify it's running:** Open browser → `http://localhost:5555/api/health`
You should get a JSON response with `"status": "ok"`.

## Step 4: Load the Chrome Extension

1. Open Chrome → navigate to `chrome://extensions`
2. Enable **Developer mode** (toggle in top right)
3. Click **Load unpacked**
4. Navigate to `C:\Users\Justin\heatseeker-system\chrome-extension`
5. Click **Select Folder**

The extension icon should appear in your toolbar (may need to pin it).

## Step 5: Configure the Extension

Click the extension icon:

1. **Save Folder:** `C:\heatseeker\captures` (or wherever you want captures)
2. **Backend URL:** `http://localhost:5555`
3. **Interval:** Leave at 5 min for now

## Step 6: First Test Capture

1. Open Skylit Heatseeker in Chrome (`app.skylit.ai`)
2. Set up your view (Trinity Mode or single ticker)
3. Click the extension icon → **📸 Capture Now**
4. Check `C:\heatseeker\captures\YYYY-MM-DD\` — you should see a `.png` and `.json` file

---

## Playback Test (Weekend Validation)

This is the main test — replay a day's heatmaps and verify the capture pipeline works end-to-end.

### How to run:

1. Start the backend (`run.bat`)
2. Open Skylit Heatseeker → use the **Playback** feature to replay a recent trading day
3. Click **▶ Start Auto-Capture** in the extension (set interval to 1 min for faster testing)
4. Let it run through the playback — captures should stack up in the date folder
5. Stop capture when done
6. Check the captures folder — you should see timestamped screenshots with metadata

### What we're validating:

- ✅ Extension captures the visible Heatseeker window correctly
- ✅ Captures resize dynamically with your window (1920x1080 to 1920x2160)
- ✅ Backend receives and saves captures with metadata
- ✅ Date subfolders are created properly
- ✅ Images are clear enough for Claude to read the heatmap

### What we're NOT testing yet:

- ❌ Claude analysis (no API key configured yet)
- ❌ OpenD market data (markets closed on weekend)
- ❌ Paper trading (needs OpenD + market hours)
- ❌ VIX/SPX data (yfinance works on weekends but returns last close)

---

## Troubleshooting

**"No Skylit tab found" when capturing:**
- Make sure `app.skylit.ai` is open in Chrome (not another browser)
- The extension looks for tabs matching `https://app.skylit.ai/*`

**Backend not receiving captures:**
- Check that `run.bat` is running (Flask server)
- Verify the Backend URL in the extension matches (`http://localhost:5555`)
- Check Windows Firewall isn't blocking port 5555

**Captures are black or blank:**
- Chrome requires the tab to be visible for `captureVisibleTab`
- Make sure the Skylit tab is the active tab when capture fires
- If the window is minimized, captures won't work

**Python not found:**
- Install Python from python.org
- Make sure "Add Python to PATH" was checked
- Restart your terminal after installing

---

## Next Steps (After Weekend Test)

1. Add Anthropic API key → test Claude analysis on captured images
2. Install and configure OpenD → test market data + option chains
3. Run `test.bat` to validate yfinance VIX data
4. First live capture session during market hours (Monday)
