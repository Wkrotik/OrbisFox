// Actual generated Gecko prefs, evaluated with host pref-registration doubles.
// Not Firefox's native preference parser, script-security service or firmware.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const engine = fs.readFileSync('build/gecko-layout/dist/bin/greprefs.js', 'utf8');
const overrides = fs.readFileSync('gecko/orbisfox/fixtures/default-prefs.js', 'utf8');
let count = 0;
for (let cycle = 0; cycle < 32; ++cycle) {
  const defaults = new Map();
  const pref = (name, value) => {
    assert.equal(typeof name, 'string');
    assert(['string', 'boolean', 'number'].includes(typeof value));
    defaults.set(name, value);
  };
  const context = {pref, sticky_pref: pref, locked_pref: pref,
                   sticky: Symbol('host sticky marker'), locked: Symbol('host locked marker')};
  vm.runInNewContext(engine, context, {timeout: 1000});
  assert.equal(defaults.get('javascript.enabled'), true);
  count = defaults.size; assert(count > 200);
  vm.runInNewContext(overrides, context, {timeout: 1000});
  assert.equal(defaults.get('javascript.enabled'), true);
  assert.equal(defaults.get('gfx.webrender.software'), true);
  assert.equal(defaults.get('layers.gpu-process.enabled'), false);
  assert.equal(defaults.get('webgl.disabled'), true);
  assert.equal(defaults.get('media.hardware-video-decoding.enabled'), false);
  assert.equal(defaults.get('media.hardware-video-encoding.enabled'), false);
}
console.log(`Generated GRE defaults: ${count} prefs, real JavaScript-enabled default and retained Orbis software/no-hardware overrides, 32 cycles PASS (host registration doubles)`);
fs.mkdirSync('build/generated-gecko-prefs-host', {recursive: true});
fs.writeFileSync('build/generated-gecko-prefs-host/test-report.json', JSON.stringify({
  passed: true, cycles: 32, generatedPrefs: count, javascriptEnabledDefault: true,
  generatedSourceSha256: crypto.createHash('sha256').update(engine).digest('hex'),
  hostPrefRegistrationDoubles: true, nativePreferenceParserVerified: false,
  firmwareVerified: false, pageJavaScriptVerified: false
}, null, 2) + '\n');
