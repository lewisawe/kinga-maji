/* Kinga Maji — shared risk-scale helpers (single source of truth for both pages).
   Presentation only: no payload or endpoint logic lives here. */
(function (global) {
  'use strict';

  // Engine category_key -> { cssVar (CSS custom property name), label, onInk }.
  // Keys are the EXACT engine category keys. onInk flags swatches that need
  // dark ink (amber) instead of white for >=4.5:1 contrast.
  var CATEGORY = {
    nuisance:        { cssVar: '--risk-nuisance',   label: 'Passable — nuisance water' },
    ankle:           { cssVar: '--risk-ankle',      label: 'Ankle deep — caution', onInk: 'dark' },
    impassable_boda: { cssVar: '--risk-impassable', label: 'Impassable for boda' },
    dangerous:       { cssVar: '--risk-dangerous',  label: 'Dangerous current' },
    evacuate:        { cssVar: '--risk-evacuate',   label: 'Evacuate now' },
    error:           { cssVar: '--risk-neutral',    label: 'Unknown' },
    unknown:         { cssVar: '--risk-neutral',    label: 'Unknown' }
  };

  function entry(key) {
    return CATEGORY[key] || CATEGORY.unknown;
  }

  // Resolve the risk color to a concrete value from the CSS custom property,
  // falling back to --risk-neutral. Works even before paint by reading :root.
  function riskColor(key) {
    var cssVar = entry(key).cssVar;
    var val = '';
    try {
      val = getComputedStyle(document.documentElement).getPropertyValue(cssVar);
    } catch (e) { /* ignore */ }
    val = (val || '').trim();
    if (val) return val;
    // Hard fallback values (match kinga.css) if computed style is unavailable.
    var FALLBACK = {
      '--risk-nuisance':   '#10B981',
      '--risk-ankle':      '#FBBF24',
      '--risk-impassable': '#F97316',
      '--risk-dangerous':  '#DC2626',
      '--risk-evacuate':   '#7F1D1D',
      '--risk-neutral':    '#475569'
    };
    return FALLBACK[cssVar] || FALLBACK['--risk-neutral'];
  }

  // Ink color to place on top of a risk swatch (dark on amber, white elsewhere).
  function riskInk(key) {
    return entry(key).onInk === 'dark' ? '#3F2D00' : '#FFFFFF';
  }

  function riskLabel(key) {
    return entry(key).label;
  }

  // Copied verbatim from the original tool page.
  function timeAgo(iso) {
    if (!iso) return '';
    try {
      var t = new Date(iso).getTime();
      if (isNaN(t)) return iso;
      var diff = Math.max(0, Date.now() - t);
      var mins = Math.round(diff / 60000);
      if (mins < 1) return 'just now';
      if (mins < 60) return mins + ' min ago';
      var hrs = Math.round(mins / 60);
      if (hrs < 24) return hrs + ' h ago';
      return Math.round(hrs / 24) + ' d ago';
    } catch (e) { return iso; }
  }

  // Format a rainfall value in mm honestly: 0 -> "0 mm", 31 -> "31 mm",
  // 12.4 -> "12.4 mm", null/NaN -> "—". Never fabricates a number.
  function fmtMm(n) {
    if (n == null) return '—';
    var v = Number(n);
    if (!isFinite(v)) return '—';
    return v.toFixed(v % 1 ? 1 : 0) + ' mm';
  }

  // Recent rainfall (last ~72h) in mm for a lat/lon, pulled LIVE from the FREE,
  // no-key Open-Meteo forecast API (third-party origin, CORS-open). Returns a
  // Promise<number|null>: a finite summed total on success, or null on ANY
  // network/parse error. Never throws, never fabricates. Coerces string coords.
  function recentRainfallMm(lat, lon) {
    var la = Number(lat), lo = Number(lon);
    if (!isFinite(la) || !isFinite(lo)) return Promise.resolve(null);
    var url = 'https://api.open-meteo.com/v1/forecast' +
      '?latitude=' + encodeURIComponent(la) +
      '&longitude=' + encodeURIComponent(lo) +
      '&hourly=precipitation&past_days=3&forecast_days=1' +
      '&timezone=Africa%2FNairobi';
    return fetch(url).then(function (res) {
      if (!res.ok) return null;
      return res.json();
    }).then(function (data) {
      if (!data || !data.hourly) return null;
      var times = data.hourly.time;
      var precip = data.hourly.precipitation;
      if (!Array.isArray(times) || !Array.isArray(precip)) return null;
      var now = Date.now();
      // Keep only entries whose timestamp is <= now, then the last 72 of those.
      var past = [];
      for (var i = 0; i < times.length && i < precip.length; i++) {
        var t = new Date(times[i]).getTime();
        if (!isNaN(t) && t <= now) {
          past.push(precip[i]);
        }
      }
      if (past.length === 0) return null;
      var recent = past.slice(-72);
      var sum = 0, seen = false;
      for (var j = 0; j < recent.length; j++) {
        var v = Number(recent[j]);
        if (isFinite(v)) { sum += v; seen = true; }
      }
      if (!seen) return null;
      return Math.round(sum * 10) / 10;
    }).catch(function () {
      return null;
    });
  }

  global.Kinga = {
    CATEGORY: CATEGORY,
    riskColor: riskColor,
    riskInk: riskInk,
    riskLabel: riskLabel,
    timeAgo: timeAgo,
    fmtMm: fmtMm,
    recentRainfallMm: recentRainfallMm
  };
})(window);
