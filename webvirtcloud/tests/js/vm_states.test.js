// Behaviour of static/js/vm_states.js (with static/js/poll.js) under a fake
// clock, document and jQuery. Run by webvirtcloud/tests/test_poll_js.py:
// node vm_states.test.js static/js/poll.js static/js/vm_states.js
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
global.document = { hidden: false, addEventListener() {}, activeElement: null, querySelector: () => null };
global.window = { backgroundJobRunning: false, location: { reload() { window.reloads += 1; } }, reloads: 0 };

// each poll answers with what the test puts in `answer`
let answer = null, asked = [];
global.$ = { getJSON(url) {
    asked.push(url);
    const value = answer;
    const r = { always(f) { f(); return r; }, done(f) { f(value); return r; } };
    return r;
} };
eval(fs.readFileSync(process.argv[2], "utf8"));
eval(fs.readFileSync(process.argv[3], "utf8"));

const base = { "1": { ok: true, vms: { "u-a": ["web", 1], "u-b": ["db", 5] } }, "2": { ok: false } };
followVmStates("/instances/states/?compute=1");

// the first answer, asked at once, is where it starts; the same VMs in another order change nothing
answer = { computes: base };
advance(0);
assert.strictEqual(asked.length, 1, "asks at once");
answer = { computes: { "2": { ok: false }, "1": { ok: true, vms: { "u-b": ["db", 5], "u-a": ["web", 1] } } } };
advance(5000);
assert.deepStrictEqual(asked, ["/instances/states/?compute=1", "/instances/states/?compute=1"], "asks every 5 s");
assert.strictEqual(window.reloads, 0, "nothing changed");

// a VM stopped, a new VM, a removed one, a renamed one, a host read again: each reloads
for (const host1 of [{ ok: true, vms: { "u-a": ["web", 5], "u-b": ["db", 5] } },
                     { ok: true, vms: { "u-a": ["web", 1], "u-b": ["db", 5], "u-c": ["new", 5] } },
                     { ok: true, vms: { "u-a": ["web", 1] } }, { ok: true, vms: { "u-a": ["web2", 1], "u-b": ["db", 5] } }]) {
    window.reloads = 0;
    answer = { computes: { "1": host1, "2": { ok: false } } };
    advance(5000);
    assert.strictEqual(window.reloads, 1, JSON.stringify(host1));
    answer = { computes: base };  // the reloaded page starts again from here
    advance(5000);
    window.reloads = 0;
}

// not while the page is in use or the job panel shows something: the next answer tells again
for (const [what, set, unset] of [
    ["a dialog", () => { document.querySelector = (s) => s === ".modal.show" ? {} : null; }, () => { document.querySelector = () => null; }],
    ["the filter", () => { document.activeElement = { matches: () => true }; }, () => { document.activeElement = null; }],
    ["a job outcome", () => { window.backgroundJobRunning = true; }, () => { window.backgroundJobRunning = false; }],
]) {
    window.reloads = 0;
    answer = { computes: { "1": { ok: true, vms: { "u-a": ["web", 5], "u-b": ["db", 5] } }, "2": { ok: false } } };
    set();
    advance(5000);
    assert.strictEqual(window.reloads, 0, "waits for " + what);
    unset();
    advance(5000);
    assert.strictEqual(window.reloads, 1, "then reloads: " + what);
    answer = { computes: base };
    advance(5000);
}
console.log("ok");
