// Behaviour of static/js/poll.js with a fake clock, document and jQuery promise.
// Run by webvirtcloud/tests/test_poll_js.py: node poll.test.js static/js/poll.js
const fs = require("fs");
const assert = require("assert");

let now = 0, timers = [], nextId = 1;
global.setTimeout = (fn, ms) => { const id = nextId++; timers.push({ id, at: now + ms, fn }); return id; };
global.clearTimeout = (id) => { timers = timers.filter((t) => t.id !== id); };
function advance(ms) {
    const end = now + ms;
    for (;;) {
        timers.sort((a, b) => a.at - b.at);
        const t = timers[0];
        if (!t || t.at > end) break;
        timers.shift(); now = t.at; t.fn();
    }
    now = end;
}
const listeners = {};
global.document = { hidden: false, addEventListener: (ev, fn) => { listeners[ev] = fn; } };
function setHidden(h) { document.hidden = h; listeners.visibilitychange(); }

// requests: each returns a promise that the test settles. Like jQuery, it runs
// the callbacks in the order they were added, and an exception in one stops
// the ones after it.
let requests = [];
function request() {
    const callbacks = [];
    const r = {
        started: now,
        always(fn) { callbacks.push(fn); return r; },
        done(fn) { callbacks.push(fn); return r; },
        finish() {
            try { callbacks.forEach((fn) => fn({ ok: true })); } catch (e) { r.error = e; }
        },
    };
    requests.push(r);
    return r;
}
let answers = [];
let failNext = false;
function onData(data) {
    answers.push(data);
    if (failNext) { failNext = false; throw new Error("a chart for an unknown device"); }
}
eval(fs.readFileSync(process.argv[2], "utf8"));

const poll = pollWhileVisible(10000, request, onData);
advance(9999); assert.strictEqual(requests.length, 0, "first request after the interval");
advance(1); assert.strictEqual(requests.length, 1);

// a slow answer: no second request while the first is open
advance(45000); assert.strictEqual(requests.length, 1, "no pile-up while a request is open");
requests[0].finish();
advance(9999); assert.strictEqual(requests.length, 1);
advance(1); assert.strictEqual(requests.length, 2, "next one interval after the answer");
requests[1].finish();

// hidden: nothing is asked
setHidden(true);
advance(60000); assert.strictEqual(requests.length, 2, "a hidden page asks nothing");
// shown again: asks at once
setHidden(false); assert.strictEqual(requests.length, 3, "asks at once when shown");
requests[2].finish();
advance(10000); assert.strictEqual(requests.length, 4);

// hidden while a request is open: no new one when it finishes, one on show
setHidden(true); requests[3].finish();
advance(60000); assert.strictEqual(requests.length, 4);
setHidden(false); assert.strictEqual(requests.length, 5);

// briefly hidden while waiting: the pending timer still fires once, no double request
requests[4].finish();
setHidden(true); setHidden(false);
advance(10000); assert.strictEqual(requests.length, 6, "no extra request for a short hide");

// stop: nothing more, also not on show
poll.stop(); requests[5].finish();
setHidden(true); setHidden(false); advance(60000);
assert.strictEqual(requests.length, 6, "stopped");
// start after stop: asks at once, then every interval
poll.start(); assert.strictEqual(requests.length, 7, "start asks at once");
requests[6].finish(); advance(10000); assert.strictEqual(requests.length, 8);
// start while running or waiting adds nothing
poll.start(); assert.strictEqual(requests.length, 8);
requests[7].finish(); poll.start(); advance(9999); assert.strictEqual(requests.length, 8, "start while waiting");
// start while hidden asks nothing until shown
poll.stop(); setHidden(true); poll.start(); assert.strictEqual(requests.length, 8);
setHidden(false); assert.strictEqual(requests.length, 9);
// an error in onData does not stop the polling
assert.strictEqual(answers.length, 8, "each answer reaches onData");
failNext = true; requests[8].finish();
assert.ok(requests[8].error, "the error reaches the page");
advance(10000); assert.strictEqual(requests.length, 10, "polling goes on after an error in onData");

// a first delay of 0: the first request at once, then every interval
poll.stop(); requests[9].finish();
const atOnce = pollWhileVisible(5000, request, onData, 0);
advance(0); assert.strictEqual(requests.length, 11, "first request after firstDelay");
requests[10].finish();
advance(4999); assert.strictEqual(requests.length, 11);
advance(1); assert.strictEqual(requests.length, 12, "then every interval");
atOnce.stop();
console.log("poll.js: all checks passed");
