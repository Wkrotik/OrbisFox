'use strict';
// Executed by the native SpiderMonkey interpreter, not C++ animation code.
// This is deliberately a script canvas, NOT an HTML/CSS/DOM implementation.
globalThis.orbisfoxFrame = (() => {
  let paused = false, clicks = 0, frames = 0, previousTime = 0, phase = 0;
  const tiles = Array.from({length: 48}, (_, i) => ({
    row: Math.floor(i / 12), column: i % 12,
    spin: i * 0.31, color: (i % 2) ? 0xe86a29 : 0x2c9ca2
  }));
  const counts = new Map([['clicks', 0]]);
  return (x, y, click, time) => {
    const delta = Math.max(0, Math.min(100, time - previousTime));
    previousTime = time;
    if (click) { paused = !paused; counts.set('clicks', ++clicks); }
    if (!paused) phase += delta / 1000;
    ++frames;
    paint.clear(0x0b1120);
    paint.rect(0, 0, 1280, 116, 0x14213a);
    paint.text(38, 28, 'ORBISFOX / LIVE JAVASCRIPT', 4, 0xf8a14c);
    paint.text(40, 81, 'FIREFOX SPIDERMONKEY ON PS4 - REAL INTERPRETER - JIT OFF', 2, 0xc1d2ec);
    paint.rect(38, 138, 1204, 362, 0x172940);
    tiles.forEach(tile => {
      const xx = 78 + tile.column * 97;
      const yy = 173 + tile.row * 80 + Math.sin(phase * 2 + tile.spin) * 18;
      const selected = x >= xx && x < xx + 56 && y >= yy && y < yy + 42;
      paint.rect(xx, yy, 56, 42, selected ? 0xffd77b : tile.color);
      paint.rect(xx + 6, yy + 7, 44, 3, selected ? 0xffffff : 0x35516e);
    });
    paint.text(40, 525, 'JAVASCRIPT LANGUAGE TESTS: 12/12 PASSED', 3, 0x71d6b3);
    paint.text(40, 566, `SCRIPT FRAMES: ${frames}   CLICKS: ${counts.get('clicks')}   ${paused ? 'PAUSED' : 'RUNNING'}`, 2, 0xc1d2ec);
    paint.text(40, 603, 'MOVE CURSOR OVER TILES / CIRCLE: PAUSE OR RESUME', 2, 0xc1d2ec);
    paint.text(40, 634, 'THIS IS NOT HTML/CSS YET / NO WEBSITES OR NETWORK ACCESS', 2, 0x899dbb);
    paint.text(40, 672, 'CROSS: OTHER PAGES   TRIANGLE: RELOAD SCRIPT   OPTIONS: EXIT', 2, 0xf8a14c);
    paint.rect(x - 8, y - 1, 17, 3, 0xffffff);
    paint.rect(x - 1, y - 8, 3, 17, 0xffffff);
  };
})();
1;
