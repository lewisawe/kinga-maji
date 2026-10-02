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

  global.Kinga = {
    CATEGORY: CATEGORY,
    riskColor: riskColor,
    riskInk: riskInk,
    riskLabel: riskLabel,
    timeAgo: timeAgo
  };
})(window);
