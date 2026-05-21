/**
 * background.js — Service worker. Single responsibility: supply tab ID to content scripts on request.
 * Content scripts cannot read their own tab ID directly; they message us.
 */
chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse) {
  if (msg.type === 'getTabId') {
    sendResponse({ tabId: sender.tab ? sender.tab.id : -1 });
  }
  return false;
});
