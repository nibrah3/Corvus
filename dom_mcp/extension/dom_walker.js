/**
 * dom_walker.js — DOM extraction only. No network, no side effects.
 * Single responsibility: walk the live DOM and return a structured snapshot.
 *
 * Handles: shadow DOM (recursive), iframes (via all_frames manifest flag),
 * standard forms, reading passages, and frame identity metadata.
 *
 * Exposes: window.cbWalker.extract() → Object
 */
(function (global) {
  'use strict';

  // ── Shadow DOM-aware query ──────────────────────────────────────────────────
  // BFS through shadow roots so querySelectorAll pierces all shadow boundaries.

  function queryDeep(selector, root) {
    var results = [];
    var queue = [root || document];
    while (queue.length) {
      var node = queue.shift();
      Array.from(node.querySelectorAll(selector)).forEach(function (el) {
        results.push(el);
      });
      Array.from(node.querySelectorAll('*')).forEach(function (el) {
        if (el.shadowRoot) queue.push(el.shadowRoot);
      });
    }
    return results;
  }

  // ── Visibility & label helpers ──────────────────────────────────────────────

  function isVisible(el) {
    var s = getComputedStyle(el);
    return s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
  }

  function getLabel(el) {
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label').trim();
    if (el.getAttribute('aria-labelledby')) {
      var ref = (el.getRootNode() || document).getElementById
        ? (el.getRootNode()).getElementById(el.getAttribute('aria-labelledby'))
        : document.getElementById(el.getAttribute('aria-labelledby'));
      if (ref) return ref.textContent.trim();
    }
    if (el.id) {
      var lbl = document.querySelector('label[for="' + el.id + '"]');
      if (lbl) return lbl.textContent.trim();
    }
    var parent = el.closest('label');
    if (parent) return parent.textContent.trim();
    return (el.placeholder || el.name || el.id || '').trim();
  }

  // ── Extractors ──────────────────────────────────────────────────────────────

  function extractQuestions() {
    var seen = new Set();
    var results = [];

    function add(el, text) {
      if (!text || text.length < 5 || text.length > 2000 || seen.has(text)) return;
      seen.add(text);
      results.push({ tag: el.tagName.toLowerCase(), text: text });
    }

    queryDeep('legend, fieldset > p, [role="heading"]').forEach(function (el) {
      if (isVisible(el)) add(el, el.textContent.trim());
    });

    queryDeep('h1, h2, h3, h4').forEach(function (el) {
      if (isVisible(el)) add(el, el.textContent.trim());
    });

    queryDeep('p, [class*="question"], [class*="prompt"], [class*="stem"]').forEach(function (el) {
      if (!isVisible(el)) return;
      var text = el.textContent.trim();
      if (text.includes('?') && text.length >= 10 && text.length <= 1000) add(el, text);
    });

    return results;
  }

  function extractRadioGroups() {
    var groups = {};
    queryDeep('input[type="radio"]').forEach(function (el) {
      if (!isVisible(el)) return;
      var name = el.name || '__unnamed__';
      if (!groups[name]) groups[name] = { name: name, options: [] };
      groups[name].options.push({ value: el.value, label: getLabel(el), checked: el.checked });
    });
    return Object.values(groups);
  }

  function extractInputs() {
    var results = [];
    queryDeep('input, select, textarea').forEach(function (el) {
      if (!isVisible(el)) return;
      var type = (el.type || el.tagName).toLowerCase();
      if (type === 'hidden' || type === 'radio') return;

      var entry = {
        tag:      el.tagName.toLowerCase(),
        type:     type,
        name:     el.name,
        id:       el.id,
        label:    getLabel(el),
        value:    el.value,
        required: el.required,
      };

      if (el.tagName === 'SELECT') {
        entry.options = Array.from(el.options).map(function (o) {
          return { value: o.value, text: o.text.trim(), selected: o.selected };
        });
      }

      if (type === 'checkbox') entry.checked = el.checked;

      results.push(entry);
    });
    return results;
  }

  function extractButtons() {
    var results = [];
    queryDeep('button, input[type="submit"], input[type="button"], [role="button"]').forEach(function (el) {
      if (!isVisible(el)) return;
      var text = (el.textContent || el.value || '').trim();
      if (text) results.push({ tag: el.tagName.toLowerCase(), text: text, type: el.type || 'button' });
    });
    return results;
  }

  function extractPassage() {
    // Long text blocks: reading passages, instructions, question stems.
    // Uses shadow-aware query; skips containers (children > 5) to avoid duplication.
    var seen = new Set();
    var results = [];
    queryDeep('p, div, td, blockquote, article, section').forEach(function (el) {
      if (!isVisible(el)) return;
      if (el.children.length > 5) return;
      var text = el.textContent.trim();
      if (text.length < 80 || text.length > 8000 || seen.has(text)) return;
      seen.add(text);
      results.push(text);
    });
    return results;
  }

  // ── Main extract ────────────────────────────────────────────────────────────

  function extract() {
    var isTop = (window === window.top);
    return {
      url:          location.href,
      title:        document.title,
      timestamp:    Date.now(),
      isTopFrame:   isTop,
      frameUrl:     location.href,
      parentUrl:    isTop ? null : (document.referrer || null),
      questions:    extractQuestions(),
      radio_groups: extractRadioGroups(),
      inputs:       extractInputs(),
      buttons:      extractButtons(),
      passage:      extractPassage(),
    };
  }

  // ── Interactive elements with full ARIA + bounding rect ──────────────────────
  // Richer than extract() — used by CDP executor to get click coordinates
  // and by the LLM to understand interactive state without a screenshot.

  function extractInteractives() {
    var results = [];
    var seen = new Set();
    var idx = 0;

    function nodeId(el) {
      if (!el.__cbId) el.__cbId = 'cb-' + (++idx);
      return el.__cbId;
    }

    function rect(el) {
      var r = el.getBoundingClientRect();
      return { x: Math.round(r.left), y: Math.round(r.top),
               w: Math.round(r.width), h: Math.round(r.height),
               cx: Math.round(r.left + r.width / 2),
               cy: Math.round(r.top + r.height / 2) };
    }

    function ariaState(el) {
      var s = {};
      var attrs = ['checked','selected','disabled','expanded',
                   'required','pressed','invalid','readonly',
                   'multiselectable','haspopup'];
      attrs.forEach(function(a) {
        var v = el.getAttribute('aria-' + a);
        if (v !== null) s[a] = v === 'true' ? true : v === 'false' ? false : v;
      });
      // native checked/disabled/required
      if (el.type === 'checkbox' || el.type === 'radio') {
        s.checked  = el.checked;
        s.disabled = el.disabled;
        s.required = el.required;
      }
      if (el.tagName === 'SELECT') {
        s.disabled = el.disabled;
        s.required = el.required;
      }
      return s;
    }

    function role(el) {
      return el.getAttribute('role') ||
             { INPUT: el.type || 'input', SELECT: 'listbox',
               TEXTAREA: 'textbox', BUTTON: 'button',
               A: 'link' }[el.tagName] || el.tagName.toLowerCase();
    }

    var selectors = [
      'input:not([type="hidden"])',
      'select',
      'textarea',
      'button',
      '[role="button"]',
      '[role="radio"]',
      '[role="checkbox"]',
      '[role="option"]',
      '[role="tab"]',
      '[role="menuitem"]',
      '[role="switch"]',
      '[role="combobox"]',
      '[tabindex]:not([tabindex="-1"])',
    ].join(',');

    queryDeep(selectors).forEach(function(el) {
      if (!isVisible(el)) return;
      var id = nodeId(el);
      if (seen.has(id)) return;
      seen.add(id);

      var r = rect(el);
      if (r.w === 0 && r.h === 0) return;  // off-screen / display:none

      var entry = {
        id:          id,
        role:        role(el),
        tag:         el.tagName.toLowerCase(),
        type:        el.type || null,
        name:        getLabel(el),
        value:       el.value !== undefined ? el.value : null,
        text:        (el.textContent || '').trim().slice(0, 300),
        placeholder: el.placeholder || null,
        state:       ariaState(el),
        rect:        r,
        selector:    el.id ? '#' + CSS.escape(el.id)
                           : (el.name ? el.tagName.toLowerCase() + '[name="' + el.name + '"]' : null),
        testId:      el.getAttribute('data-testid') || el.getAttribute('data-cy') ||
                     el.getAttribute('data-test') || null,
      };

      if (el.tagName === 'SELECT') {
        entry.options = Array.from(el.options).map(function(o) {
          return { value: o.value, text: o.text.trim(), selected: o.selected };
        });
      }

      results.push(entry);
    });

    return results;
  }

  global.cbWalker = { extract: extract, extractInteractives: extractInteractives };

}(window));
