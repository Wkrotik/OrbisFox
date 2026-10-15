// Actual storage gate with explicit mozStorage/file/statement doubles.
// Verifies sequencing/error gates only, not real SQLite, persistence or firmware.
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync('gecko/orbisfox/fixtures/storage-probe.js', 'utf8');
function run(failure = '') {
  const trace = [], logs = [];
  let opens = 0, reads = 0, closes = 0, finalizes = 0, row = 'OrbisFox SQLite durable probe 🦊', previous = row;
  const execute = sql => {
    trace.push(sql);
    if (failure === 'sql') throw Error('SQLite I/O error');
    if (sql === 'BEGIN IMMEDIATE') previous = row;
    if (sql.startsWith('UPDATE ')) row = 'rollback sentinel';
    if (sql === 'ROLLBACK') row = previous;
  };
  const service = {openUnsharedDatabase(file) {
    ++opens; assert.equal(file.path, '/data/orbisfox/gecko-profile/mozstorage-bringup.sqlite');
    if (failure === 'open') throw Error('VFS unavailable');
    return {executeSimpleSQL: execute,
      createStatement(sql) {
        assert.equal(sql, 'SELECT value FROM orbisfox_probe WHERE id = 1');
        return {executeStep() {return failure !== 'missing';},
          getUTF8String(index) {assert.equal(index, 0); ++reads;
            return failure === 'reopen' && opens === 2 ? 'wrong durable data' : row;},
          finalize() {++finalizes;}};
      }, close() {++closes;}
    };
  }};
  const Cc = {'@mozilla.org/storage/service;1': {getService() {
    if (failure === 'service') throw Error('Storage initialization failed'); return service;
  }}, '@mozilla.org/file/local;1': {createInstance() {return {initWithPath(path) {this.path = path;}};}}};
  const context = {}; vm.runInNewContext(source, context);
  let result = false, error;
  try {result = context.verifyTrustedPersistentStorage(Cc, {}, {log(message) {logs.push(message);}});}
  catch (failure) {error = failure;}
  return {result, error, trace, logs, opens, closes, reads, finalizes};
}
for (let cycle = 0; cycle < 32; ++cycle) {
  const good = run(); assert(good.result); assert(!good.error);
  assert.equal(good.opens, 2); assert.equal(good.closes, 2); assert.equal(good.reads, 3); assert.equal(good.finalizes, 3);
  assert.deepEqual(good.trace.map(s => s.split(' ')[0]), ['CREATE', 'BEGIN', 'INSERT', 'COMMIT', 'BEGIN', 'UPDATE', 'ROLLBACK']);
  assert(good.logs.some(s => s.endsWith('rollback PASS')));
  for (const failure of ['service', 'open', 'sql', 'missing', 'reopen']) {
    const bad = run(failure); assert(!bad.result); assert(bad.error);
    assert(!bad.logs.some(s => s.endsWith('rollback PASS')));
    if (['sql', 'missing', 'reopen'].includes(failure)) assert(bad.closes > 0);
  }
}
console.log('Actual mozStorage probe helper: service/open/SQL/row errors, commit/reopen/UTF-8/rollback sequence, statement finalization/connection close, 32 cycles PASS (XPCOM doubles)');
