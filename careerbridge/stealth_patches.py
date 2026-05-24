"""
careerbridge/stealth_patches.py — Layered CDP stealth patch library.

Research sources:
  - puppeteer-extra-plugin-stealth (berstend/puppeteer-extra)
  - rebrowser-patches (rebrowser-net/rebrowser-patches)
  - playwright-stealth (AtubeLLC/playwright-stealth)
  - creepjs source (abrahamjuliot/creepjs)
  - Vastel et al. "FP-Radar" (browser fingerprinting survey, 2021)
  - Jonker et al. "Fingerprint Survey" (NDSS 2019)

Layers apply in order — each is independently toggleable via apply_patches().
IXBrowser already patches at C++ level: webdriver flag, canvas noise, WebGL
vendor/renderer, AudioContext fingerprint, timezone, language headers.
These layers cover what IXBrowser CANNOT patch (JS-space runtime signals).
"""
from __future__ import annotations

# ── Layer 0: IXBrowser baseline (already injected by cdp_executor._STEALTH_JS)
# Removes cdc_* variables, stubs window.chrome.runtime.
# DO NOT repeat here — it runs via addScriptToEvaluateOnNewDocument on connect.

# ── Layer 1: Chrome object completeness ───────────────────────────────────────
# Detectors: CreepJS, Sannysoft, FingerprintPro, Pixelscan
# Issue: bare window.chrome stub missing loadTimes, csi, app sub-objects.
CHROME_COMPLETE = r"""
(function(){
  if (!window.chrome) window.chrome = {};

  // chrome.loadTimes — present in real Chrome
  window.chrome.loadTimes = function(){
    return {
      commitLoadTime: performance.timing.navigationStart/1000 + Math.random()*0.01,
      connectionInfo: 'http/1.1',
      finishDocumentLoadTime: 0,
      finishLoadTime: 0,
      firstPaintAfterLoadTime: 0,
      firstPaintTime: 0,
      navigationType: 'Other',
      npnNegotiatedProtocol: 'http/1.1',
      requestTime: performance.timing.navigationStart/1000,
      startLoadTime: performance.timing.navigationStart/1000,
      wasAlternateProtocolAvailable: false,
      wasFetchedViaSpdy: false,
      wasNpnNegotiated: false,
    };
  };

  // chrome.csi — performance timestamps
  window.chrome.csi = function(){
    return {
      startE: performance.timing.navigationStart,
      onloadT: performance.timing.loadEventStart,
      pageT: performance.now(),
      tran: 15,
    };
  };

  // chrome.app — present in real Chrome
  if (!window.chrome.app) {
    window.chrome.app = {
      isInstalled: false,
      InstallState: {DISABLED:'disabled',INSTALLED:'installed',NOT_INSTALLED:'not_installed'},
      RunningState: {CANNOT_RUN:'cannot_run',READY_TO_RUN:'ready_to_run',RUNNING:'running'},
      getDetails: function(){ return null; },
      getIsInstalled: function(){ return false; },
      installState: function(cb){ cb('not_installed'); },
      isInstalled: false,
      runningState: function(){ return 'cannot_run'; },
    };
  }

  // chrome.runtime completeness (already stubbed, fill gaps)
  if (!window.chrome.runtime) window.chrome.runtime = {};
  window.chrome.runtime.id = undefined;
  window.chrome.runtime.connect = window.chrome.runtime.connect || function(){
    return {postMessage:function(){}, onMessage:{addListener:function(){}}};
  };
  window.chrome.runtime.sendMessage = window.chrome.runtime.sendMessage || function(){};
  if (!window.chrome.runtime.onMessage)
    window.chrome.runtime.onMessage = {addListener:function(){}, removeListener:function(){}};
  if (!window.chrome.runtime.onConnect)
    window.chrome.runtime.onConnect = {addListener:function(){}, removeListener:function(){}};
  if (!window.chrome.runtime.onInstalled)
    window.chrome.runtime.onInstalled = {addListener:function(){}, removeListener:function(){}};
})();
"""

# ── Layer 2: navigator.plugins realistic array ────────────────────────────────
# Detectors: Sannysoft ("Plugin Array"), CreepJS, Pixelscan
# Issue: some IXBrowser configs expose empty plugins array.
PLUGINS_REALISTIC = r"""
(function(){
  if (navigator.plugins && navigator.plugins.length >= 3) return; // already populated

  const fakePlugins = [
    {name:'Chrome PDF Plugin', description:'Portable Document Format', filename:'internal-pdf-viewer',
     mimeTypes:[{type:'application/x-google-chrome-pdf', suffixes:'pdf', description:'Portable Document Format'}]},
    {name:'Chrome PDF Viewer', description:'', filename:'mhjfbmdgcfjbbpaeojofohoefgiehjai',
     mimeTypes:[{type:'application/pdf', suffixes:'pdf', description:''}]},
    {name:'Native Client', description:'', filename:'internal-nacl-plugin',
     mimeTypes:[{type:'application/x-nacl', suffixes:'', description:'Native Client Executable'},
                {type:'application/x-pnacl', suffixes:'', description:'Portable Native Client Executable'}]},
  ];

  function makeMimeType(t) {
    return Object.create(MimeType.prototype, {
      type:{value:t.type,enumerable:true},
      suffixes:{value:t.suffixes,enumerable:true},
      description:{value:t.description,enumerable:true},
      enabledPlugin:{value:null,enumerable:true},
    });
  }

  function makePlugin(p) {
    const mimes = p.mimeTypes.map(makeMimeType);
    const obj = Object.create(Plugin.prototype);
    Object.defineProperties(obj, {
      name:{value:p.name,enumerable:true},
      description:{value:p.description,enumerable:true},
      filename:{value:p.filename,enumerable:true},
      length:{value:mimes.length,enumerable:true},
    });
    mimes.forEach((m,i) => { obj[i] = m; obj[m.type] = m; });
    return obj;
  }

  const plugins = fakePlugins.map(makePlugin);
  const pluginArray = Object.create(PluginArray.prototype);
  Object.defineProperty(pluginArray, 'length', {value:plugins.length,enumerable:true});
  plugins.forEach((p,i) => { pluginArray[i] = p; pluginArray[p.name] = p; });
  pluginArray.item = function(i){ return this[i] || null; };
  pluginArray.namedItem = function(n){ return this[n] || null; };
  pluginArray.refresh = function(){};

  Object.defineProperty(navigator, 'plugins', {
    get: function(){ return pluginArray; },
    enumerable: true, configurable: true,
  });
  Object.defineProperty(navigator, 'mimeTypes', {
    get: function(){
      const ma = Object.create(MimeTypeArray.prototype);
      const types = plugins.flatMap(p => Object.values(p).filter(v => v instanceof MimeType));
      Object.defineProperty(ma, 'length', {value:types.length,enumerable:true});
      types.forEach((m,i) => { ma[i] = m; ma[m.type] = m; });
      ma.item = function(i){ return this[i] || null; };
      ma.namedItem = function(n){ return this[n] || null; };
      return ma;
    },
    enumerable: true, configurable: true,
  });
})();
"""

# ── Layer 3: navigator.permissions realistic ──────────────────────────────────
# Detectors: Sannysoft ("Notification Permissions"), CreepJS, Pixelscan
# Issue: headless returns "denied" for notifications; CDP automation returns
#        "denied" for push — both are detectable divergences.
PERMISSIONS_PATCH = r"""
(function(){
  // 1. Override Notification.permission to return 'default' (not 'denied')
  //    IXBrowser/headless Chrome auto-denies notifications — detectors check this.
  try {
    if (typeof Notification !== 'undefined' && Notification.permission !== 'default') {
      Object.defineProperty(Notification, 'permission', {
        get: function() { return 'default'; },
        configurable: true,
      });
    }
  } catch(e) {}

  // 2. Override permissions.query() to return realistic states
  const _origQuery = window.Permissions && window.Permissions.prototype.query;
  if (!_origQuery) return;

  // PermissionStatus.state valid values: "granted" | "denied" | "prompt"
  // Note: Notification.permission uses "default" for the same concept as "prompt"
  const _overrides = {
    notifications: 'prompt',
    push:          'prompt',
    midi:          'granted',
    'clipboard-read':  'granted',
    'clipboard-write': 'granted',
    geolocation:   'prompt',
    camera:        'prompt',
    microphone:    'prompt',
  };

  window.Permissions.prototype.query = function(permissionDesc) {
    const state = _overrides[(permissionDesc||{}).name];
    if (state !== undefined) {
      // Use a plain object — Object.create(PermissionStatus.prototype) produces
      // a broken object without internal slots that V8 requires for .state.
      const status = { state, onchange: null,
        addEventListener: function(){}, removeEventListener: function(){} };
      return Promise.resolve(status);
    }
    return _origQuery.call(this, permissionDesc);
  };
})();
"""

# ── Layer 4: isTrusted event spoofing ─────────────────────────────────────────
# Detectors: Any site checking event.isTrusted on click/key handlers
# Issue: CDP Input.dispatchMouseEvent/dispatchKeyEvent sets isTrusted=false.
#        THIS IS THE HARDEST SIGNAL — only OS HID gives true isTrusted=true.
#        This patch overrides the property descriptor to always return true.
#        Trade-off: breaks legitimate sites that use isTrusted as CSRF guard.
#        Enable ONLY for assessment pipeline flows, not general browsing.
ISTRUSTED_SPOOF = r"""
(function(){
  const _original = Object.getOwnPropertyDescriptor(Event.prototype, 'isTrusted');
  if (!_original || !_original.get) return;
  Object.defineProperty(Event.prototype, 'isTrusted', {
    get: function(){ return true; },
    enumerable: true,
    configurable: true,
  });
})();
"""

# ── Layer 5: Stack trace / Error normalization ────────────────────────────────
# Detectors: CreepJS "Error stack" feature, some custom enterprise detectors
# Issue: In CDP contexts the V8 stack sometimes includes __playwright_*
#        or unusual frames. This patch is defensive only — IXBrowser
#        doesn't emit those frames but it's a zero-cost safety net.
ERROR_STACK_NORM = r"""
(function(){
  const _OrigError = Error;
  function PatchedError(...args) {
    const e = new _OrigError(...args);
    if (e.stack) {
      e.stack = e.stack
        .replace(/__playwright[^\n]*/g, '')
        .replace(/puppeteer[^\n]*/g, '')
        .replace(/\n\n+/g, '\n');
    }
    return e;
  }
  PatchedError.prototype = _OrigError.prototype;
  PatchedError.captureStackTrace = _OrigError.captureStackTrace;
  ['prepareStackTrace','stackTraceLimit'].forEach(k => {
    if (k in _OrigError) PatchedError[k] = _OrigError[k];
  });
  window.Error = PatchedError;
})();
"""

# ── Layer 6: Cross-frame webdriver patch ──────────────────────────────────────
# Detectors: CreepJS "iframe contentWindow", custom anti-bot scripts
# Issue: navigator.webdriver inside an iframe may not be patched if the
#        frame runs in a separate process. This intercepts iframe creation
#        and patches the contentWindow before scripts load.
IFRAME_WEBDRIVER = r"""
(function(){
  const _origCreate = document.createElement.bind(document);
  document.createElement = function(tag, ...args) {
    const el = _origCreate(tag, ...args);
    if ((tag||'').toLowerCase() === 'iframe') {
      el.addEventListener('load', function() {
        try {
          const nav = el.contentWindow && el.contentWindow.navigator;
          if (nav && Object.getOwnPropertyDescriptor(nav, 'webdriver')) {
            Object.defineProperty(nav, 'webdriver', {get: ()=>false, configurable:true});
          }
        } catch(e) {}
      });
    }
    return el;
  };
})();
"""

# ── Layer 7: User-Activation spoofing ─────────────────────────────────────────
# Detectors: CreepJS "User Activation", sites checking transient activation
# Issue: Some sites verify user activation (requires a real user gesture).
#        CDP Runtime.evaluate with userGesture:true helps but doesn't set
#        the internal sticky activation flag in all contexts.
USER_ACTIVATION = r"""
(function(){
  if (!window.UserActivation) return;
  const desc = Object.getOwnPropertyDescriptor(window, 'userActivation');
  if (desc) {
    Object.defineProperty(window, 'userActivation', {
      get: function() {
        const orig = desc.get.call(this);
        return new Proxy(orig, {
          get(target, key) {
            if (key === 'hasBeenActive' || key === 'isActive') return true;
            const v = target[key];
            return typeof v === 'function' ? v.bind(target) : v;
          }
        });
      },
      configurable: true,
    });
  }
})();
"""

# ── Layer 8: Speech Synthesis voices ─────────────────────────────────────────
# Detectors: CreepJS "voices", Pixelscan fingerprint consistency
# Issue 1: speechSynthesis.getVoices() returns [] before voiceschanged fires.
# Issue 2: CreepJS checks if the default voice locale matches navigator.language.
#           e.g. if lang=sw-KE but default voice is en-US → flagged as mismatch.
# Fix: Cache voices after voiceschanged AND reorder so a locale-matching voice
#      appears first (becoming the "default"). Fall back to original ordering.
SPEECH_VOICES = r"""
(function(){
  if (!window.speechSynthesis) return;
  var _orig = window.speechSynthesis.getVoices.bind(window.speechSynthesis);
  var _cached = null;
  var _navLang = (navigator.language || 'en').toLowerCase();
  var _navPrefix = _navLang.split('-')[0];

  function _reorderVoices(voices) {
    if (!voices || !voices.length) return voices;
    // Find a voice matching navigator.language (exact match first, prefix fallback)
    var exactIdx  = -1, prefixIdx = -1;
    for (var i = 0; i < voices.length; i++) {
      var vl = (voices[i].lang || '').toLowerCase();
      if (vl === _navLang && exactIdx < 0)  exactIdx  = i;
      if (vl.startsWith(_navPrefix) && prefixIdx < 0) prefixIdx = i;
    }
    var matchIdx = exactIdx >= 0 ? exactIdx : prefixIdx;
    if (matchIdx <= 0) return voices; // already first or no match
    // Move matching voice to position 0
    var arr = Array.from(voices);
    var match = arr.splice(matchIdx, 1)[0];
    arr.unshift(match);
    return arr;
  }

  window.speechSynthesis.addEventListener('voiceschanged', function() {
    _cached = _reorderVoices(_orig());
  }, {once: true});

  window.speechSynthesis.getVoices = function() {
    if (_cached && _cached.length) return _cached;
    var voices = _orig();
    if (voices.length) { _cached = _reorderVoices(voices); return _cached; }
    return _cached || [];
  };
})();
"""

# ── Layer 9: WebRTC IP leak prevention ───────────────────────────────────────
# Detectors: Pixelscan, CreepJS, any site using RTCPeerConnection to leak IP
# Issue: WebRTC 'typ host' ICE candidates always expose real local IP,
#        even through VPN/proxy. mDNS (*.local) is another leak vector.
# Patch: Block all host candidates at both addEventListener and onicecandidate
#        property level (prototype-level patch so new PC instances are covered).
WEBRTC_SHIELD = r"""
(function(){
  var _origRTC = window.RTCPeerConnection;
  if (!_origRTC) return;

  function _shouldBlock(candidate) {
    if (!candidate) return false;
    var sdp = candidate.candidate || '';
    if (!sdp) return false;
    // Block ALL 'typ host' candidates — always expose real local IP
    if (/\btyp\s+host\b/.test(sdp)) return true;
    // Block mDNS hostnames (*.local) — Chrome's privacy-preserving host candidate
    if (/[0-9a-f-]{8,}\.local\b/i.test(sdp)) return true;
    // Block private IP ranges that slip through in other candidate types
    if (/\b(?:192\.168\.|10\.\d{1,3}\.|172\.(?:1[6-9]|2\d|3[01])\.|169\.254\.|127\.)\d{1,3}\.\d{1,3}\b/.test(sdp)) return true;
    return false;
  }

  // Patch onicecandidate at prototype level — covers all new PC instances
  var _iceDesc = Object.getOwnPropertyDescriptor(_origRTC.prototype, 'onicecandidate');
  if (_iceDesc && _iceDesc.set) {
    Object.defineProperty(_origRTC.prototype, 'onicecandidate', {
      get: _iceDesc.get,
      set: function(handler) {
        if (typeof handler === 'function') {
          _iceDesc.set.call(this, function(event) {
            if (event && event.candidate && _shouldBlock(event.candidate)) return;
            handler.call(this, event);
          });
        } else {
          _iceDesc.set.call(this, handler);
        }
      },
      configurable: true,
    });
  }

  function PatchedRTC(config, constraints) {
    var pc = new _origRTC(config, constraints);
    var _origAddEL = pc.addEventListener.bind(pc);
    pc.addEventListener = function(type, listener, options) {
      if (type === 'icecandidate' && typeof listener === 'function') {
        return _origAddEL(type, function(event) {
          if (event && event.candidate && _shouldBlock(event.candidate)) return;
          listener(event);
        }, options);
      }
      return _origAddEL(type, listener, options);
    };
    return pc;
  }
  PatchedRTC.prototype = _origRTC.prototype;
  Object.setPrototypeOf(PatchedRTC, _origRTC);
  window.RTCPeerConnection = PatchedRTC;

  if (window.webkitRTCPeerConnection && window.webkitRTCPeerConnection !== _origRTC) {
    var _wk = window.webkitRTCPeerConnection;
    window.webkitRTCPeerConnection = function(c, x) {
      var pc = new _wk(c, x);
      var _origAddEL = pc.addEventListener.bind(pc);
      pc.addEventListener = function(type, listener, options) {
        if (type === 'icecandidate' && typeof listener === 'function') {
          return _origAddEL(type, function(event) {
            if (event && event.candidate && _shouldBlock(event.candidate)) return;
            listener(event);
          }, options);
        }
        return _origAddEL(type, listener, options);
      };
      return pc;
    };
    window.webkitRTCPeerConnection.prototype = _wk.prototype;
  }
})();
"""

# ── Layer 10: Worker fingerprint consistency ──────────────────────────────────
# Detectors: CreepJS "Worker Scope" lies, FingerprintJS worker entropy check
# Issue: CreepJS creates a blob: Worker that serialises navigator.* and sends
#        it back via postMessage. If IXBrowser patches main thread navigator
#        but not the worker context, CreepJS flags a worker/main mismatch.
# Approach A: For non-blob Workers, prepend patch via importScripts wrapper.
# Approach B: For blob Workers (CreepJS pattern), intercept onmessage/
#             addEventListener to patch the returned data before callers see it.
WORKER_NAV_SPOOF = r"""
(function(){
  var _OrigWorker = window.Worker;
  if (!_OrigWorker) return;

  // Snapshot main-thread values at injection time
  var _fp = {};
  (function(){
    try { _fp.userAgent           = navigator.userAgent; } catch(e){}
    try { _fp.appVersion          = navigator.appVersion; } catch(e){}
    try { _fp.platform            = navigator.platform; } catch(e){}
    try { _fp.language            = navigator.language; } catch(e){}
    try { _fp.languages           = Array.from(navigator.languages || []); } catch(e){}
    try { _fp.hardwareConcurrency = navigator.hardwareConcurrency; } catch(e){}
    try { _fp.deviceMemory        = navigator.deviceMemory; } catch(e){}
    try { _fp.vendor              = navigator.vendor; } catch(e){}
    try { _fp.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone; } catch(e){}
  })();

  // Inline worker bootstrap (stringified — no closure variables)
  var _workerBootstrap = '(function(){\n' +
    'var _n=' + JSON.stringify(_fp) + ';\n' +
    '["userAgent","appVersion","platform","language","hardwareConcurrency","deviceMemory","vendor"].forEach(function(k){\n' +
    '  try{if(_n[k]!==undefined)Object.defineProperty(self.navigator,k,{get:function(){return _n[k];},configurable:true});}catch(e){}\n' +
    '});\n' +
    'try{if(_n.languages&&_n.languages.length){Object.defineProperty(self.navigator,"languages",{get:function(){return _n.languages;},configurable:true});}}catch(e){}\n' +
    'try{var _ro=Intl.DateTimeFormat.prototype.resolvedOptions;Intl.DateTimeFormat.prototype.resolvedOptions=function(){var r=_ro.call(this);if(_n.timezone)r.timeZone=_n.timezone;return r;};}catch(e){}\n' +
    '})();\n';

  // Recursively patch message data to match main-thread fingerprint
  function _patchData(data) {
    if (!data || typeof data !== 'object' || Array.isArray(data)) return;
    var _keys = ['userAgent','appVersion','platform','language','hardwareConcurrency','deviceMemory','vendor'];
    _keys.forEach(function(k){ if (k in data && _fp[k] !== undefined) data[k] = _fp[k]; });
    if ('languages' in data && _fp.languages) data.languages = _fp.languages.slice();
    if ('timezone' in data && _fp.timezone)   data.timezone  = _fp.timezone;
    if ('timeZone' in data && _fp.timezone)   data.timeZone  = _fp.timezone;
    // CreepJS nests results: {workerScope: {...}, navigator: {...}, scope: {...}}
    ['navigator','workerScope','scope','data','results'].forEach(function(k){
      if (data[k] && typeof data[k] === 'object') _patchData(data[k]);
    });
  }

  function _makeProxied(w) {
    return new Proxy(w, {
      set: function(target, prop, value) {
        if (prop === 'onmessage' && typeof value === 'function') {
          var orig = value;
          target.onmessage = function(event) {
            try { _patchData(event.data); } catch(e) {}
            return orig.call(this, event);
          };
          return true;
        }
        target[prop] = value;
        return true;
      },
      get: function(target, prop) {
        if (prop === 'addEventListener') {
          return function(type, listener, opts) {
            if (type === 'message' && typeof listener === 'function') {
              return target.addEventListener(type, function(event) {
                try { _patchData(event.data); } catch(e) {}
                return listener.call(this, event);
              }, opts);
            }
            return target.addEventListener(type, listener, opts);
          };
        }
        var v = target[prop];
        return typeof v === 'function' ? v.bind(target) : v;
      },
    });
  }

  window.Worker = function Worker(scriptURL, options) {
    var url = String(scriptURL || '');
    var w;
    // For non-blob URLs: wrap via importScripts so the bootstrap runs first
    if (!url.startsWith('blob:') && !url.startsWith('data:')) {
      try {
        var wrapCode = _workerBootstrap + '\nimportScripts(' + JSON.stringify(url) + ');';
        var blob = new Blob([wrapCode], {type: 'application/javascript'});
        var blobURL = URL.createObjectURL(blob);
        w = new _OrigWorker(blobURL, options);
      } catch(e) {
        w = new _OrigWorker(scriptURL, options);
      }
    } else {
      // blob: workers (CreepJS pattern): patch via message interception
      w = new _OrigWorker(scriptURL, options);
    }
    return _makeProxied(w);
  };
  window.Worker.prototype = _OrigWorker.prototype;
  Object.setPrototypeOf(window.Worker, _OrigWorker);
})();
"""

# ── Layer 11: Intl / timezone consistency with navigator.language ─────────────
# Detectors: CreepJS "Intl" and "Timezone" lie checks
# Issue: IXBrowser profile may set navigator.language='sw-KE' (Swahili/Kenya)
#        but the system clock timezone stays at its real value (e.g. UTC or
#        America/New_York). CreepJS flags the mismatch as a fingerprint lie.
# Fix: Override Intl.DateTimeFormat.prototype.resolvedOptions to return the
#      IANA timezone that matches the current navigator.language.
INTL_TIMEZONE_PATCH = r"""
(function(){
  var _LANG_TZ = {
    'sw':'Africa/Nairobi','sw-KE':'Africa/Nairobi','sw-TZ':'Africa/Dar_es_Salaam',
    'en':'America/New_York','en-US':'America/New_York','en-GB':'Europe/London',
    'en-AU':'Australia/Sydney','en-CA':'America/Toronto','en-NZ':'Pacific/Auckland',
    'en-ZA':'Africa/Johannesburg','en-IN':'Asia/Kolkata','en-SG':'Asia/Singapore',
    'de':'Europe/Berlin','de-AT':'Europe/Vienna','de-CH':'Europe/Zurich',
    'fr':'Europe/Paris','fr-CA':'America/Montreal','fr-BE':'Europe/Brussels',
    'es':'Europe/Madrid','es-MX':'America/Mexico_City','es-AR':'America/Argentina/Buenos_Aires',
    'it':'Europe/Rome','pt':'America/Sao_Paulo','pt-PT':'Europe/Lisbon',
    'nl':'Europe/Amsterdam','pl':'Europe/Warsaw','cs':'Europe/Prague',
    'ja':'Asia/Tokyo','zh':'Asia/Shanghai','zh-TW':'Asia/Taipei','zh-HK':'Asia/Hong_Kong',
    'ko':'Asia/Seoul','hi':'Asia/Kolkata','ar':'Asia/Riyadh','tr':'Europe/Istanbul',
    'ru':'Europe/Moscow','uk':'Europe/Kiev','vi':'Asia/Ho_Chi_Minh','th':'Asia/Bangkok',
    'id':'Asia/Jakarta','ms':'Asia/Kuala_Lumpur','tl':'Asia/Manila',
  };

  function _tzForLang(lang) {
    if (!lang) return null;
    if (_LANG_TZ[lang]) return _LANG_TZ[lang];
    return _LANG_TZ[lang.split('-')[0]] || null;
  }

  var _targetTZ = _tzForLang(navigator.language);
  if (!_targetTZ) return;

  var _currentTZ = null;
  try { _currentTZ = Intl.DateTimeFormat().resolvedOptions().timeZone; } catch(e) { return; }
  if (_currentTZ === _targetTZ) return; // already consistent

  var _origRO = Intl.DateTimeFormat.prototype.resolvedOptions;
  Intl.DateTimeFormat.prototype.resolvedOptions = function() {
    var opts = _origRO.call(this);
    if (!this['​_explicitTZ']) opts.timeZone = _targetTZ;
    return opts;
  };

  // Track DTF instances created with an explicit timeZone so we don't override them
  var _OrigDTF = Intl.DateTimeFormat;
  function _PatchedDTF(locales, options) {
    var instance = new _OrigDTF(locales, options);
    if (options && options.timeZone) instance['​_explicitTZ'] = true;
    return instance;
  }
  _PatchedDTF.prototype = _OrigDTF.prototype;
  _PatchedDTF.supportedLocalesOf = _OrigDTF.supportedLocalesOf;
  Object.setPrototypeOf(_PatchedDTF, _OrigDTF);
  try { Intl.DateTimeFormat = _PatchedDTF; } catch(e) {}
})();
"""

# ── Layer 12: console.debug / automation variable removal ─────────────────────
# Detectors: Some enterprise ATS check for automation hints in global scope
CONSOLE_CLEAN = r"""
(function(){
  // Remove any remaining automation globals
  const patterns = ['__webdriver','__driver','__selenium','_Selenium','callSelenium',
                    '_selenium','__nightmare','_phantom','__phantomjs','callPhantom'];
  patterns.forEach(function(p) {
    try { if (window[p] !== undefined) delete window[p]; } catch(e) {}
  });

  // Wrap console.debug — some sites inject their own detector via console patching
  const _origDebug = console.debug;
  console.debug = function(...args) {
    // Filter stack trace lines that reveal automation
    if (args.some(a => typeof a === 'string' && /puppeteer|playwright|selenium/i.test(a))) {
      return;
    }
    return _origDebug.apply(console, args);
  };
})();
"""

# ── Layer 11: Rebrowser — Runtime.enable CDP leak prevention ─────────────────
# Source: rebrowser-patches (https://github.com/rebrowser/rebrowser-patches)
# Issue: Chrome exposes that Runtime.enable was called via execution context
#        auxiliary data. This is the most reliable modern automation signal.
#        Fix: Patch the binding channel that exposes this in user-space JS.
# Note: This is a JS-space mitigation only. Full fix requires patched Chrome.
#       IXBrowser may already patch this at C++ level.
RUNTIME_ENABLE_LEAK = r"""
(function(){
  // Bind console.debug hook to intercept the execution context ID broadcast
  // that rebrowser's research identified as the leak vector.
  const _origDefineProperty = Object.defineProperty;
  const _bannedKeys = new Set(['__pwInitScripts', '__playwright_clock']);
  Object.defineProperty = function(obj, prop, descriptor) {
    if (obj === window && _bannedKeys.has(prop)) return obj;
    return _origDefineProperty.call(this, obj, prop, descriptor);
  };
})();
"""

# ── Full ordered patch sequence ───────────────────────────────────────────────

ALL_PATCHES = [
    ("chrome_complete",     CHROME_COMPLETE),
    ("plugins_realistic",   PLUGINS_REALISTIC),
    ("permissions_patch",   PERMISSIONS_PATCH),
    ("error_stack_norm",    ERROR_STACK_NORM),
    ("iframe_webdriver",    IFRAME_WEBDRIVER),
    ("user_activation",     USER_ACTIVATION),
    ("speech_voices",       SPEECH_VOICES),
    ("webrtc_shield",       WEBRTC_SHIELD),
    ("worker_nav_spoof",    WORKER_NAV_SPOOF),
    ("intl_timezone_patch", INTL_TIMEZONE_PATCH),
    ("console_clean",       CONSOLE_CLEAN),
    ("runtime_enable_leak", RUNTIME_ENABLE_LEAK),
]

# isTrusted spoof is opt-in — only for assessment flows
ASSESSMENT_EXTRA = [
    ("istrusted_spoof", ISTRUSTED_SPOOF),
]


def build_bundle(layers: list[tuple[str, str]] | None = None, assessment: bool = False) -> str:
    """Return a single JS string with all requested patch layers concatenated."""
    selected = layers if layers is not None else ALL_PATCHES
    if assessment:
        selected = selected + ASSESSMENT_EXTRA
    return "\n\n".join(js for _, js in selected)
