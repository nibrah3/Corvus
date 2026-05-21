/**
 * content.js — Orchestration only. No DOM walking, no network.
 * Single responsibility: wire cbWalker + cbRelay together with debounced
 * MutationObserver and visibility tracking, including tab ID resolution.
 *
 * Depends on: dom_walker.js (cbWalker), relay.js (cbRelay) — loaded first.
 */
(function () {
  'use strict';

  var DEBOUNCE_MS = 300;
  var debounceTimer = null;
  var cachedTabId = -1;

  // Resolve our tab ID once from the background service worker, then cache it.
  chrome.runtime.sendMessage({ type: 'getTabId' }, function (resp) {
    if (resp && resp.tabId) cachedTabId = resp.tabId;
    // Relay immediately once we have the tab ID (handles initial page load).
    relayIfVisible();
  });

  function relayIfVisible() {
    if (document.visibilityState !== 'visible') return;
    var data = cbWalker.extract();
    data.tabId = cachedTabId;
    cbRelay.send(data);
  }

  function relayDebounced() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(relayIfVisible, DEBOUNCE_MS);
  }

  // Relay when this tab comes to the foreground.
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') relayIfVisible();
  });

  // Re-relay on DOM mutations (only fires if tab is visible — guard is inside relayIfVisible).
  var observer = new MutationObserver(relayDebounced);
  observer.observe(document.documentElement, {
    childList:     true,
    subtree:       true,
    characterData: true,
    attributes:    false,
  });

}());
