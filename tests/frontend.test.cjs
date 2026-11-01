'use strict';
// Synthetic tests only: no browser network requests or real host measurements.
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(path.join(__dirname, '..', 'dashboard.html'), 'utf8');
const script = html.split('<script>')[1].split('</script>')[0];
new vm.Script(script);
const source = script.replace('updateStatus();setInterval(updateStatus,1000);poll();', '');
assert.notEqual(source, script, 'Test harness must remove live polling');
const elements = {};
const get = id => elements[id] || (elements[id] = {textContent: '', className: '', dataset: {}});
const document = {getElementById: get, body: {dataset: {}}};
let now = 100000;
class Clock extends Date {
  constructor(...args) { super(...(args.length ? args : [now])); }
  static now() { return now; }
}
const context = vm.createContext({document, innerWidth: 720, innerHeight: 1195,
  Date: Clock, addEventListener() {}, setTimeout() {}, clearTimeout() {}, console});
vm.runInContext(source, context);
const evaluate = text => vm.runInContext(text, context);
assert.equal(evaluate('fmtBytes(1024)'), '1 KB');
assert.equal(evaluate('fmtBytes(2**30)'), '1.0 GB');
assert.equal(evaluate('JSON.stringify(rates([0,400,1200],[0,4,6],2))'), '[100,400]');
assert.equal(evaluate('JSON.stringify(rates([400,0,40],null,2))'), '[0,20]');
assert.equal(evaluate("escapeHTML('<img onerror=1>')"), '&lt;img onerror=1&gt;');
assert.notEqual(evaluate("portKey({address:'127.0.0.1',port:12345})"), evaluate("portKey({address:'0.0.0.0',port:12345})"));
evaluate('updateStatus()'); assert.equal(document.body.dataset.connection, 'waiting');
evaluate('lastOkAt=100000;lastSampleSeenAt=100000;sampleBaseAge=0;updateStatus()'); assert.equal(document.body.dataset.connection, 'live');
now = 110000;
evaluate('lastOkAt=110000;updateStatus()'); assert.equal(document.body.dataset.connection, 'stale');
evaluate('fetchFailed=true;updateStatus()'); assert.equal(document.body.dataset.connection, 'offline');
evaluate('fetchFailed=false;lastOkAt=110000;lastSampleSeenAt=110000;sampleBaseAge=0;updateStatus()'); assert.equal(document.body.dataset.connection, 'live');
console.log('PASS: frontend syntax, intervals, counter reset, formatting, escaping, unique port IDs and connection states');
