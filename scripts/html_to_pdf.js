// Converts HTML to PDF via Chrome CDP — no header/footer
const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');
const path = require('path');
const WebSocket = require('ws');

const inputHtml = path.resolve(process.argv[2]);
const outputPdf = path.resolve(process.argv[3]);
const fileUrl = 'file:///' + inputHtml.replace(/\\/g, '/');
const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PORT = 9334;

const delay = ms => new Promise(r => setTimeout(r, ms));

function getJson(p) {
  return new Promise((resolve, reject) => {
    http.get({ hostname: 'localhost', port: PORT, path: p }, res => {
      let d = '';
      res.on('data', c => d += c);
      res.on('end', () => {
        try {
          // Strip any leading non-JSON text (e.g. Chrome warnings)
          const start = d.search(/[{\[]/);
          resolve(JSON.parse(start >= 0 ? d.slice(start) : d));
        } catch(e) { reject(new Error('JSON parse failed: ' + d.slice(0,200))); }
      });
    }).on('error', reject);
  });
}

function cdp(ws, method, params) {
  return new Promise((resolve, reject) => {
    const id = Math.floor(Math.random() * 1e9);
    const handler = data => {
      const msg = JSON.parse(data);
      if (msg.id === id) {
        ws.off('message', handler);
        msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
      }
    };
    ws.on('message', handler);
    ws.send(JSON.stringify({ id, method, params: params || {} }));
  });
}

async function run() {
  const chrome = spawn(CHROME, [
    `--remote-debugging-port=${PORT}`,
    '--headless=new',
    '--no-sandbox',
    '--disable-gpu',
    '--no-first-run',
    '--disable-extensions',
    'about:blank'
  ], { stdio: 'ignore' });

  await delay(2500);

  // Open a new tab via PUT /json/new
  const tab = await new Promise((resolve, reject) => {
    const req = http.request({ hostname: 'localhost', port: PORT, path: '/json/new', method: 'PUT' }, res => {
      let d = '';
      res.on('data', c => d += c);
      res.on('end', () => { try { resolve(JSON.parse(d)); } catch(e) { reject(e); } });
    });
    req.on('error', reject);
    req.end();
  });
  const wsUrl = tab.webSocketDebuggerUrl;

  const ws = new WebSocket(wsUrl);
  await new Promise((res, rej) => { ws.on('open', res); ws.on('error', rej); });

  await cdp(ws, 'Page.enable');
  await cdp(ws, 'Network.enable');

  // Navigate and wait for load
  await cdp(ws, 'Page.navigate', { url: fileUrl });
  await new Promise(resolve => {
    const handler = data => {
      if (JSON.parse(data).method === 'Page.loadEventFired') {
        ws.off('message', handler);
        resolve();
      }
    };
    ws.on('message', handler);
    setTimeout(resolve, 4000); // fallback timeout
  });

  await delay(1000); // let fonts render

  const result = await cdp(ws, 'Page.printToPDF', {
    displayHeaderFooter: false,
    printBackground: true,
    paperWidth: 8.27,
    paperHeight: 11.69,
    marginTop: 0,
    marginBottom: 0,
    marginLeft: 0,
    marginRight: 0,
    scale: 0.95
  });

  fs.writeFileSync(outputPdf, Buffer.from(result.data, 'base64'));
  console.log(`Done: ${outputPdf}`);

  ws.close();
  chrome.kill();
}

run().catch(e => { console.error(e.message); process.exit(1); });
