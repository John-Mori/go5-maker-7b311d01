'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const source = fs.readFileSync(path.join(__dirname, '..', 'js', 'yt-clicks.js'), 'utf8');
assert(source.includes("addEventListener('compositionstart'"), 'compositionstart must own the live search input');
assert(source.includes("addEventListener('compositionend'"), 'compositionend must commit the search exactly once');
assert(source.includes("ev && ev.isComposing"), 'input events must honor the browser IME flag');
assert(source.includes("if (_histSearchComposing || _histSearchRenderTimer)"), 'background renders must not replace the IME input');
assert(source.includes("queueHistSearchRender_(this, 90)"), 'ordinary input must be debounced instead of rebuilding on every key');
assert(source.includes("list.querySelector('.hist-work-search')"), 'the live search subtree must be reused across background renders');
assert(source.includes("stableMount_.replaceWith(stableHistSearch_)"), 'the same search DOM node must be remounted');
assert(source.includes("_hws.__go5HistSearchWired"), 'a reused input must not accumulate duplicate listeners');

const inputAt = source.indexOf("var _hws = $('histWorkSearch')");
const clearAt = source.indexOf("var _hwsc = $('histWorkSearchClear')", inputAt);
const handler = source.slice(inputAt, clearAt);
const composingGuard = handler.indexOf("if (_histSearchComposing || (ev && ev.isComposing)) return;");
const queuedRender = handler.indexOf("queueHistSearchRender_(this, 90)");
assert(composingGuard >= 0 && queuedRender > composingGuard, 'render must be skipped before the IME composition is committed');
assert(!handler.includes("\n      render();"), 'the input handler must not synchronously replace its own DOM node');

console.log('history search IME tests: ok');
