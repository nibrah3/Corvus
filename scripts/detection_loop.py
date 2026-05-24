"""
scripts/detection_loop.py — Bot detection audit + iterative patch loop.

Visits known detection benchmarks, scores each signal, applies patch layers,
and repeats until the score plateaus or all patches are exhausted.

Detection sites:
  1. bot.sannysoft.com      — classic CDP/Puppeteer signal table
  2. pixelscan.net          — consistency + bot marker scan
  3. arh.antoinevastel.com  — headless / automation detection
  4. browserleaks.com/js    — JS API fingerprint leaks
  5. abrahamjuliot.github.io/creepjs/ — deep fingerprint forensics

Usage:
    python scripts/detection_loop.py [--cdp ws://...] [--rounds N] [--site N]
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time

# Force UTF-8 output on Windows (avoids cp1252 charmap errors)
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

CB_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, CB_DIR)

with open(os.path.join(CB_DIR, ".env")) as _f:
    for _line in _f:
        _line = _line.strip()
        if "=" in _line and not _line.startswith("#"):
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

from careerbridge.cdp_executor import CDPExecutor
from careerbridge.stealth_patches import ALL_PATCHES, ASSESSMENT_EXTRA, build_bundle

# ── Colour helpers ────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def _ok(s):  return f"{GREEN}[OK] {s}{RESET}"
def _bad(s): return f"{RED}[!!] {s}{RESET}"
def _warn(s):return f"{YELLOW}[??] {s}{RESET}"
def _hdr(s): return f"{BOLD}{CYAN}{s}{RESET}"


# ── JS probes (direct eval, not relying on site rendering) ───────────────────

# Comprehensive JS probe that checks all known automation signals directly.
# Returns a dict with signal name → {value, detected} pairs.
DIRECT_PROBE_JS = r"""
(function() {
  var results = {};

  function probe(name, fn) {
    try { results[name] = fn(); }
    catch(e) { results[name] = '__error__:' + e.message; }
  }

  // ── navigator signals ──────────────────────────────────────────────────────
  probe('webdriver',          () => navigator.webdriver);
  probe('webdriver_type',     () => typeof navigator.webdriver);
  probe('plugins_count',      () => navigator.plugins.length);
  probe('languages_count',    () => (navigator.languages||[]).length);
  probe('language',           () => navigator.language);
  probe('hardware_concurrency',() => navigator.hardwareConcurrency);
  probe('device_memory',      () => navigator.deviceMemory);
  probe('platform',           () => navigator.platform);
  probe('do_not_track',       () => navigator.doNotTrack);
  probe('connection_type',    () => (navigator.connection||{}).effectiveType);

  // ── window.chrome ──────────────────────────────────────────────────────────
  probe('chrome_exists',      () => !!window.chrome);
  probe('chrome_runtime',     () => !!(window.chrome||{}).runtime);
  probe('chrome_loadtimes',   () => typeof (window.chrome||{}).loadTimes);
  probe('chrome_csi',         () => typeof (window.chrome||{}).csi);
  probe('chrome_app',         () => !!(window.chrome||{}).app);

  // ── screen / window geometry ───────────────────────────────────────────────
  probe('screen_width',       () => screen.width);
  probe('screen_height',      () => screen.height);
  probe('outer_width',        () => window.outerWidth);
  probe('outer_height',       () => window.outerHeight);
  probe('inner_width',        () => window.innerWidth);
  probe('inner_height',       () => window.innerHeight);
  probe('color_depth',        () => screen.colorDepth);
  probe('pixel_ratio',        () => window.devicePixelRatio);

  // ── timing / performance ───────────────────────────────────────────────────
  probe('perf_timing_valid',  () => performance.timing.navigationStart > 0);
  probe('perf_nav_type',      () => (performance.getEntriesByType('navigation')[0]||{}).type);

  // ── permissions ────────────────────────────────────────────────────────────
  probe('notification_perm',  () => (typeof Notification !== 'undefined') ? Notification.permission : 'N/A');

  // ── automation globals ─────────────────────────────────────────────────────
  probe('cdc_vars', () => Object.keys(window).filter(k => k.startsWith('cdc_') || k.includes('__webdriver') || k.includes('__driver_evaluate')).length);
  probe('phantom',    () => !!(window.callPhantom || window._phantom));
  probe('nightmare',  () => !!window.__nightmare);

  // ── Event isTrusted ────────────────────────────────────────────────────────
  probe('istrusted_spoofed', () => {
    var e = new MouseEvent('click');
    return e.isTrusted;
  });

  // ── iframe webdriver cross-frame ───────────────────────────────────────────
  probe('iframe_webdriver', () => {
    try {
      var f = document.createElement('iframe');
      f.style.display = 'none';
      document.body.appendChild(f);
      var wd = f.contentWindow.navigator.webdriver;
      document.body.removeChild(f);
      return wd;
    } catch(e) { return '__error__'; }
  });

  // ── WebRTC ─────────────────────────────────────────────────────────────────
  probe('webrtc_exists', () => !!(window.RTCPeerConnection || window.webkitRTCPeerConnection));

  // ── speech synthesis ───────────────────────────────────────────────────────
  probe('speech_voices', () => (window.speechSynthesis||{getVoices:()=>[]}).getVoices().length);

  // ── Error stack normalcy ───────────────────────────────────────────────────
  probe('error_stack_clean', () => {
    try { throw new Error('test'); } catch(e) {
      return !(e.stack||'').match(/puppeteer|playwright|__pw/i);
    }
  });

  // ── User activation ────────────────────────────────────────────────────────
  probe('user_activation_active', () => {
    if (!window.userActivation) return 'N/A';
    return window.userActivation.isActive;
  });
  probe('user_activation_been', () => {
    if (!window.userActivation) return 'N/A';
    return window.userActivation.hasBeenActive;
  });

  // ── Worker constructor (sync check — is it patched?)  ─────────────────────
  probe('worker_patched', () => {
    if (!window.Worker) return 'absent';
    // Native Worker.toString() → 'function Worker() { [native code] }'
    // Our proxy shows custom code
    var s = Function.prototype.toString.call(window.Worker);
    return s.includes('[native code]') ? 'native_unpatched' : 'proxy_patched';
  });

  // ── Intl/language timezone consistency ─────────────────────────────────────
  probe('intl_tz', () => Intl.DateTimeFormat().resolvedOptions().timeZone);
  probe('intl_locale', () => Intl.DateTimeFormat().resolvedOptions().locale);

  // ── Canvas fingerprint presence ────────────────────────────────────────────
  probe('canvas_supported', () => {
    var c = document.createElement('canvas');
    return !!(c.getContext && c.getContext('2d'));
  });

  // ── WebGL strings ──────────────────────────────────────────────────────────
  probe('webgl_vendor', () => {
    try {
      var c = document.createElement('canvas');
      var gl = c.getContext('webgl') || c.getContext('experimental-webgl');
      var ext = gl && gl.getExtension('WEBGL_debug_renderer_info');
      return ext ? gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) : 'N/A';
    } catch(e) { return 'error'; }
  });
  probe('webgl_renderer', () => {
    try {
      var c = document.createElement('canvas');
      var gl = c.getContext('webgl') || c.getContext('experimental-webgl');
      var ext = gl && gl.getExtension('WEBGL_debug_renderer_info');
      return ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : 'N/A';
    } catch(e) { return 'error'; }
  });

  return results;
})()
"""

# ── Signal scoring rules ──────────────────────────────────────────────────────

def _score_signals(sig: dict) -> list[tuple[str, bool, str]]:
    """
    Return list of (signal_name, passed, detail) tuples.
    passed=True means the signal looks human (no detection).
    """
    results = []

    def chk(name: str, condition: bool, detail: str = ""):
        results.append((name, condition, detail))

    v = sig  # shorthand

    chk("webdriver=false",
        v.get("webdriver") is False or v.get("webdriver") is None,
        f"navigator.webdriver={v.get('webdriver')!r}")

    chk("webdriver_undefined_type",
        v.get("webdriver_type") in ("undefined", "boolean"),
        f"type={v.get('webdriver_type')!r}")

    chk("plugins_populated",
        (v.get("plugins_count") or 0) >= 3,
        f"{v.get('plugins_count')} plugins")

    chk("languages_set",
        (v.get("languages_count") or 0) >= 1,
        f"{v.get('languages_count')} languages")

    chk("chrome_exists",
        bool(v.get("chrome_exists")),
        "window.chrome present")

    chk("chrome_runtime",
        bool(v.get("chrome_runtime")),
        "chrome.runtime present")

    chk("chrome_loadtimes",
        v.get("chrome_loadtimes") == "function",
        f"chrome.loadTimes={v.get('chrome_loadtimes')!r}")

    chk("chrome_csi",
        v.get("chrome_csi") == "function",
        f"chrome.csi={v.get('chrome_csi')!r}")

    chk("chrome_app",
        bool(v.get("chrome_app")),
        "chrome.app present")

    chk("no_cdc_vars",
        (v.get("cdc_vars") or 0) == 0,
        f"{v.get('cdc_vars')} cdc_ globals found")

    chk("no_phantom",
        not v.get("phantom"),
        "phantom globals absent")

    chk("color_depth_24",
        v.get("color_depth") in (24, 30, 32),
        f"colorDepth={v.get('color_depth')}")

    chk("perf_timing_valid",
        bool(v.get("perf_timing_valid")),
        "performance.timing.navigationStart>0")

    chk("notification_not_denied",
        v.get("notification_perm") not in ("denied",),
        f"Notification.permission={v.get('notification_perm')!r}")

    chk("no_nightmare",
        not v.get("nightmare"),
        "__nightmare absent")

    chk("error_stack_clean",
        bool(v.get("error_stack_clean")),
        "no automation strings in Error.stack")

    chk("istrusted_spoofed",
        bool(v.get("istrusted_spoofed")),
        f"new MouseEvent().isTrusted={v.get('istrusted_spoofed')}")

    chk("iframe_webdriver_clean",
        v.get("iframe_webdriver") in (False, None, "__error__"),
        f"iframe.contentWindow.navigator.webdriver={v.get('iframe_webdriver')!r}")

    chk("webgl_vendor_real",
        bool(v.get("webgl_vendor")) and "SwiftShader" not in str(v.get("webgl_vendor",""))
        and v.get("webgl_vendor") != "error",
        f"vendor={str(v.get('webgl_vendor',''))[:40]!r}")

    chk("outer_height_nonzero",
        (v.get("outer_height") or 0) > 0,
        f"outerHeight={v.get('outer_height')}")

    wc = str(v.get("worker_patched", "N/A"))
    chk("worker_proxy_applied",
        wc in ("proxy_patched", "absent", "N/A"),
        f"Worker constructor={wc}")

    tz = str(v.get("intl_tz", ""))
    lang = str(v.get("language", ""))
    # Simple consistency check: language prefix should plausibly match timezone region
    _TZ_OK = {
        "sw": "Africa/", "en": ("America/","Europe/","Australia/","Pacific/","Asia/"),
        "de": "Europe/", "fr": "Europe/", "ja": "Asia/", "ko": "Asia/",
        "zh": "Asia/", "ru": "Europe/", "es": ("Europe/","America/"),
        "pt": ("Europe/","America/"),
    }
    lang_prefix = lang.split("-")[0] if lang else ""
    tz_expected = _TZ_OK.get(lang_prefix)
    if tz_expected and tz:
        tz_ok = tz.startswith(tz_expected) if isinstance(tz_expected, str) else any(tz.startswith(p) for p in tz_expected)
    else:
        tz_ok = True  # unknown language — don't penalise
    chk("intl_tz_consistent",
        tz_ok,
        f"lang={lang!r} tz={tz!r}")

    return results


# ── Site-specific scrapers ────────────────────────────────────────────────────

def _visit_sannysoft(cdp: CDPExecutor) -> dict:
    cdp.navigate("https://bot.sannysoft.com")
    time.sleep(5)
    # Extract table: tr → td[0]=test, td[1]=result, className=pass/fail/warn
    rows = cdp.eval_js(r"""
    (function(){
      var rows = [];
      document.querySelectorAll('table tr').forEach(function(tr) {
        var tds = tr.querySelectorAll('td');
        if (tds.length < 2) return;
        rows.push({
          test:    tds[0].innerText.trim(),
          result:  tds[1].innerText.trim(),
          passed:  tr.className.includes('passed') || tds[1].className.includes('passed'),
          failed:  tr.className.includes('failed') || tds[1].className.includes('failed'),
        });
      });
      return rows;
    })()
    """) or []
    return {"site": "bot.sannysoft.com", "rows": rows}


def _visit_pixelscan(cdp: CDPExecutor) -> dict:
    # pixelscan.net discontinued its free fingerprint scan; use fingerprint-scan.com
    # (the successor that Vastel explicitly links to as the "more recent" alternative)
    cdp.navigate("https://fingerprint-scan.com/")
    time.sleep(20)  # SPA needs time to run all async checks
    data = cdp.eval_js(r"""
    (function(){
      var checks = [];
      var score  = null;

      // Extract overall score/verdict text
      var scoreEls = document.querySelectorAll(
        '[class*="score"],[class*="Score"],[class*="result"],[class*="verdict"],[class*="summary"],' +
        '[id*="score"],[id*="result"],[id*="verdict"]'
      );
      scoreEls.forEach(function(el) {
        if (score) return;
        var t = el.innerText.trim();
        if (t.length > 1 && t.length < 300) score = t;
      });

      // Extract per-check rows
      var rowSelectors = [
        '[class*="check"]','[class*="Check"]','[class*="item"]','[class*="row"]',
        '[class*="feature"]','[class*="test"]',
      ];
      var found = false;
      rowSelectors.forEach(function(sel) {
        if (found) return;
        var els = document.querySelectorAll(sel);
        if (els.length >= 4) {
          els.forEach(function(el) {
            var text = el.innerText.trim();
            if (text.length > 2 && text.length < 300) {
              var cls = el.className || '';
              checks.push({
                text: text, classes: cls,
                pass: /pass|ok|safe|good|green|human/i.test(cls + ' ' + text),
                fail: /fail|bad|warn|risk|bot|red|danger|suspicious/i.test(cls),
              });
            }
          });
          if (checks.length >= 3) found = true;
        }
      });

      // Table fallback
      if (!found) {
        document.querySelectorAll('tr').forEach(function(tr) {
          var tds = tr.querySelectorAll('td');
          if (tds.length >= 2) {
            checks.push({
              text: tr.innerText.trim(), classes: tr.className,
              pass: /pass|ok/i.test(tr.className), fail: /fail|bad/i.test(tr.className),
            });
          }
        });
      }

      var pageText = document.body ? document.body.innerText.slice(0, 3000) : '';
      return {score: score, checks: checks.slice(0, 40), pageText: pageText,
              url: location.href, title: document.title};
    })()
    """) or {}
    return {"site": "fingerprint-scan.com", "data": data}


def _visit_vastel(cdp: CDPExecutor) -> dict:
    cdp.navigate("https://arh.antoinevastel.com/bots/areyouheadless")
    time.sleep(6)
    result = cdp.eval_js(r"""
    (function(){
      var text = document.body ? document.body.innerText : '';
      var score = null;
      var scoreEl = document.querySelector('#score, .score, [class*="score"]');
      if (scoreEl) score = scoreEl.innerText;
      var tableRows = [];
      document.querySelectorAll('tr').forEach(function(tr) {
        var tds = tr.querySelectorAll('td');
        if (tds.length >= 2) tableRows.push({
          test: tds[0].innerText.trim(),
          result: tds[1].innerText.trim(),
        });
      });
      return {text: text.slice(0,1500), score: score, rows: tableRows};
    })()
    """) or {}
    return {"site": "arh.antoinevastel.com", "data": result}


def _visit_creepjs(cdp: CDPExecutor) -> dict:
    cdp.navigate("https://abrahamjuliot.github.io/creepjs/")
    time.sleep(18)  # CreepJS runs many async fingerprint tests
    result = cdp.eval_js(r"""
    (function(){
      var text = document.body ? document.body.innerText : '';

      // 1. Extract percentage scores from headless/stealth detection lines
      var scores = [];
      text.split('\n').forEach(function(line) {
        line = line.trim();
        var m = line.match(/^(\d+(?:\.\d+)?%)\s*(.{3,60})$/);
        if (m) scores.push({pct: m[1], label: m[2]});
        // Also catch "25% like headless: hash" style
        var m2 = line.match(/(\d+)%\s+((?:like\s+)?headless|stealth|chromium)[\s:]/i);
        if (m2) scores.push({pct: m2[1]+'%', label: m2[2]});
      });

      // 2. Extract specific signal lines
      var signals = {};
      // Headless line
      var hlMatch = text.match(/(\d+)%\s+like\s+headless/i);
      if (hlMatch) signals.headless_pct = parseInt(hlMatch[1]);
      var stMatch = text.match(/(\d+)%\s+stealth/i);
      if (stMatch) signals.stealth_pct = parseInt(stMatch[1]);
      // Resistance
      var resMatch = text.match(/Resistance[a-f0-9]{8}[\s\S]{0,300}?(?=\n\S)/);
      if (resMatch) signals.resistance = resMatch[0].replace(/\s+/g,' ').slice(0,200);
      // WebRTC candidate
      var rtcMatch = text.match(/candidate:[^\n]+typ host[^\n]*/);
      if (rtcMatch) signals.webrtc_host_candidate = rtcMatch[0].slice(0,150);
      // Speech default voice
      var speechMatch = text.match(/default:\n([^\n]+)/);
      if (speechMatch) signals.speech_default = speechMatch[1].trim();
      // Connection
      var connMatch = text.match(/effectiveType:\s*(\w+)/);
      if (connMatch) signals.connection_type = connMatch[1];
      // Screen
      var screenMatch = text.match(/screen:\s*(\d+\s*x\s*\d+)/);
      if (screenMatch) signals.screen = screenMatch[1];

      // 3. Lies sections — look for lines explicitly saying "N lie(s)"
      var explicitLies = [];
      text.split('\n').forEach(function(line) {
        line = line.trim();
        if (/\d+\s+lie/i.test(line)) explicitLies.push(line.slice(0,120));
      });

      return {
        scores: scores.slice(0,10),
        signals: signals,
        explicit_lies: explicitLies.slice(0,20),
        page_sample: text.slice(0, 2000),
      };
    })()
    """) or {}
    return {"site": "creepjs", "data": result}


def _visit_browserleaks(cdp: CDPExecutor) -> dict:
    cdp.navigate("https://browserleaks.com/javascript")
    time.sleep(6)
    rows = cdp.eval_js(r"""
    (function(){
      var rows = [];
      document.querySelectorAll('table tr').forEach(function(tr) {
        var tds = tr.querySelectorAll('td');
        if (tds.length >= 2) rows.push({
          key:   tds[0].innerText.trim(),
          value: tds[1].innerText.trim(),
        });
      });
      return rows.slice(0,60);
    })()
    """) or []
    return {"site": "browserleaks.com/js", "rows": rows}


def _probe_worker_consistency(cdp: CDPExecutor) -> dict:
    """Async probe: spin up a blob Worker, collect navigator.* values, compare."""
    try:
        result = cdp.eval_js_async(r"""
        new Promise(function(resolve) {
          try {
            var code = [
              'self.postMessage({',
              '  ua:       navigator.userAgent,',
              '  lang:     navigator.language,',
              '  langs:    Array.from(navigator.languages||[]),',
              '  platform: navigator.platform,',
              '  hw:       navigator.hardwareConcurrency,',
              '  mem:      navigator.deviceMemory,',
              '  vendor:   navigator.vendor,',
              '  tz: (function(){try{return Intl.DateTimeFormat().resolvedOptions().timeZone;}catch(e){return "";}})()',
              '});',
            ].join('\n');
            var blob = new Blob([code], {type:'application/javascript'});
            var url  = URL.createObjectURL(blob);
            var w    = new Worker(url);
            var tid  = setTimeout(function(){
              w.terminate(); URL.revokeObjectURL(url);
              resolve({error:'timeout'});
            }, 4000);
            w.onmessage = function(e) {
              clearTimeout(tid); w.terminate(); URL.revokeObjectURL(url);
              var d = e.data || {};
              d.main_ua       = navigator.userAgent;
              d.main_lang     = navigator.language;
              d.main_langs    = Array.from(navigator.languages||[]);
              d.main_platform = navigator.platform;
              d.main_hw       = navigator.hardwareConcurrency;
              d.main_mem      = navigator.deviceMemory;
              d.main_vendor   = navigator.vendor;
              d.main_tz       = (function(){try{return Intl.DateTimeFormat().resolvedOptions().timeZone;}catch(e){return "";}})();
              d.ua_match      = d.ua === d.main_ua;
              d.lang_match    = d.lang === d.main_lang;
              d.platform_match= d.platform === d.main_platform;
              d.tz_match      = d.tz === d.main_tz;
              resolve(d);
            };
            w.onerror = function(e) {
              clearTimeout(tid); URL.revokeObjectURL(url);
              resolve({error: 'worker_error:' + e.message});
            };
          } catch(ex) {
            resolve({error: 'exception:' + ex.message});
          }
        })
        """)
        return result or {}
    except Exception as e:
        return {"error": str(e)}


SITES = [
    ("sannysoft",          _visit_sannysoft),
    ("fingerprint-scan.com", _visit_pixelscan),
    ("vastel",             _visit_vastel),
    ("creepjs",            _visit_creepjs),
    ("browserleaks",       _visit_browserleaks),
]


# ── Patch round management ────────────────────────────────────────────────────

PATCH_ROUNDS = [
    # Round 0: baseline (no extra patches beyond IXBrowser + _STEALTH_JS)
    [],
    # Round 1: chrome completeness + permissions
    [("chrome_complete", None), ("permissions_patch", None)],
    # Round 2: + plugins + error stack + console clean
    [("plugins_realistic", None), ("error_stack_norm", None), ("console_clean", None)],
    # Round 3: + iframe webdriver + user activation + speech
    [("iframe_webdriver", None), ("user_activation", None), ("speech_voices", None)],
    # Round 4: + webrtc shield (now blocks typ host, not just RFC1918) + runtime leak
    [("webrtc_shield", None), ("runtime_enable_leak", None)],
    # Round 5: + Worker navigator spoof + Intl timezone consistency
    [("worker_nav_spoof", None), ("intl_timezone_patch", None)],
    # Round 6: + isTrusted spoof (assessment-mode — Chrome C++ gate; cosmetic only)
    [("istrusted_spoof", None)],
]


def _apply_patch_round(cdp: CDPExecutor, round_idx: int) -> str:
    """Build and inject the patch bundle for rounds 0..round_idx."""
    from careerbridge.stealth_patches import ALL_PATCHES, ASSESSMENT_EXTRA
    patch_dict = {name: js for name, js in ALL_PATCHES + ASSESSMENT_EXTRA}

    # Collect all patch names up to this round
    selected_names: set[str] = set()
    for r in range(1, round_idx + 1):
        if r < len(PATCH_ROUNDS):
            for name, _ in PATCH_ROUNDS[r]:
                selected_names.add(name)

    selected = [(n, patch_dict[n]) for n in [p for _, p in
                [(n, n) for n in selected_names]] if n in patch_dict]
    # Simpler: just build cumulative bundle
    cumulative = [(n, j) for n, j in ALL_PATCHES if
                  any(n in [nm for nm, _ in PATCH_ROUNDS[r]]
                      for r in range(1, round_idx + 1)
                      if r < len(PATCH_ROUNDS))]
    if round_idx >= 5:
        cumulative += ASSESSMENT_EXTRA

    bundle = build_bundle(cumulative)
    if bundle.strip():
        cdp._send("Page.addScriptToEvaluateOnNewDocument", {"source": bundle})
        # Also evaluate immediately on current page
        cdp.eval_js(bundle)
    return bundle


# ── Main loop ─────────────────────────────────────────────────────────────────

def run_detection_loop(
    cdp_url: str,
    max_rounds: int = 7,
    site_filter: list[str] | None = None,
    pause_between_sites: float = 2.0,
):
    cdp = CDPExecutor()
    cdp.connect_ws(cdp_url)

    all_round_scores: list[dict] = []

    for round_idx in range(max_rounds):
        print(f"\n{'='*70}")
        print(_hdr(f"ROUND {round_idx} — {'BASELINE (no extra patches)' if round_idx == 0 else f'Patches 1..{round_idx}'}"))
        print(f"{'='*70}")

        # Apply cumulative patches for this round
        if round_idx > 0:
            bundle = _apply_patch_round(cdp, round_idx)
            n_patches = bundle.count("(function()")
            print(f"  Injected {n_patches} patch module(s) via addScriptToEvaluateOnNewDocument")

        # ── Direct probe (always run on blank page first) ──────────────────
        print(f"\n{_hdr('[ DIRECT JS PROBE ]')}")
        cdp.navigate("about:blank")
        time.sleep(0.5)
        # Re-apply patches on blank page (addScriptToEvaluateOnNewDocument doesn't apply to about:blank)
        if round_idx > 0:
            cdp.eval_js(bundle)
        raw_signals = cdp.eval_js(DIRECT_PROBE_JS) or {}
        scored = _score_signals(raw_signals)
        pass_count = sum(1 for _, p, _ in scored if p)
        fail_count = sum(1 for _, p, _ in scored if not p)
        print(f"  Score: {pass_count}/{pass_count+fail_count} signals clean")
        print()
        for name, passed, detail in scored:
            icon = _ok(name) if passed else _bad(name)
            print(f"  {icon}  {detail}")

        round_score = {
            "round": round_idx,
            "direct_pass": pass_count,
            "direct_fail": fail_count,
            "direct_signals": {n: (p, d) for n, p, d in scored},
        }

        # ── Async Worker consistency probe ─────────────────────────────────────
        print(f"\n{_hdr('[ WORKER CONSISTENCY PROBE ]')}")
        wdata = _probe_worker_consistency(cdp)
        if "error" in wdata:
            print(f"  {_warn('worker probe')}: {wdata['error']}")
        else:
            fields = [("ua","ua_match","userAgent"), ("lang","lang_match","language"),
                      ("platform","platform_match","platform"), ("tz","tz_match","timezone")]
            all_match = True
            for worker_key, match_key, label in fields:
                match = wdata.get(match_key, False)
                wval  = str(wdata.get(worker_key, "?"))[:50]
                mval  = str(wdata.get(f"main_{worker_key}", "?"))[:50]
                if match:
                    print(f"  {_ok(label)}: worker={wval!r}")
                else:
                    all_match = False
                    print(f"  {_bad(label)}: worker={wval!r} main={mval!r}")
            if all_match:
                print(f"  {_ok('Worker navigator MATCHES main thread — no fingerprint mismatch')}")
        round_score["worker_consistency"] = wdata

        # ── Site-specific scans ────────────────────────────────────────────
        sites_to_run = [(n, fn) for n, fn in SITES
                        if not site_filter or n in site_filter]

        for site_name, site_fn in sites_to_run:
            print(f"\n{_hdr(f'[ {site_name.upper()} ]')}")
            try:
                result = site_fn(cdp)
                _print_site_result(site_name, result)
                round_score[site_name] = result
            except Exception as e:
                print(f"  {_bad('ERROR')}: {e}")
                round_score[site_name] = {"error": str(e)}

            time.sleep(pause_between_sites)

        all_round_scores.append(round_score)

        # ── Round summary ──────────────────────────────────────────────────
        prev_pass = all_round_scores[-2]["direct_pass"] if len(all_round_scores) > 1 else 0
        delta = pass_count - prev_pass
        print(f"\n{'─'*70}")
        print(f"  Round {round_idx} summary: {pass_count}/{pass_count+fail_count} clean "
              f"({'↑' if delta > 0 else '→' if delta == 0 else '↓'}{abs(delta):+d} vs prev round)")

        if fail_count == 0:
            print(f"\n{GREEN}{BOLD}All signals clean — stopping loop.{RESET}")
            break

        if round_idx == max_rounds - 1:
            print(f"\n{YELLOW}Max rounds reached. Remaining gaps:{RESET}")
            for name, passed, detail in scored:
                if not passed:
                    print(f"  {_bad(name)}: {detail}")

    # ── Final report ───────────────────────────────────────────────────────
    _print_final_report(all_round_scores)
    cdp.disconnect()
    return all_round_scores


def _print_site_result(site_name: str, result: dict) -> None:
    if "error" in result:
        print(f"  {_bad('error')}: {result['error']}")
        return

    if site_name == "sannysoft":
        rows = result.get("rows", [])
        for r in rows:
            if r.get("failed"):
                print(f"  {_bad(r.get('test','?'))}: {r.get('result','')}")
            elif r.get("passed"):
                print(f"  {_ok(r.get('test','?'))}: {r.get('result','')}")
            else:
                print(f"  {_warn(r.get('test','?'))}: {r.get('result','')}")

    elif site_name in ("pixelscan", "fingerprint-scan.com"):
        data   = result.get("data", {})
        score  = data.get("score")
        checks = data.get("checks", [])
        url    = data.get("url", "")
        print(f"  URL: {url[:80]}")
        if score:
            print(f"  Score/Summary: {BOLD}{score[:150]}{RESET}")
        if checks:
            shown = [c for c in checks if c.get("fail") or c.get("pass")][:20] or checks[:20]
            for it in shown:
                text = it.get("text", "")[:100]
                if it.get("fail"):
                    print(f"  {_bad(text)}")
                elif it.get("pass"):
                    print(f"  {_ok(text)}")
                else:
                    print(f"  {_warn(text)}")
        else:
            pt = data.get("pageText", "")
            if pt:
                print(f"  (page text excerpt)")
                for line in pt.splitlines()[:20]:
                    line = line.strip()
                    if line:
                        print(f"    {line[:120]}")

    elif site_name == "vastel":
        data = result.get("data", {})
        rows = data.get("rows", [])
        if rows:
            for r in rows:
                is_pass = "pass" in r.get("result","").lower() or "ok" in r.get("result","").lower()
                flag = "[OK]" if is_pass else "[!!]"
                color = GREEN if is_pass else RED
                print(f"  {color}{flag} {r.get('test','')}: {r.get('result','')}{RESET}")
        else:
            text = data.get("text","")[:600]
            print(f"  {text}")

    elif site_name == "creepjs":
        data    = result.get("data", {})
        signals = data.get("signals", {})
        scores  = data.get("scores", [])
        lies    = data.get("explicit_lies", [])

        # Headless / stealth scores
        hl = signals.get("headless_pct")
        st = signals.get("stealth_pct")
        if hl is not None:
            icon = _bad(f"headless-like {hl}%") if hl > 10 else _ok(f"headless-like {hl}%")
            print(f"  {icon}")
        if st is not None:
            icon = _bad(f"stealth {st}%") if st > 10 else _ok(f"stealth {st}%")
            print(f"  {icon}")

        # WebRTC
        rtc = signals.get("webrtc_host_candidate")
        if rtc:
            print(f"  {_bad('WebRTC host candidate LEAKED')}: {rtc[:100]}")
        else:
            print(f"  {_ok('WebRTC: no host candidate in page text')}")

        # Speech
        speech = signals.get("speech_default", "")
        if speech:
            lang  = str(result.get("data",{}).get("signals",{}).get("lang",""))
            print(f"  {_warn('speech default voice')}: {speech[:80]}")

        # Resistance
        res = signals.get("resistance","")
        if res:
            mode_ok = "unknown" not in res.lower()
            icon = _ok("resistance") if mode_ok else _warn("resistance (antidetect detected)")
            print(f"  {icon}: {res[:100]}")

        # Screen
        screen = signals.get("screen","")
        if screen:
            suspicious = "1024 x 768" in screen or "800 x 600" in screen
            icon = _bad(f"screen {screen}") if suspicious else _ok(f"screen {screen}")
            print(f"  {icon}")

        # Connection
        conn = signals.get("connection_type","")
        if conn:
            icon = _ok(f"connection {conn}") if conn in ("4g","wifi") else _warn(f"connection {conn}")
            print(f"  {icon}")

        # Explicit lies
        if lies:
            print(f"  {_bad(f'Explicit lies: {len(lies)}')}")
            for lie in lies[:10]:
                print(f"    {_bad(lie[:100])}")
        else:
            print(f"  {_ok('No explicit lie counts in text')}")

    elif site_name == "browserleaks":
        rows = result.get("rows", [])
        sensitive_keys = {"webdriver", "plugin", "language", "mime", "notification"}
        for r in rows:
            key = r.get("key","").lower()
            val = r.get("value","")
            if any(k in key for k in sensitive_keys):
                print(f"  {_warn(r['key'])}: {val[:80]}")


def _print_final_report(scores: list[dict]) -> None:
    print(f"\n{'='*70}")
    print(_hdr("FINAL DETECTION LOOP REPORT"))
    print(f"{'='*70}")
    if not scores:
        return

    baseline = scores[0]
    final    = scores[-1]
    b_pass   = baseline["direct_pass"]
    b_fail   = baseline["direct_fail"]
    f_pass   = final["direct_pass"]
    f_fail   = final["direct_fail"]

    print(f"\n  Baseline:  {b_pass}/{b_pass+b_fail} clean ({b_fail} failing)")
    print(f"  After {len(scores)-1} round(s): {f_pass}/{f_pass+f_fail} clean ({f_fail} failing)")
    print(f"  Improvement: {f_pass - b_pass:+d} signals fixed\n")

    if f_fail == 0:
        print(f"  {GREEN}{BOLD}STATUS: FULLY CLEAN — no bot signals detected{RESET}")
    else:
        print(f"  {YELLOW}{BOLD}STATUS: {f_fail} signal(s) still leaking:{RESET}")
        for name, (passed, detail) in final["direct_signals"].items():
            if not passed:
                print(f"    {_bad(name)}: {detail}")

    print(f"\n  Patch progression:")
    for s in scores:
        r = s["round"]
        p = s["direct_pass"]
        f = s["direct_fail"]
        bar = "█" * p + "░" * f
        print(f"    Round {r}: [{bar}] {p}/{p+f}")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bot detection audit loop")
    parser.add_argument("--cdp", default="", help="CDP WebSocket URL (default: auto-discover via IXBrowser API)")
    parser.add_argument("--rounds", type=int, default=7, help="Max patch rounds (default 7)")
    parser.add_argument("--site", action="append", dest="sites",
                        help="Limit to specific site(s): sannysoft pixelscan vastel creepjs browserleaks")
    parser.add_argument("--profile", type=int, default=12, help="IXBrowser profile ID")
    args = parser.parse_args()

    cdp_url = args.cdp
    if not cdp_url:
        from careerbridge.ixbrowser_connector import ix_open_profile
        cdp_url = ix_open_profile(args.profile)
        print(f"Using IXBrowser profile {args.profile}: {cdp_url[:60]}")

    run_detection_loop(
        cdp_url=cdp_url,
        max_rounds=args.rounds,
        site_filter=args.sites,
    )
