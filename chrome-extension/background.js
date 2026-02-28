// Heatseeker Capture — Background Service Worker

const DEFAULT_CONFIG = {
  savePath: '',
  backendUrl: 'http://localhost:5555',
  intervalMinutes: 5,
  notifications: true,
  discordAlerts: true,
  isCapturing: false,
  captureCountToday: 0,
  lastCaptureDate: null,
  lastCaptureTime: null,
};

// ─── State ───────────────────────────────────────────────────────

let config = { ...DEFAULT_CONFIG };

async function loadConfig() {
  const stored = await chrome.storage.local.get('config');
  if (stored.config) {
    config = { ...DEFAULT_CONFIG, ...stored.config };
  }
  // Reset daily counter if date changed
  const today = new Date().toISOString().split('T')[0];
  if (config.lastCaptureDate !== today) {
    config.captureCountToday = 0;
    config.lastCaptureDate = today;
    await saveConfig();
  }
  return config;
}

async function saveConfig() {
  await chrome.storage.local.set({ config });
}

// ─── Capture Logic ───────────────────────────────────────────────

async function captureTab() {
  try {
    // Find the Skylit tab
    const tabs = await chrome.tabs.query({ url: 'https://app.skylit.ai/*' });
    if (tabs.length === 0) {
      console.warn('[Heatseeker] No Skylit tab found');
      return { success: false, error: 'No Skylit tab found. Open app.skylit.ai first.' };
    }

    const tab = tabs[0];

    // Make sure the tab is active for capture (Chrome requires this for captureVisibleTab)
    await chrome.tabs.update(tab.id, { active: true });
    await chrome.windows.update(tab.windowId, { focused: true });

    // Small delay to let the tab render
    await new Promise(r => setTimeout(r, 500));

    // Capture the visible area of the tab
    const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, {
      format: 'png',
      quality: 100
    });

    const timestamp = new Date();
    const dateStr = timestamp.toISOString().split('T')[0]; // YYYY-MM-DD
    const timeStr = timestamp.toISOString().split('T')[1].replace(/:/g, '-').split('.')[0]; // HH-MM-SS
    const filename = `heatseeker_${dateStr}_${timeStr}.png`;

    // Try to scrape structured data from the DOM (much cheaper than vision tokens)
    let scrapedData = null;
    try {
      scrapedData = await chrome.tabs.sendMessage(tab.id, { action: 'getHeatmapData' });
    } catch (err) {
      // Content script not loaded — inject it programmatically and retry
      console.warn('[Heatseeker] Content script not loaded, injecting now...');
      try {
        await chrome.scripting.executeScript({
          target: { tabId: tab.id },
          files: ['content.js']
        });
        // Small delay to let the script initialize
        await new Promise(r => setTimeout(r, 300));
        scrapedData = await chrome.tabs.sendMessage(tab.id, { action: 'getHeatmapData' });
      } catch (retryErr) {
        console.warn('[Heatseeker] DOM scrape failed after injection:', retryErr.message);
      }
    }

    if (scrapedData?.available && scrapedData?.data) {
      console.log(`[Heatseeker] Scraped ${scrapedData.data.total_nodes} nodes from DOM`);
    } else {
      console.warn('[Heatseeker] No scraped data available');
      scrapedData = null;
    }

    // Send to backend (screenshot + structured data)
    const scraped = scrapedData?.available ? scrapedData.data : null;
    const result = await sendToBackend(dataUrl, filename, dateStr, timestamp, scraped);

    // Update stats
    config.captureCountToday++;
    config.lastCaptureTime = timestamp.toISOString();
    await saveConfig();

    // Notify if enabled
    if (config.notifications) {
      chrome.notifications.create({
        type: 'basic',
        iconUrl: 'icons/icon128.png',
        title: 'Heatseeker Capture',
        message: `Captured: ${filename}`,
        silent: true
      });
    }

    console.log(`[Heatseeker] Captured: ${filename}`);
    return { success: true, filename, timestamp: timestamp.toISOString() };

  } catch (err) {
    console.error('[Heatseeker] Capture failed:', err);
    return { success: false, error: err.message };
  }
}

async function sendToBackend(dataUrl, filename, dateSubfolder, timestamp, scrapedData = null) {
  if (!config.backendUrl) {
    console.warn('[Heatseeker] No backend URL configured');
    return { error: 'No backend URL configured' };
  }

  try {
    // Convert data URL to blob
    const response = await fetch(dataUrl);
    const blob = await response.blob();

    const formData = new FormData();
    formData.append('image', blob, filename);
    formData.append('filename', filename);
    formData.append('date', dateSubfolder);
    formData.append('timestamp', timestamp.toISOString());
    formData.append('savePath', config.savePath);
    if (scrapedData) {
      formData.append('scraped_data', JSON.stringify(scrapedData));
    }

    const result = await fetch(`${config.backendUrl}/api/capture`, {
      method: 'POST',
      body: formData
    });

    if (!result.ok) {
      const errText = await result.text();
      throw new Error(`Backend returned ${result.status}: ${errText}`);
    }

    const data = await result.json();
    console.log(`[Heatseeker] Backend saved: ${data.path} (${data.size} bytes)`);
    return data;
  } catch (err) {
    console.error('[Heatseeker] Failed to send to backend:', err.message);

    // Show notification so user knows backend is down
    if (config.notifications) {
      chrome.notifications.create({
        type: 'basic',
        iconUrl: 'icons/icon128.png',
        title: 'Heatseeker — Backend Error',
        message: `Could not reach backend: ${err.message}`,
        silent: false
      });
    }

    return { error: err.message };
  }
}

// ─── Auto-Capture Timer ──────────────────────────────────────────

const ALARM_NAME = 'heatseeker-auto-capture';

async function startAutoCapture() {
  config.isCapturing = true;
  await saveConfig();

  // Create alarm for periodic capture
  await chrome.alarms.create(ALARM_NAME, {
    delayInMinutes: config.intervalMinutes,
    periodInMinutes: config.intervalMinutes
  });

  // Do an immediate capture
  await captureTab();

  console.log(`[Heatseeker] Auto-capture started: every ${config.intervalMinutes} min`);
}

async function stopAutoCapture() {
  config.isCapturing = false;
  await saveConfig();
  await chrome.alarms.clear(ALARM_NAME);
  console.log('[Heatseeker] Auto-capture stopped');
}

async function updateInterval(minutes) {
  config.intervalMinutes = Math.max(1, Math.min(30, minutes));
  await saveConfig();

  // If capturing, restart with new interval
  if (config.isCapturing) {
    await chrome.alarms.clear(ALARM_NAME);
    await chrome.alarms.create(ALARM_NAME, {
      delayInMinutes: config.intervalMinutes,
      periodInMinutes: config.intervalMinutes
    });
  }
}

// Alarm handler
chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === ALARM_NAME) {
    await loadConfig();
    if (config.isCapturing) {
      await captureTab();
    }
  }
});

// ─── Message Handling (from popup) ───────────────────────────────

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    await loadConfig();

    switch (msg.action) {
      case 'getConfig':
        sendResponse({ config });
        break;

      case 'updateConfig':
        Object.assign(config, msg.updates);
        await saveConfig();
        sendResponse({ config });
        break;

      case 'captureNow':
        const result = await captureTab();
        sendResponse(result);
        break;

      case 'startCapture':
        await startAutoCapture();
        sendResponse({ config });
        break;

      case 'stopCapture':
        await stopAutoCapture();
        sendResponse({ config });
        break;

      case 'updateInterval':
        await updateInterval(msg.minutes);
        sendResponse({ config });
        break;

      default:
        sendResponse({ error: 'Unknown action' });
    }
  })();

  return true; // Keep message channel open for async response
});

// ─── Init ────────────────────────────────────────────────────────

chrome.runtime.onInstalled.addListener(async () => {
  await loadConfig();
  console.log('[Heatseeker] Extension installed/updated');
});

chrome.runtime.onStartup.addListener(async () => {
  await loadConfig();
  // Don't auto-resume capture on browser restart — user should start manually
  if (config.isCapturing) {
    config.isCapturing = false;
    await saveConfig();
  }
});
