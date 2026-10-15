// Actual launcher readTrustedFixture body with explicit host XPCOM stream doubles.
// Not an XPConnect, console I/O, channel, parser, DOM or rendering certification.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('gecko/orbisfox/fixtures/gecko-startup.js', 'utf8');
const body = source.slice(source.indexOf('function readTrustedFixture('), source.indexOf('\n(() => {'));
const context = {};
vm.runInNewContext(body, context);
const fixture = fs.readFileSync('gecko/orbisfox/fixtures/offline.html', 'utf8');
function run(text, failure, fileSize = Buffer.byteLength(text), isFile = true) {
  const state = { initialized: false, closed: false, streamClosed: false, offset: 0 };
  const stream = { init() { state.initialized = true; }, close() { state.streamClosed = true; } };
  const converter = {
    init(input, charset, size, replacement) {
      assert.equal(input, stream); assert.equal(charset, 'UTF-8'); assert.equal(replacement, 0);
      if (failure === 'init') throw Error('converter init failure');
    },
    readString(size, output) {
      if (failure === 'read') throw Error('strict UTF-8/read failure');
      output.value = text.slice(state.offset, state.offset + 7);
      state.offset += output.value.length;
      return output.value.length;
    },
    close() { state.closed = true; }
  };
  const Cc = {
    '@mozilla.org/network/file-input-stream;1': {createInstance() {return stream;}},
    '@mozilla.org/intl/converter-input-stream;1': {createInstance() {return converter;}}
  };
  const Ci = {};
  let result, error;
  try { result = context.readTrustedFixture(Cc, Ci, {fileSize, isFile() {return isFile;}}); }
  catch (e) {error = e;}
  return {state, result, error};
}
for (let cycle = 0; cycle < 32; ++cycle) {
  const valid = run(fixture); assert.equal(valid.result, fixture); assert(valid.state.closed);
  const uri = 'data:text/html;charset=utf-8,' + encodeURIComponent(valid.result);
  assert.equal(decodeURIComponent(uri.slice(uri.indexOf(',') + 1)), fixture);
  for (const [text, failure, size, file] of [[fixture, 'read'], [fixture, 'init'], ['', null],
      ['invalid html', null], [fixture, null, 65537], [fixture, null, 5481, false],
      ['<!doctype html>' + 'x'.repeat(65537), null, 5481]]) {
    const bad = run(text, failure, size, file); assert(bad.error);
    if (bad.state.initialized) assert(bad.state.closed || bad.state.streamClosed);
  }
}
console.log('Actual fixture-reader helper: exact content / data URI roundtrip / bounds / errors / cleanup, 32 cycles PASS (host stream doubles only)');
