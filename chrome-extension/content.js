// Heatseeker Capture — Content Script
// Injected into app.skylit.ai pages
// Future: DOM scraping for structured node data

(function() {
  'use strict';

  console.log('[Heatseeker] Content script loaded on Skylit');

  // Placeholder for future DOM scraping functionality
  // The initial version relies on screenshot capture from the background script
  // 
  // Future enhancements:
  // - Extract node values directly from DOM (React-rendered table data)
  // - Parse GEX heatmap cell values (strike × expiry × dollar value)
  // - Detect current mode (Trinity, single ticker, etc.)
  // - Extract active ticker list
  // - Monitor for map reshuffles (rapid value changes)
  
  // Listen for messages from background script
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    switch (msg.action) {
      case 'getPageInfo':
        sendResponse({
          url: window.location.href,
          title: document.title,
          timestamp: new Date().toISOString()
        });
        break;

      case 'getHeatmapData':
        // Future: scrape structured data from the DOM
        sendResponse({ 
          available: false, 
          message: 'DOM scraping not yet implemented — using screenshot capture' 
        });
        break;

      default:
        sendResponse({ error: 'Unknown action' });
    }
    return true;
  });
})();
