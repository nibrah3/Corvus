/**
 * relay.js — HTTP relay only. No DOM access, no orchestration.
 * Single responsibility: send a data object to the local receiver server.
 *
 * Exposes: window.cbRelay.send(data) → void
 */
(function (global) {
  'use strict';

  var RECEIVER_URL = 'http://127.0.0.1:8711/dom';
  var RETRY_DELAYS = [1000, 2000, 4000, 8000]; // backoff steps in ms

  function send(data, attempt) {
    attempt = attempt || 0;
    fetch(RECEIVER_URL, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(data),
    }).catch(function () {
      if (attempt < RETRY_DELAYS.length) {
        setTimeout(function () { send(data, attempt + 1); }, RETRY_DELAYS[attempt]);
      }
      // After all retries exhausted, drop silently
    });
  }

  global.cbRelay = { send: send };

}(window));
