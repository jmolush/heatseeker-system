// Heatseeker Capture — Popup UI

document.addEventListener('DOMContentLoaded', async () => {
  // ─── Elements ──────────────────────────────────────────────
  const statusDot = document.getElementById('statusDot');
  const statusText = document.getElementById('statusText');
  const savePathInput = document.getElementById('savePath');
  const backendUrlInput = document.getElementById('backendUrl');
  const intervalDisplay = document.getElementById('intervalDisplay');
  const intervalSlider = document.getElementById('intervalSlider');
  const notificationsToggle = document.getElementById('notificationsToggle');
  const discordToggle = document.getElementById('discordToggle');
  const captureNowBtn = document.getElementById('captureNow');
  const toggleCaptureBtn = document.getElementById('toggleCapture');
  const captureCount = document.getElementById('captureCount');
  const lastCapture = document.getElementById('lastCapture');
  const nextCapture = document.getElementById('nextCapture');

  // ─── Load Config ───────────────────────────────────────────
  let config = {};

  async function loadState() {
    const response = await chrome.runtime.sendMessage({ action: 'getConfig' });
    config = response.config;
    updateUI();
  }

  function updateUI() {
    // Status
    if (config.isCapturing) {
      statusDot.className = 'status-dot active';
      statusText.textContent = `Capturing every ${config.intervalMinutes} min`;
      toggleCaptureBtn.textContent = '⏹ Stop Capture';
      toggleCaptureBtn.classList.add('running');
    } else {
      statusDot.className = 'status-dot';
      statusText.textContent = 'Idle';
      toggleCaptureBtn.textContent = '▶ Start Auto-Capture';
      toggleCaptureBtn.classList.remove('running');
    }

    // Fields
    savePathInput.value = config.savePath || '';
    backendUrlInput.value = config.backendUrl || '';
    intervalSlider.value = config.intervalMinutes;
    intervalDisplay.textContent = config.intervalMinutes;
    notificationsToggle.checked = config.notifications;
    discordToggle.checked = config.discordAlerts;

    // Stats
    captureCount.textContent = config.captureCountToday || 0;
    if (config.lastCaptureTime) {
      const t = new Date(config.lastCaptureTime);
      lastCapture.textContent = t.toLocaleTimeString();
    } else {
      lastCapture.textContent = '—';
    }

    if (config.isCapturing && config.lastCaptureTime) {
      const next = new Date(new Date(config.lastCaptureTime).getTime() + config.intervalMinutes * 60000);
      nextCapture.textContent = next.toLocaleTimeString();
    } else {
      nextCapture.textContent = '—';
    }
  }

  // ─── Event Handlers ────────────────────────────────────────

  // Save path
  let savePathTimeout;
  savePathInput.addEventListener('input', () => {
    clearTimeout(savePathTimeout);
    savePathTimeout = setTimeout(async () => {
      await chrome.runtime.sendMessage({
        action: 'updateConfig',
        updates: { savePath: savePathInput.value }
      });
    }, 500);
  });

  // Backend URL
  let backendTimeout;
  backendUrlInput.addEventListener('input', () => {
    clearTimeout(backendTimeout);
    backendTimeout = setTimeout(async () => {
      await chrome.runtime.sendMessage({
        action: 'updateConfig',
        updates: { backendUrl: backendUrlInput.value }
      });
    }, 500);
  });

  // Interval slider
  intervalSlider.addEventListener('input', () => {
    intervalDisplay.textContent = intervalSlider.value;
  });

  intervalSlider.addEventListener('change', async () => {
    await chrome.runtime.sendMessage({
      action: 'updateInterval',
      minutes: parseInt(intervalSlider.value)
    });
    await loadState();
  });

  // Interval +/- buttons
  document.querySelectorAll('.interval-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const delta = parseInt(btn.dataset.delta);
      const newVal = Math.max(1, Math.min(30, config.intervalMinutes + delta));
      intervalSlider.value = newVal;
      intervalDisplay.textContent = newVal;
      await chrome.runtime.sendMessage({
        action: 'updateInterval',
        minutes: newVal
      });
      await loadState();
    });
  });

  // Toggles
  notificationsToggle.addEventListener('change', async () => {
    await chrome.runtime.sendMessage({
      action: 'updateConfig',
      updates: { notifications: notificationsToggle.checked }
    });
  });

  discordToggle.addEventListener('change', async () => {
    await chrome.runtime.sendMessage({
      action: 'updateConfig',
      updates: { discordAlerts: discordToggle.checked }
    });
  });

  // Capture now
  captureNowBtn.addEventListener('click', async () => {
    captureNowBtn.disabled = true;
    captureNowBtn.textContent = '⏳ Capturing...';

    const result = await chrome.runtime.sendMessage({ action: 'captureNow' });

    if (result.success) {
      captureNowBtn.textContent = '✅ Captured!';
    } else {
      captureNowBtn.textContent = '❌ Failed';
      console.error('Capture failed:', result.error);
    }

    await loadState();

    setTimeout(() => {
      captureNowBtn.disabled = false;
      captureNowBtn.textContent = '📸 Capture Now';
    }, 2000);
  });

  // Toggle auto-capture
  toggleCaptureBtn.addEventListener('click', async () => {
    if (config.isCapturing) {
      await chrome.runtime.sendMessage({ action: 'stopCapture' });
    } else {
      // Validate config
      if (!config.backendUrl) {
        statusText.textContent = '⚠️ Set backend URL first';
        return;
      }
      await chrome.runtime.sendMessage({ action: 'startCapture' });
    }
    await loadState();
  });

  // ─── Init ──────────────────────────────────────────────────
  await loadState();

  // Refresh stats every 10 seconds while popup is open
  setInterval(loadState, 10000);
});
