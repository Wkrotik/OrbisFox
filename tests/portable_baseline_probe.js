// Host-only semantic probe. Run with --no-jit-backend in both interpreter modes.
const started = dateNow();
function hot(object, count) {
  let result = 0;
  for (let i = 0; i < count; ++i) result += object.value + (i & 255);
  return result;
}
let checksum = 0;
for (let pass = 0; pass < 8; ++pass) {
  const count = 200000, remainder = count % 256;
  const expected = Math.floor(count / 256) * 32640 + remainder * (remainder - 1) / 2;
  assertEq(hot({value: pass}, count), expected + pass * count);
  const object = {value: pass};
  Object.defineProperty(object, 'twice', {get() { return this.value * 2; }});
  const proxy = new Proxy(object, {get(target, key) { return Reflect.get(target, key); }});
  assertEq(proxy.twice, pass * 2);
  const closure = ((value) => (n) => value + n)(pass);
  assertEq(closure(7), pass + 7);
  let finalized = 0;
  try { try { throw pass; } finally { ++finalized; } }
  catch (error) { assertEq(error, pass); }
  assertEq(finalized, 1);
  const bytes = new Uint8Array([pass, 2, 3]);
  assertEq(bytes.reduce((a, b) => a + b), pass + 5);
  assertEq(/(a+)(b)/.exec('aaab')[1], 'aaa');
  const retained = Array.from({length: 2000}, (_, i) => ({value: i, owner: object}));
  gc();
  checksum += retained[1999].value;
  assertEq(retained[1999].owner.value, pass);
}
function* values() { yield 3; yield 4; }
assertEq([...values()].join(','), '3,4');
let asyncResult = 0;
(async () => { asyncResult = await Promise.resolve(19); })();
drainJobQueue();
assertEq(asyncResult, 19);
let overflow = false;
try { (function recurse() { return recurse() + 1; })(); }
catch (error) { overflow = error instanceof InternalError; }
assertEq(overflow, true);
gc();
print(JSON.stringify({portableProbe: true, checksum, asyncResult, overflow, elapsedMs: dateNow() - started}));
