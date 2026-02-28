// Heatseeker Capture — Content Script
// Injected into app.skylit.ai pages
// Scrapes heatmap data from the DOM into structured JSON

(function() {
  'use strict';

  console.log('[Heatseeker] Content script loaded on Skylit');

  /**
   * Scrape all visible heatmap panels from Trinity Mode or single view.
   * Returns structured JSON with strike prices, values, colors, and metadata.
   */
  function scrapeHeatmapData() {
    const panels = [];
    
    // Each panel in Trinity Mode is a distinct column with its own ticker header
    // Look for the panel containers — adjust selectors based on actual DOM structure
    
    // Strategy: find all elements that look like heatmap panels
    // Each panel has: ticker label, price, king indicator, and rows of strike data
    
    // Try to find panel headers (SPXW, SPY, QQQ labels with prices)
    const panelHeaders = document.querySelectorAll('[class*="panel"], [class*="heatmap"], [class*="column"]');
    
    // Fallback: scan the entire page for structured data
    const result = {
      timestamp: new Date().toISOString(),
      url: window.location.href,
      mode: detectMode(),
      panels: [],
      raw_scrape: null,
    };

    // Approach 1: Try to find panel containers by structure
    // Each Trinity panel typically has a header with ticker + price, then a scrollable body with rows
    const tickerLabels = findTickerLabels();
    
    if (tickerLabels.length > 0) {
      for (const label of tickerLabels) {
        const panel = scrapePanel(label);
        if (panel && panel.nodes.length > 0) {
          result.panels.push(panel);
        }
      }
    }

    // Approach 2: If structured scraping didn't find much, do a brute-force text scan
    if (result.panels.length === 0 || result.panels.every(p => p.nodes.length === 0)) {
      console.log('[Heatseeker] Structured scraping found nothing, trying text scan...');
      result.raw_scrape = bruteForceTextScan();
    }

    result.panel_count = result.panels.length;
    result.total_nodes = result.panels.reduce((sum, p) => sum + p.nodes.length, 0);
    
    console.log(`[Heatseeker] Scraped ${result.panel_count} panels, ${result.total_nodes} total nodes`);
    return result;
  }

  /**
   * Detect what mode Skylit is in (Trinity, single, etc.)
   */
  function detectMode() {
    const bodyText = document.body.innerText;
    if (bodyText.includes('TRINITY') || bodyText.includes('3 panels')) {
      return 'trinity';
    }
    return 'single';
  }

  /**
   * Find ticker label elements (SPXW, SPY, QQQ, etc.)
   * These are the starting points for scraping each panel.
   */
  function findTickerLabels() {
    const tickers = ['SPXW', 'SPY', 'QQQ', 'IWM', 'VIX'];
    const found = [];

    // Look for elements containing ticker text
    // Could be buttons, spans, divs — varies by Skylit's UI version
    const allElements = document.querySelectorAll('button, span, div, select');
    
    for (const el of allElements) {
      const text = el.textContent.trim();
      if (tickers.includes(text) && el.offsetParent !== null) {
        // Verify this looks like a panel header (has price nearby)
        const parent = el.closest('[class*="panel"], [class*="column"], [class*="grid"]') || el.parentElement?.parentElement?.parentElement;
        if (parent) {
          found.push({
            ticker: text,
            element: el,
            container: parent,
          });
        }
      }
    }

    // Deduplicate by ticker
    const seen = new Set();
    return found.filter(f => {
      if (seen.has(f.ticker)) return false;
      seen.add(f.ticker);
      return true;
    });
  }

  /**
   * Scrape a single panel's data given its ticker label element.
   */
  function scrapePanel(labelInfo) {
    const { ticker, element, container } = labelInfo;
    
    const panel = {
      ticker: ticker,
      price: null,
      change: null,
      change_pct: null,
      king_pct: null,
      nodes: [],
    };

    // Find price near the ticker label
    // Look for elements with $ values or decimal numbers near the label
    const headerArea = element.closest('[class*="header"], [class*="top"]') || container;
    if (headerArea) {
      const priceMatch = headerArea.textContent.match(/\$?([\d,]+\.\d{2})/);
      if (priceMatch) {
        panel.price = parseFloat(priceMatch[1].replace(',', ''));
      }
      
      const changeMatch = headerArea.textContent.match(/([-+]?\d+\.\d+%)/);
      if (changeMatch) {
        panel.change_pct = changeMatch[1];
      }

      const kingMatch = headerArea.textContent.match(/King\s+([\d.]+%?\s*[↑↓]?)/i);
      if (kingMatch) {
        panel.king_pct = kingMatch[1].trim();
      }
    }

    // Find node rows — each row has a strike price and a dollar value
    // Look for all text content that matches the pattern: number + $value
    const rows = findNodeRows(container);
    
    for (const row of rows) {
      const node = parseNodeRow(row);
      if (node) {
        panel.nodes.push(node);
      }
    }

    // Sort by strike descending (highest at top, matching visual layout)
    panel.nodes.sort((a, b) => b.strike - a.strike);

    return panel;
  }

  /**
   * Find elements that look like heatmap node rows.
   * Each row typically has: strike number | colored bar | dollar value
   */
  function findNodeRows(container) {
    if (!container) return [];

    // Strategy: find all elements that contain a dollar value pattern
    const candidates = [];
    const allElements = container.querySelectorAll('div, span, td, tr, li');

    for (const el of allElements) {
      const text = el.textContent.trim();
      
      // Match patterns like "$1,234.5K" or "-$456.7K" or "$22,821.9K★"
      if (/[-]?\$[\d,]+\.?\d*K?\*?★?/.test(text)) {
        // Make sure this element also has a strike price (4-digit number)
        if (/\b\d{3,5}\b/.test(text)) {
          candidates.push(el);
        }
      }
    }

    // Deduplicate — prefer the most specific (smallest) elements
    // Filter out parents of other candidates
    const filtered = candidates.filter(el => {
      return !candidates.some(other => other !== el && el.contains(other));
    });

    return filtered;
  }

  /**
   * Parse a single node row element into structured data.
   */
  function parseNodeRow(element) {
    const text = element.textContent.trim();
    
    // Extract strike price (3-5 digit number, typically the first number in the row)
    const strikeMatch = text.match(/\b(\d{3,5})\b/);
    if (!strikeMatch) return null;
    
    const strike = parseInt(strikeMatch[1]);

    // Extract dollar value — could be positive or negative
    // Patterns: $1,234.5K, -$456.7K, $22,821.9K★
    const valueMatch = text.match(/([-]?)\$?([\d,]+\.?\d*)K?\*?★?/);
    if (!valueMatch) return null;

    const sign = valueMatch[1] === '-' ? -1 : 1;
    let rawValue = parseFloat(valueMatch[2].replace(',', ''));
    
    // If the text had "K", multiply by 1000
    if (/K/i.test(text)) {
      rawValue *= 1000;
    }
    
    const value = sign * rawValue;

    // Determine gamma type from color
    // Positive gamma: green/yellow hues | Negative gamma: blue/purple hues
    const bgColor = getComputedBackgroundColor(element);
    const gammaType = classifyGammaFromColor(bgColor);

    // Check if this is a King node (★ marker or highest value)
    const isKing = /★|\*/.test(text);

    return {
      strike: strike,
      value: value,
      value_display: valueMatch[0],
      gamma_type: gammaType,
      is_king: isKing,
      bg_color: bgColor,
    };
  }

  /**
   * Get the effective background color of an element or its colored bar child.
   */
  function getComputedBackgroundColor(element) {
    // The color bar might be a child element
    const colorBar = element.querySelector('[class*="bar"], [class*="cell"], [class*="fill"], [style*="background"]');
    const target = colorBar || element;
    
    const style = window.getComputedStyle(target);
    const bg = style.backgroundColor;
    
    if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') {
      return bg;
    }

    // Walk up parents to find the colored container
    let parent = element.parentElement;
    for (let i = 0; i < 3 && parent; i++) {
      const parentBg = window.getComputedStyle(parent).backgroundColor;
      if (parentBg && parentBg !== 'rgba(0, 0, 0, 0)' && parentBg !== 'transparent') {
        return parentBg;
      }
      parent = parent.parentElement;
    }

    return null;
  }

  /**
   * Classify gamma type (positive/negative) from an RGB color string.
   * Green/yellow = positive gamma, Blue/purple = negative gamma
   */
  function classifyGammaFromColor(colorStr) {
    if (!colorStr) return 'unknown';

    // Parse rgb(r, g, b) or rgba(r, g, b, a)
    const match = colorStr.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
    if (!match) return 'unknown';

    const r = parseInt(match[1]);
    const g = parseInt(match[2]);
    const b = parseInt(match[3]);

    // Simple heuristic:
    // Green/yellow dominant = positive gamma (absorption)
    // Blue/purple dominant = negative gamma (amplification)
    
    if (g > r && g > b) return 'positive';       // Green dominant
    if (r > 150 && g > 150 && b < 100) return 'positive'; // Yellow
    if (b > r && b > g) return 'negative';        // Blue dominant
    if (r > 100 && b > 100 && g < 100) return 'negative'; // Purple
    
    // Edge cases
    if (g > 100 && b > 100 && r < 80) return 'positive';  // Teal/cyan → positive
    if (r > g && r > b) return 'negative';         // Red-ish → likely negative

    return 'unknown';
  }

  /**
   * Brute-force text scan fallback.
   * Extracts all visible text that looks like heatmap data.
   */
  function bruteForceTextScan() {
    const body = document.body.innerText;
    const lines = body.split('\n').map(l => l.trim()).filter(l => l.length > 0);
    
    const data = {
      tickers_found: [],
      potential_nodes: [],
      raw_lines: [],
    };

    const tickerPattern = /^(SPXW|SPY|QQQ|IWM|VIX)\b/;
    const nodePattern = /(\d{3,5})\s+([-]?\$[\d,]+\.?\d*K?\*?★?)/;

    for (const line of lines) {
      if (tickerPattern.test(line)) {
        data.tickers_found.push(line.substring(0, 100));
      }

      const nodeMatch = line.match(nodePattern);
      if (nodeMatch) {
        data.potential_nodes.push({
          strike: parseInt(nodeMatch[1]),
          value_text: nodeMatch[2],
          full_line: line.substring(0, 150),
        });
      }

      // Keep lines that look like they contain heatmap data
      if (/\d{3,5}.*\$/.test(line)) {
        data.raw_lines.push(line.substring(0, 200));
      }
    }

    return data;
  }


  // ─── Message Handler ───────────────────────────────────────────

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
        try {
          const data = scrapeHeatmapData();
          sendResponse({ available: true, data: data });
        } catch (err) {
          console.error('[Heatseeker] Scrape error:', err);
          sendResponse({ 
            available: false, 
            error: err.message 
          });
        }
        break;

      default:
        sendResponse({ error: 'Unknown action' });
    }
    return true;
  });

})();
