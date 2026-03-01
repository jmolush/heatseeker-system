// Heatseeker Capture — Content Script
// Injected into app.skylit.ai pages
// Scrapes heatmap data from the DOM into structured JSON

(function() {
  'use strict';

  console.log('[Heatseeker] Content script loaded on Skylit');

  /**
   * Scrape all visible heatmap panels from Trinity Mode or single view.
   * 
   * DOM structure (as of Feb 2026):
   * - Each node row has a `data-strike-index` attribute
   * - Rows have inline `background-color: rgb(r, g, b)` for gamma coloring
   * - Dollar values are in <span class="tabular-nums"> with font-weight 700
   * - King nodes have a lucide-star SVG icon
   * - Strike prices are in the left cell (div.flex-shrink-0)
   * - Standard layout: 4 panels — SPXW, SPY, QQQ, VIX (Trinity + VIX gamma)
   */
  function scrapeHeatmapData() {
    const mode = detectMode();
    const result = {
      timestamp: new Date().toISOString(),
      url: window.location.href,
      mode: mode,
      panels: [],
      panel_count: 0,
      total_nodes: 0,
    };

    // For individual ticker mode, include the detected ticker info at top level
    if (mode === 'individual') {
      const tickerInfo = detectIndividualTicker();
      if (tickerInfo) {
        result.individual_ticker = tickerInfo.ticker;
        result.individual_price = tickerInfo.price;
        result.individual_change_pct = tickerInfo.changePct;
      }
    }

    // Find all ticker panels by looking for ticker header elements
    const panels = findPanels();

    for (const panelInfo of panels) {
      const panel = scrapePanel(panelInfo);
      if (panel) {
        result.panels.push(panel);
      }
    }

    result.panel_count = result.panels.length;
    result.total_nodes = result.panels.reduce((sum, p) => sum + p.nodes.length, 0);

    console.log(`[Heatseeker] Scraped ${result.panel_count} panels, ${result.total_nodes} total nodes`);
    return result;
  }

  /**
   * Detect what mode Skylit is in.
   * 
   * Three modes:
   * - trinity_plus / trinity / dual: Multi-column overlay (div.fixed.inset-0.z-40)
   * - individual: Single ticker heatmap page (ticker info button with z-index: 15)
   * - single: Fallback
   */
  function detectMode() {
    // Check for Trinity Mode overlay first
    const trinityOverlay = document.querySelector('div.fixed.inset-0.z-40');
    if (trinityOverlay) {
      const text = trinityOverlay.textContent || '';
      const panelMatch = text.match(/(\d+)\s*panels?/i);
      if (panelMatch) {
        const count = parseInt(panelMatch[1]);
        if (count >= 4) return 'trinity_plus';
        if (count === 3) return 'trinity';
        if (count === 2) return 'dual';
      }
      return 'trinity';
    }

    // Check for individual ticker page — the ticker info button
    // It's inside a div with z-index: 15 and contains ticker symbol + price
    const tickerInfo = detectIndividualTicker();
    if (tickerInfo) return 'individual';

    // Fallback: check body text for TRINITY keyword
    const bodyText = document.body.innerText;
    if (bodyText.includes('TRINITY')) return 'trinity';

    return 'single';
  }

  /**
   * Detect the active ticker on individual ticker pages.
   * 
   * DOM structure (as of March 2026):
   * The ticker info button lives inside a div with style "z-index: 15".
   * Inside the button:
   *   <span style="font-weight: 600; font-family: 'Roboto Mono'...">AMD</span>
   *   <span style="background-color: rgb(34, 197, 94)">  (green dot)
   *   <span class="hidden sm:inline">$</span>
   *   <span class="hidden md:inline">199.36</span>
   *   <span class="hidden lg:inline">-3.30</span>   (change, red/green bg)
   *   <span class="hidden lg:inline">(-1.62%)</span>
   *
   * Returns: { ticker, price, change, changePct } or null
   */
  function detectIndividualTicker() {
    // Strategy 1: Find the ticker info button via z-index: 15 container
    const allDivs = document.querySelectorAll('div[style*="z-index"]');
    for (const div of allDivs) {
      if (!div.style.zIndex || parseInt(div.style.zIndex) !== 15) continue;

      const button = div.querySelector('button');
      if (!button) continue;

      const spans = button.querySelectorAll('span');
      if (spans.length < 2) continue;

      // First span should be the ticker symbol (short, all-caps, monospace font)
      const firstSpan = spans[0];
      const tickerText = firstSpan.textContent.trim();
      const style = firstSpan.getAttribute('style') || '';

      // Validate: ticker is 1-5 uppercase letters, monospace font, font-weight 600+
      if (!/^[A-Z]{1,5}$/.test(tickerText)) continue;
      if (!style.includes('Roboto Mono') && !style.includes('monospace')) continue;

      const result = { ticker: tickerText, price: null, change: null, changePct: null };

      // Extract price and change from subsequent spans
      for (const span of spans) {
        const text = span.textContent.trim();

        // Price: digits with optional comma and decimal (e.g., "199.36" or "5,678.88")
        if (!result.price && /^[\d,]+\.\d{2}$/.test(text)) {
          result.price = parseFloat(text.replace(/,/g, ''));
        }

        // Change amount: signed number (e.g., "-3.30" or "+2.50")
        if (!result.change && /^[+-]?\d+\.\d+$/.test(text) && result.price && parseFloat(text) !== result.price) {
          result.change = parseFloat(text);
        }

        // Change percentage: parenthesized or with % (e.g., "(-1.62%)" or "-1.62%")
        const pctMatch = text.match(/\(?([-+]?\d+\.\d+)%\)?/);
        if (!result.changePct && pctMatch) {
          result.changePct = parseFloat(pctMatch[1]);
        }
      }

      return result;
    }

    // Strategy 2: Fallback — look for any button with Roboto Mono ticker + green dot pattern
    const buttons = document.querySelectorAll('button');
    for (const button of buttons) {
      const spans = button.querySelectorAll('span');
      if (spans.length < 3) continue;

      const firstSpan = spans[0];
      const tickerText = firstSpan.textContent.trim();
      const style = firstSpan.getAttribute('style') || '';

      if (!/^[A-Z]{1,5}$/.test(tickerText)) continue;
      if (!style.includes('font-weight') || !style.includes('monospace') && !style.includes('Roboto Mono')) continue;

      // Check for green dot (second span with small width/height and green bg)
      const secondSpan = spans[1];
      const secondStyle = secondSpan.getAttribute('style') || '';
      if (!secondStyle.includes('border-radius: 50%') && !secondStyle.includes('border-radius:50%')) continue;

      const result = { ticker: tickerText, price: null, change: null, changePct: null };

      for (const span of spans) {
        const text = span.textContent.trim();
        if (!result.price && /^[\d,]+\.\d{2}$/.test(text)) {
          result.price = parseFloat(text.replace(/,/g, ''));
        }
        const pctMatch = text.match(/\(?([-+]?\d+\.\d+)%\)?/);
        if (!result.changePct && pctMatch) {
          result.changePct = parseFloat(pctMatch[1]);
        }
      }

      return result;
    }

    return null;
  }

  /**
   * Find panel containers.
   * 
   * In Trinity Mode: 3-4 side-by-side panels (SPXW, SPY, QQQ, VIX).
   * In Individual Mode: Single panel for whatever ticker is active.
   * 
   * Returns array of { ticker, headerElement, container } objects.
   */
  function findPanels() {
    const mode = detectMode();

    // ── Individual Ticker Mode ─────────────────────────────
    if (mode === 'individual') {
      return findIndividualPanel();
    }

    // ── Trinity / Multi-Column Mode ────────────────────────
    return findTrinityPanels();
  }

  /**
   * Find the single panel in individual ticker mode.
   * Uses the detected ticker from the info button, then finds the heatmap table.
   *
   * Individual ticker pages use a TABLE layout (not data-strike-index divs):
   *   <table> → <thead> (expiry date headers) → <tbody> → <tr id="strike-row-XX">
   *   First <td> = strike price, subsequent <td>s = expiry column values
   *   Values in <div data-velocity-key="STRIKE_DATE">$XXK</div>
   */
  function findIndividualPanel() {
    const tickerInfo = detectIndividualTicker();
    if (!tickerInfo) return [];

    // Strategy 1: Find the heatmap table by looking for tr[id^="strike-row-"]
    const strikeRows = document.querySelectorAll('tr[id^="strike-row-"]');
    if (strikeRows.length > 0) {
      // Walk up to the <table> or <tbody>
      let container = strikeRows[0].closest('table') || strikeRows[0].closest('tbody');
      if (!container) container = strikeRows[0].parentElement;

      return [{
        ticker: tickerInfo.ticker,
        headerElement: null,
        container: container,
        tickerInfo: tickerInfo,
        isTableLayout: true,  // Signal that this is the table-based layout
      }];
    }

    // Strategy 2: Fallback to data-strike-index (in case DOM changes back)
    const allRows = document.querySelectorAll('[data-strike-index]');
    if (allRows.length === 0) return [];

    let container = findPanelContainer(allRows[0]);
    if (!container) {
      container = allRows[0].parentElement;
      while (container && container.querySelectorAll('[data-strike-index]').length < allRows.length * 0.5) {
        container = container.parentElement;
      }
    }

    if (!container) return [];

    return [{
      ticker: tickerInfo.ticker,
      headerElement: null,
      container: container,
      tickerInfo: tickerInfo,
      isTableLayout: false,
    }];
  }

  /**
   * Find panels in Trinity / multi-column mode.
   * Searches for known index tickers in panel headers.
   */
  function findTrinityPanels() {
    const panels = [];
    const tickers = ['SPXW', 'SPY', 'QQQ', 'IWM', 'VIX', 'NDX', 'RUT'];

    // Find all elements that contain just a ticker name
    // These are typically buttons or spans in the panel header
    const allElements = document.querySelectorAll('button, span, div, select');

    for (const el of allElements) {
      const text = el.textContent.trim();
      if (!tickers.includes(text)) continue;
      if (!el.offsetParent) continue; // Skip hidden elements

      // Walk up to find the panel container
      // The panel container holds both the header and all the node rows
      let container = findPanelContainer(el);
      if (!container) continue;

      // Avoid duplicates
      if (panels.some(p => p.container === container)) continue;

      panels.push({
        ticker: text,
        headerElement: el,
        container: container,
      });
    }

    return panels;
  }

  /**
   * Walk up from a ticker label to find the panel container.
   * The container is the element that holds both the header and all data-strike-index rows.
   */
  function findPanelContainer(el) {
    let current = el.parentElement;
    for (let i = 0; i < 15 && current; i++) {
      // Check if this element contains data-strike-index rows
      const rows = current.querySelectorAll('[data-strike-index]');
      if (rows.length > 10) {
        return current;
      }
      current = current.parentElement;
    }
    return null;
  }

  /**
   * Scrape a single panel's data.
   */
  function scrapePanel(panelInfo) {
    const { ticker, headerElement, container } = panelInfo;

    const panel = {
      ticker: ticker,
      price: null,
      change_pct: null,
      king_pct: null,
      nodes: [],
      node_count: 0,
      king_node: null,
    };

    // ─── Header Info ─────────────────────────────────────
    // In individual mode, tickerInfo already has price/change from the info button
    if (panelInfo.tickerInfo) {
      panel.price = panelInfo.tickerInfo.price;
      panel.change_pct = panelInfo.tickerInfo.changePct;
    }

    // For Trinity mode (or as fallback), extract from the header area
    if (headerElement) {
      let headerArea = headerElement;
      for (let i = 0; i < 5; i++) {
        headerArea = headerArea.parentElement;
        if (!headerArea) break;
        const text = headerArea.textContent;
        
        // Look for price pattern: $X,XXX.XX or XXXX.XX
        if (!panel.price) {
          const priceMatch = text.match(/\$?([\d,]+\.\d{2})\b/);
          if (priceMatch) {
            panel.price = parseFloat(priceMatch[1].replace(/,/g, ''));
          }
        }

        // Change percentage
        if (!panel.change_pct) {
          const changeMatch = text.match(/([-+]?\d+\.\d+)%/);
          if (changeMatch) {
            panel.change_pct = parseFloat(changeMatch[1]);
          }
        }

        // King percentage (shown as "King X.X% ↑/↓")
        if (!panel.king_pct) {
          const kingMatch = text.match(/King\s+([\d.]+)%?\s*([↑↓]?)/i);
          if (kingMatch) {
            panel.king_pct = kingMatch[1] + '%' + (kingMatch[2] || '');
          }
        }

        // Don't go beyond the panel container
        if (headerArea === container) break;
      }
    }

    // ─── Node Rows ───────────────────────────────────────
    // Individual ticker table layout: tr[id^="strike-row-"] with expiry columns
    // Trinity Mode layout: divs with data-strike-index attribute
    if (panelInfo.isTableLayout) {
      // Table layout — individual ticker page
      const tableData = parseTableLayout(container);
      panel.nodes = tableData.nodes;
      panel.expiry_dates = tableData.expiryDates;
      panel.current_strike = tableData.currentStrike;
    } else {
      // Original data-strike-index layout (Trinity Mode)
      const rows = container.querySelectorAll('[data-strike-index]');
      for (const row of rows) {
        const node = parseNodeRow(row);
        if (node) {
          panel.nodes.push(node);
        }
      }
    }

    // Sort by strike descending (highest first)
    panel.nodes.sort((a, b) => b.strike - a.strike);
    panel.node_count = panel.nodes.length;

    // Identify king node (highest absolute value, or marked with star)
    const starNode = panel.nodes.find(n => n.is_king);
    if (starNode) {
      panel.king_node = {
        strike: starNode.strike,
        value: starNode.value,
        gamma_type: starNode.gamma_type,
      };
    } else if (panel.nodes.length > 0) {
      // Fallback: highest absolute value
      const biggest = panel.nodes.reduce((max, n) =>
        Math.abs(n.value) > Math.abs(max.value) ? n : max
      );
      panel.king_node = {
        strike: biggest.strike,
        value: biggest.value,
        gamma_type: biggest.gamma_type,
      };
    }

    return panel;
  }

  /**
   * Parse the table-based heatmap layout used on individual ticker pages.
   *
   * DOM structure:
   *   <table>
   *     <thead>
   *       <tr>
   *         <th>Strike</th>
   *         <th>2026-03-06</th>  ← expiry dates
   *         <th>2026-03-13</th>
   *         ...
   *       </tr>
   *     </thead>
   *     <tbody>
   *       <tr id="strike-row-91">
   *         <td style="...font-weight: 500..."><span>80.0</span></td>  ← strike price
   *         <td style="background-color: rgb(49,100,140)">
   *           <div data-velocity-key="80_2026-03-06">$2.4K</div>
   *         </td>
   *         ...
   *       </tr>
   *     </tbody>
   *   </table>
   *
   * Current price row: <td> with font-weight: 700 and white background
   * King node cell: has box-shadow inset and lucide-star SVG, font-weight: 700
   *
   * Returns { nodes: [...], expiryDates: [...], currentStrike: number|null }
   */
  function parseTableLayout(container) {
    const result = {
      nodes: [],
      expiryDates: [],
      currentStrike: null,
    };

    // Extract expiry dates from <thead>
    const table = container.tagName === 'TABLE' ? container : container.querySelector('table');
    if (!table) {
      // Fallback: container might be the tbody itself
      const headerRow = container.closest('table')?.querySelector('thead tr');
      if (headerRow) {
        const ths = headerRow.querySelectorAll('th');
        ths.forEach((th, i) => {
          if (i > 0) { // Skip "Strike" header
            result.expiryDates.push(th.textContent.trim());
          }
        });
      }
    } else {
      const headerRow = table.querySelector('thead tr');
      if (headerRow) {
        const ths = headerRow.querySelectorAll('th');
        ths.forEach((th, i) => {
          if (i > 0) result.expiryDates.push(th.textContent.trim());
        });
      }
    }

    // Parse each strike row
    const rows = (table || container).querySelectorAll('tr[id^="strike-row-"]');

    for (const row of rows) {
      const tds = row.querySelectorAll('td');
      if (tds.length < 2) continue;

      // First TD = strike price
      const strikeTd = tds[0];
      const strikeSpan = strikeTd.querySelector('span');
      const strikeText = strikeSpan ? strikeSpan.textContent.trim() : strikeTd.textContent.trim();
      const strike = parseFloat(strikeText);
      if (isNaN(strike)) continue;

      // Detect if this is the current price row (white bg, bold font)
      const strikeTdStyle = strikeTd.getAttribute('style') || '';
      if (strikeTdStyle.includes('font-weight: 700') && strikeTdStyle.includes('rgb(255, 255, 255)')) {
        result.currentStrike = strike;
      }

      // Parse each expiry column (td index 1+)
      const expiryValues = [];
      let rowKingCell = null;

      for (let i = 1; i < tds.length; i++) {
        const td = tds[i];
        const velocityDiv = td.querySelector('[data-velocity-key]');
        const cellText = velocityDiv ? velocityDiv.textContent.trim() : td.textContent.trim();

        // Parse dollar value
        const value = parseDollarValue(cellText);

        // Background color from the TD
        const bgColor = td.style.backgroundColor || null;
        const gammaType = classifyGamma(bgColor);

        // King marker: star SVG inside the cell
        const hasStar = td.querySelector('[class*="lucide-star"], .lucide-star') !== null;
        // Also check for bold font-weight on the cell (king cells have font-weight: 700)
        const tdStyle = td.getAttribute('style') || '';
        const isBold = tdStyle.includes('font-weight: 700');
        const isKing = hasStar;

        // Extract expiry date from velocity key (e.g., "80_2026-03-06" → "2026-03-06")
        let expiryDate = result.expiryDates[i - 1] || null;
        if (!expiryDate && velocityDiv) {
          const vKey = velocityDiv.getAttribute('data-velocity-key') || '';
          const dateMatch = vKey.match(/\d{4}-\d{2}-\d{2}/);
          if (dateMatch) expiryDate = dateMatch[0];
        }

        expiryValues.push({
          expiry_date: expiryDate,
          value: value,
          value_display: cellText,
          gamma_type: gammaType,
          bg_color_rgb: bgColor,
          is_king: isKing,
        });

        if (isKing) rowKingCell = expiryValues[expiryValues.length - 1];
      }

      // Build the node object — includes all expiry columns
      const node = {
        strike: strike,
        strike_index: parseInt(row.id.replace('strike-row-', '')) || null,
        expiry_values: expiryValues,
        // For backward compatibility, also set aggregate values:
        // Use the nearest-dated expiry with the largest absolute value as the "main" value
        value: null,
        value_display: '',
        gamma_type: 'unknown',
        is_king: false,
        bg_color_rgb: null,
      };

      // Find the most significant cell (largest absolute value) for the aggregate fields
      let maxAbsValue = 0;
      for (const ev of expiryValues) {
        if (ev.value !== null && Math.abs(ev.value) > maxAbsValue) {
          maxAbsValue = Math.abs(ev.value);
          node.value = ev.value;
          node.value_display = ev.value_display;
          node.gamma_type = ev.gamma_type;
          node.bg_color_rgb = ev.bg_color_rgb;
        }
        if (ev.is_king) {
          node.is_king = true;
          // King overrides aggregate value
          node.value = ev.value;
          node.value_display = ev.value_display;
          node.gamma_type = ev.gamma_type;
          node.bg_color_rgb = ev.bg_color_rgb;
        }
      }

      result.nodes.push(node);
    }

    return result;
  }

  /**
   * Parse a single node row element into structured data (Trinity Mode / data-strike-index layout).
   * 
   * Row structure:
   * - data-strike-index="XX" attribute
   * - Inline background-color style for gamma coloring
   * - <span class="tabular-nums" style="font-weight: 700"> for dollar value
   * - SVG with lucide-star class for King marker
   * - Strike price as text content
   */
  function parseNodeRow(row) {
    const text = row.textContent.trim();
    const strikeIndex = row.getAttribute('data-strike-index');

    // Extract strike price from the left-side label cell
    // SPXW: 3-5 digits (e.g. 6935), SPY/QQQ: 3 digits (e.g. 690, 687)
    // VIX: 1-3 digits, possibly decimal (e.g. 20, 19.5, 150)
    const leftCell = row.querySelector('.flex-shrink-0');
    const strikeText = leftCell ? leftCell.textContent.trim() : text;
    const strikeMatch = strikeText.match(/\b(\d{1,5}(?:\.\d+)?)\b/);
    if (!strikeMatch) return null;
    const strike = parseFloat(strikeMatch[1]);

    // Extract dollar value from the value cell (flex-1 div) or tabular-nums spans
    let value = null;
    let valueDisplay = '';

    // Get the value cell — this contains the dollar amount and sign
    const valueCell = row.querySelector('.flex-1, [class*="flex-1"]');
    
    // Try tabular-nums spans first (most reliable for the number)
    const valueSpans = row.querySelectorAll('.tabular-nums, [class*="tabular"]');
    for (const span of valueSpans) {
      const spanText = span.textContent.trim();
      const parsed = parseDollarValue(spanText);
      if (parsed !== null) {
        value = parsed;
        valueDisplay = spanText;
        break;
      }
    }

    // Double-check: if value is positive, look at the full value cell text
    // The minus sign might be outside the tabular-nums span, or the span's
    // textContent might not include it due to DOM structure
    if (value !== null && value >= 0 && valueCell) {
      const cellText = valueCell.textContent.trim();
      // Look for ANY negative indicator before or near the dollar amount
      // Check first few chars for minus-like characters
      const firstChars = cellText.substring(0, 5);
      const hasNegative = /[-–−\u2212\u2010\u2011\u2012\u2013\u2014\u2015]/.test(firstChars);
      if (hasNegative) {
        value = -Math.abs(value);
        if (!valueDisplay.startsWith('-')) {
          valueDisplay = '-' + valueDisplay;
        }
      }
    }

    // Fallback: scan all text for dollar pattern
    if (value === null) {
      const dollarMatch = text.match(/([-–−]?\$[\d,]+\.?\d*K?)\s*[★*]?/);
      if (dollarMatch) {
        value = parseDollarValue(dollarMatch[1]);
        valueDisplay = dollarMatch[1];
      }
    }

    if (value === null) return null;

    // Background color — inline style on the row or a child
    const bgColor = extractBackgroundColor(row);
    const gammaType = classifyGamma(bgColor);

    // King node marker — look for star SVG (lucide-star class)
    const hasStar = row.querySelector('[class*="lucide-star"], .lucide-star') !== null;
    // Also check for ★ or * character after the value
    const isKing = hasStar || /[★*]/.test(text.slice(text.indexOf('$')));

    return {
      strike: strike,
      strike_index: strikeIndex ? parseInt(strikeIndex) : null,
      value: value,
      value_display: valueDisplay,
      gamma_type: gammaType,
      is_king: isKing,
      bg_color_rgb: bgColor,
    };
  }

  /**
   * Parse a dollar value string into a number.
   * Handles: $1,234.5K, -$456.7K, $22,821.9K★, -$3,951.9K★
   */
  function parseDollarValue(str) {
    if (!str) return null;

    // Clean up — strip stars, arrows, quotes, whitespace
    let clean = str.replace(/[★*↑↓\s"""'']/g, '').trim();

    // Detect negative — handle every known minus-like character:
    // U+002D hyphen-minus, U+2010 hyphen, U+2011 non-breaking hyphen,
    // U+2012 figure dash, U+2013 en-dash, U+2014 em-dash, U+2015 horizontal bar,
    // U+2212 minus sign, U+FE63 small hyphen-minus, U+FF0D fullwidth hyphen-minus
    let negative = false;
    if (/^[\-–—−‐‑‒\u2212\uFE63\uFF0D]/.test(clean)) {
      negative = true;
      clean = clean.replace(/^[\-–—−‐‑‒\u2212\uFE63\uFF0D]+/, '');
    } else if (/^\(.*\)$/.test(clean)) {
      negative = true;
      clean = clean.replace(/^\(/, '').replace(/\)$/, '');
    }

    // Remove dollar sign
    clean = clean.replace(/\$/, '');

    // Check for K suffix (thousands)
    let multiplier = 1;
    if (/K$/i.test(clean)) {
      multiplier = 1000;
      clean = clean.replace(/K$/i, '');
    } else if (/M$/i.test(clean)) {
      multiplier = 1000000;
      clean = clean.replace(/M$/i, '');
    }

    // Remove commas
    clean = clean.replace(/,/g, '');

    const num = parseFloat(clean);
    if (isNaN(num)) return null;

    return (negative ? -1 : 1) * num * multiplier;
  }

  /**
   * Extract the gamma background color from the value cell (not the row).
   * 
   * Row structure:
   *   <div data-strike-index="95">          ← row (bg: rgb(10,10,10) = dark theme)
   *     <div class="flex-shrink-0">         ← strike label (bg: rgb(10,10,10))
   *     <div class="flex-1">               ← VALUE CELL — this has the gamma color!
   *       <span class="tabular-nums">      ← dollar value
   *
   * We need the flex-1 child's background, NOT the row's.
   */
  function extractBackgroundColor(el) {
    // Target the value cell directly — it's the flex-1 child with the gamma color
    const valueCell = el.querySelector('.flex-1, [class*="flex-1"]');
    if (valueCell) {
      // Check inline style first (Skylit sets it inline)
      if (valueCell.style.backgroundColor) {
        return valueCell.style.backgroundColor;
      }
      const computed = window.getComputedStyle(valueCell);
      const bg = computed.backgroundColor;
      if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') {
        return bg;
      }
    }

    // Fallback: check all children for any non-dark background
    const darkBg = 'rgb(10, 10, 10)';
    for (const child of el.children) {
      if (child.style.backgroundColor && child.style.backgroundColor !== darkBg) {
        return child.style.backgroundColor;
      }
      const childBg = window.getComputedStyle(child).backgroundColor;
      if (childBg && childBg !== 'rgba(0, 0, 0, 0)' && childBg !== 'transparent' && childBg !== darkBg) {
        return childBg;
      }
    }

    // Last resort: row itself (but skip near-black theme colors)
    if (el.style.backgroundColor && el.style.backgroundColor !== darkBg) {
      return el.style.backgroundColor;
    }

    return null;
  }

  /**
   * Classify gamma type from RGB color.
   * 
   * From the screenshot:
   * - Bright green (rgb(121, 206, 79)) = strong positive gamma
   * - Dark green/teal = moderate positive gamma
   * - Dark blue/purple = negative gamma
   * - The brighter/more saturated, the stronger the value
   */
  function classifyGamma(colorStr) {
    if (!colorStr) return 'unknown';

    const match = colorStr.match(/rgba?\(\s*(\d+),\s*(\d+),\s*(\d+)/);
    if (!match) return 'unknown';

    const r = parseInt(match[1]);
    const g = parseInt(match[2]);
    const b = parseInt(match[3]);

    // Convert to HSL for better classification
    const { h, s, l } = rgbToHsl(r, g, b);

    // Green/yellow hues (60-180) = positive gamma (absorption/pinning)
    // Blue/purple hues (180-300) = negative gamma (amplification)
    if (h >= 60 && h <= 180) return 'positive';
    if (h >= 180 && h <= 300) return 'negative';
    if (h < 60 && h >= 30) return 'positive';  // Yellow-green
    if (h > 300) return 'negative';              // Magenta/red-purple

    // Low saturation = near the boundary
    if (s < 0.15) return 'neutral';

    return 'unknown';
  }

  /**
   * Convert RGB to HSL.
   */
  function rgbToHsl(r, g, b) {
    r /= 255; g /= 255; b /= 255;
    const max = Math.max(r, g, b);
    const min = Math.min(r, g, b);
    let h, s, l = (max + min) / 2;

    if (max === min) {
      h = s = 0;
    } else {
      const d = max - min;
      s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
      switch (max) {
        case r: h = ((g - b) / d + (g < b ? 6 : 0)) / 6; break;
        case g: h = ((b - r) / d + 2) / 6; break;
        case b: h = ((r - g) / d + 4) / 6; break;
      }
    }

    return { h: h * 360, s, l };
  }


  // ─── Message Handler ───────────────────────────────────────────

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    switch (msg.action) {
      case 'getPageInfo':
        sendResponse({
          url: window.location.href,
          title: document.title,
          timestamp: new Date().toISOString(),
        });
        break;

      case 'getHeatmapData':
        try {
          const data = scrapeHeatmapData();
          sendResponse({ available: true, data: data });
        } catch (err) {
          console.error('[Heatseeker] Scrape error:', err);
          sendResponse({ available: false, error: err.message });
        }
        break;

      default:
        sendResponse({ error: 'Unknown action' });
    }
    return true;
  });

})();