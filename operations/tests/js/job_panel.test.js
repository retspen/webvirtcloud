// operations/tests/js/job_panel.test.js
// node job_panel.test.js static/js/poll.js operations/static/operations/job_panel.js
const fs = require("fs");
const assert = require("assert");

let now = 0, timers = [], nextId = 1;
global.setTimeout = (fn, ms) => { const id = nextId++; timers.push({ id, at: now + (ms || 0), fn }); return id; };
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
const realNow = Date.now;
Date.now = () => 1700000000000 + now;
global.document = { hidden: false, addEventListener() {}, activeElement: null, querySelector: () => null };
global.window = { backgroundJobRunning: false,
                  location: { reload() { window.reloaded = true; }, assign(url) { window.opened = url; } } };

// requests settle only when the test says so; callbacks run in registration order
let open = [];
function req(url) {
    const cbs = [];
    const r = { url, settled: false,
        always(f) { cbs.push(["always", f]); return r; },
        done(f) { cbs.push(["done", f]); return r; },
        fail(f) { cbs.push(["fail", f]); return r; },
        settle(ok, value) {
            r.settled = true;
            cbs.forEach(([t, f]) => { if (t === "always" || t === (ok ? "done" : "fail")) f(value); });
        } };
    open.push(r);
    return r;
}
// a failed request passes a jqXHR-like {status: N}
function answer(url, value, ok = true) {
    const r = open.find((x) => x.url === url && !x.settled);
    assert.ok(r, "no open request to " + url);
    r.settle(ok, value);
}
global.$ = { getJSON: req, ajax: (o) => req(o.url) };
let listeners = {};
const el = { innerHTML: "", addEventListener(ev, f) { listeners[ev] = f; } };
eval(fs.readFileSync(process.argv[2], "utf8"));
eval(fs.readFileSync(process.argv[3], "utf8"));

const urls = { resource: "/r", job: (id) => "/j/" + id, cancel: (id) => "/c/" + id };
const seen = new Date(1700000000000).toISOString();
const running = { id: "a", label: "Delete snapshot", state: "running", phase: "Merging", progress_done: 1,
                  progress_total: 4, cancellable: false, result: {}, error: "" };
const empty = { jobs: [], others: [], short_operation: false, worker_last_seen: seen };

jobPanel(el, urls, "tok");
advance(0);
answer("/r", { ...empty, jobs: [running] });
assert.ok(el.innerHTML.includes("Delete snapshot") && el.innerHTML.includes("25%"), "shows the job and real progress");

// one colour per state (operations/tests/test_views.py checks the same map in the template filter)
assert.deepStrictEqual(JOB_STATE_COLORS, { queued: "secondary", running: "primary", cancelling: "info",
    succeeded: "success", failed: "danger", cancelled: "secondary", uncertain: "warning" });
assert.ok(el.innerHTML.includes('class="alert alert-primary') && el.innerHTML.includes('<span class="badge bg-primary">running</span>')
    && el.innerHTML.includes('<span class="small text-body-secondary">Merging</span>'), "state badge and muted phase");
assert.strictEqual(window.backgroundJobRunning, true);

assert.ok(!el.innerHTML.includes("Finishing"), "a number below 99 %");

// from 99 % the bar is full, striped, animated and says Finishing
advance(3000);
answer("/r", { ...empty, jobs: [{ ...running, progress_done: 99, progress_total: 100 }] });
assert.ok(el.innerHTML.includes("progress-bar-striped progress-bar-animated"), "striped and animated");
assert.ok(el.innerHTML.includes("Finishing\u2026") && el.innerHTML.includes('aria-valuenow="100"')
    && el.innerHTML.includes("width:100%") && !el.innerHTML.includes("99%"), "full width, no number");
advance(3000);
answer("/r", { ...empty, jobs: [{ ...running, state: "cancelling", progress_done: 99, progress_total: 100 }] });
assert.ok(!el.innerHTML.includes("Finishing") && el.innerHTML.includes("99%"), "only a running job is finishing");
advance(3000);
answer("/r", { ...empty, jobs: [running] });
assert.ok(!el.innerHTML.includes("Finishing"), "back to a number");

// the next poll goes out 3 s after the answer
advance(3000);
answer("/r", { ...empty, jobs: [running] });

// the job finishes between polls: the panel asks for it by id, keeps the flag meanwhile
advance(3000);
answer("/r", empty);
assert.strictEqual(window.backgroundJobRunning, true, "still true while the outcome is fetched");
answer("/j/a", { status: 0 }, false); // a network error: asked again on the next poll
advance(3000);
answer("/r", empty);
answer("/j/a", { ...running, state: "succeeded", result: { left_behind: ["/pool/a.one"], warning: "not <thawed>" } });
assert.ok(el.innerHTML.includes('<li class="text-break"><code>/pool/a.one</code></li>'), "shows the warning from the result");
assert.ok(el.innerHTML.includes('<div class="small mt-2">not &lt;thawed&gt;</div>'), "shows the result's warning escaped");
assert.ok(el.innerHTML.includes('class="alert alert-success') && el.innerHTML.includes('<span class="badge bg-success">succeeded</span>')
    && el.innerHTML.includes('<div class="ms-auto d-flex gap-2"><button type="button" class="btn btn-sm btn-primary" data-refresh'),
    "the outcome has the state colour and its buttons on the right");
assert.strictEqual(window.backgroundJobRunning, true, "keeps backgroundJobRunning until dismissed");

listeners.click({ target: { dataset: { dismiss: "a" } } });
assert.strictEqual(window.backgroundJobRunning, false);
assert.ok(!window.reloaded);

// a job that ended before the first poll: shown from the submitted ids
open = []; timers = [];
const el2 = { innerHTML: "", addEventListener() {} };
jobPanel(el2, urls, "tok", ["b"]);
advance(0);
answer("/r", empty);
answer("/j/b", { ...running, id: "b", state: "failed", error: "refused" });
assert.ok(el2.innerHTML.includes("refused") && el2.innerHTML.includes('class="alert alert-danger'),
    "shows a job that finished before the first poll");

// a late answer for a dismissed job does not bring it back
const el3 = { innerHTML: "", addEventListener(ev, f) { listeners3 = f; } };
let listeners3;
jobPanel(el3, urls, "tok", ["c"]);
advance(0);
answer("/r", empty);
listeners3({ target: { dataset: { dismiss: "c" } } });
answer("/j/c", { ...running, id: "c", state: "succeeded" });
assert.ok(!el3.innerHTML.includes("Delete snapshot"), "a dismissed outcome stays dismissed");

// an uncertain job stays in the list (it keeps its claims): its error shows
open = []; timers = [];
let writes = 0, html4 = "";
const el4 = { addEventListener() {},
              get innerHTML() { return html4; }, set innerHTML(v) { writes++; html4 = v; } };
jobPanel(el4, urls, "tok");
advance(0);
answer("/r", { ...empty, jobs: [{ ...running, state: "uncertain", error: "check the disks" }] });
assert.ok(el4.innerHTML.includes('<span class="badge bg-warning text-dark">uncertain</span>'), "dark text on the yellow badge");
assert.ok(el4.innerHTML.includes("check the disks") && el4.innerHTML.includes('class="alert alert-warning'),
    "an uncertain job in the list shows its error");
// an unchanged answer does not rebuild the panel (a focused button keeps its focus)
advance(3000);
answer("/r", { ...empty, jobs: [{ ...running, state: "uncertain", error: "check the disks" }] });
assert.strictEqual(writes, 1, "an unchanged answer leaves the panel alone");

// the panel showing nothing leaves a flag the please-wait dialog set alone
open = []; timers = [];
jobPanel({ innerHTML: "", addEventListener() {} }, urls, "tok");
window.backgroundJobRunning = true;
advance(0);
answer("/r", empty);
assert.strictEqual(window.backgroundJobRunning, true, "a foreground operation keeps its guard");

// a job the user may not see or that is gone (403/404) is not asked for again
open = []; timers = [];
const el6 = { innerHTML: "", addEventListener() {} };
window.backgroundJobRunning = false;
jobPanel(el6, urls, "tok");
advance(0);
answer("/r", { ...empty, jobs: [{ ...running, id: "d" }] });
assert.strictEqual(window.backgroundJobRunning, true);
advance(3000);
answer("/r", empty);
answer("/j/d", { status: 404 }, false);
assert.strictEqual(el6.innerHTML, "", "a missing job leaves nothing behind");
assert.strictEqual(window.backgroundJobRunning, false, "the guard goes back once the panel holds nothing");
advance(3000);
answer("/r", empty);
assert.ok(!open.some((r) => r.url === "/j/d" && !r.settled), "a missing job is not asked for again");
// remembered ids hold the page's own reload at once, before the first poll answers
open = []; timers = [];
window.backgroundJobRunning = false;
const el7 = { innerHTML: "", addEventListener() {} };
jobPanel(el7, urls, "tok", ["e"]);
assert.strictEqual(window.backgroundJobRunning, true, "set at init, not after the first poll");
advance(0);
answer("/r", empty, false); // a failed first poll keeps it
assert.strictEqual(window.backgroundJobRunning, true, "kept after a failed first poll");
advance(3000);
answer("/r", empty);
answer("/j/e", { status: 404 }, false);
assert.strictEqual(window.backgroundJobRunning, false, "released once the remembered job is settled");

// a running (not only a queued) job with a stale lease shows the worker warning
open = []; timers = [];
const el8 = { innerHTML: "", addEventListener() {} };
const stale = new Date(Date.now() - 120000).toISOString();
jobPanel(el8, urls, "tok");
advance(0);
answer("/r", { ...empty, worker_last_seen: stale, jobs: [running] });
assert.ok(el8.innerHTML.includes("Worker unavailable"), "a running job with a stale lease warns");
advance(3000);
answer("/r", { ...empty, worker_last_seen: stale, jobs: [{ ...running, state: "cancelling" }] });
assert.ok(el8.innerHTML.includes("Worker unavailable"), "a cancelling job with a stale lease warns");
advance(3000);
answer("/r", { ...empty, worker_last_seen: new Date(Date.now()).toISOString(), jobs: [running] });
assert.ok(!el8.innerHTML.includes("Worker unavailable"), "a fresh lease does not warn");
advance(3000);
answer("/r", { ...empty, worker_last_seen: stale, jobs: [{ ...running, state: "uncertain" }] });
assert.ok(!el8.innerHTML.includes("Worker unavailable"), "an uncertain job waits for an administrator, not the worker");
advance(3000);
answer("/r", { ...empty, worker_last_seen: stale, jobs: [{ ...running, in_request: true }] });
assert.ok(!el8.innerHTML.includes("Worker unavailable"), "a job a request runs does not wait for the worker");
advance(3000);
answer("/r", { ...empty, worker_last_seen: stale, jobs: [{ ...running, in_request: true },
                                                        { ...running, id: "w", state: "queued", in_request: false }] });
assert.ok(el8.innerHTML.includes("Worker unavailable"), "a queued job beside it still warns");

// cancel: the button is disabled while the request runs; a refusal or a network error shows; the list is asked again
open = []; timers = [];
let click9;
const el9 = { innerHTML: "", addEventListener(ev, f) { click9 = f; } };
const queued = { ...running, id: "q", state: "queued", cancellable: true, progress_total: null };
jobPanel(el9, urls, "tok");
advance(0);
answer("/r", { ...empty, jobs: [queued] });
assert.ok(el9.innerHTML.includes('data-cancel="q">Cancel</button>'), "an enabled cancel button");
click9({ target: { dataset: { cancel: "q" } } });
assert.ok(el9.innerHTML.includes('data-cancel="q" disabled>'), "disabled while the request runs");
answer("/c/q", { status: 400, responseJSON: { detail: "This job cannot be cancelled once it has started" } }, false);
assert.ok(el9.innerHTML.includes("This job cannot be cancelled once it has started")
    && el9.innerHTML.includes('class="alert alert-danger'), "the server's reason shows");
assert.ok(open.some((r) => r.url === "/r" && !r.settled), "the list is asked again at once");
answer("/r", { ...empty, jobs: [{ ...queued, state: "running", cancellable: false }] });
assert.ok(el9.innerHTML.includes("cannot be cancelled") && !el9.innerHTML.includes("data-cancel"),
    "the reason stays after the refresh");
click9({ target: { dataset: { dismissError: "1" } } });
assert.ok(!el9.innerHTML.includes("cannot be cancelled"), "the reason can be dismissed");
advance(3000);
answer("/r", { ...empty, jobs: [queued] });
click9({ target: { dataset: { cancel: "q" } } });
answer("/c/q", { status: 0 }, false);
assert.ok(el9.innerHTML.includes("could not be reached"), "a network error shows");

// track(id): the panel follows a job the page just started and asks for the list at once
open = []; timers = [];
window.backgroundJobRunning = false;
const el10 = { innerHTML: "", addEventListener() {} };
const panel = jobPanel(el10, urls, "tok");
advance(0);
answer("/r", empty);
assert.strictEqual(window.backgroundJobRunning, false);
panel.track("t");
assert.strictEqual(window.backgroundJobRunning, true, "a tracked job holds the page's reload");
assert.ok(open.some((r) => r.url === "/r" && !r.settled), "the list is asked for at once");
answer("/r", empty);
answer("/j/t", { ...running, id: "t", label: "Upload", state: "cancelled" });
assert.ok(el10.innerHTML.includes("Upload") && el10.innerHTML.includes('<span class="badge bg-secondary">cancelled</span>'),
    "the tracked job's outcome shows");

// a list answer older than the job, then its detail still active: the panel keeps following it
open = []; timers = [];
const el11 = { innerHTML: "", addEventListener() {} };
const panel11 = jobPanel(el11, urls, "tok");
advance(0);
answer("/r", empty);
panel11.track("u");
answer("/r", empty);
answer("/j/u", { ...running, id: "u", label: "Upload" });
assert.ok(!open.some((r) => !r.settled && r.url === "/j/u"), "an active detail is not asked for again at once");
assert.strictEqual(window.backgroundJobRunning, true, "still followed");
advance(3000);
answer("/r", empty);
assert.strictEqual(open.filter((r) => !r.settled && r.url === "/j/u").length, 1, "asked again once per poll");
window.reloaded = false;
answer("/j/u", { ...running, id: "u", label: "Upload", state: "succeeded" });
assert.ok(window.reloaded, "a job that succeeds without a warning reloads the page: it shows the job's effect");
assert.ok(!el11.innerHTML.includes('<span class="badge bg-success">succeeded</span>'), "not shown as well");

// a job that made a VM opens its page; a warning keeps the outcome, with Open; only a path of this site
open = []; timers = []; window.reloaded = false; window.opened = null;
const elv = { innerHTML: "", addEventListener() {} };
jobPanel(elv, urls, "tok", ["v"]);
advance(0);
answer("/r", empty);
answer("/j/v", { ...running, id: "v", label: "Clone VM", state: "succeeded", result: { open: "/instances/9/" } });
assert.ok(window.opened === "/instances/9/" && !window.reloaded, "opens the clone's page");
for (const [result, shown] of [[{ open: "/instances/9/", warning: "not started" }, true],
                               [{ open: "//evil.example.com/" }, false], [{ open: "javascript:alert(1)" }, false]]) {
    open = []; timers = []; window.reloaded = false; window.opened = null;
    const elw = { innerHTML: "", addEventListener() {} };
    jobPanel(elw, urls, "tok", ["w"]);
    advance(0);
    answer("/r", empty);
    answer("/j/w", { ...running, id: "w", state: "succeeded", result });
    assert.strictEqual(window.opened, null, JSON.stringify(result));
    assert.strictEqual(elw.innerHTML.includes('href="/instances/9/">Open</a>'), shown, JSON.stringify(result));
}

// a dialog open or a field in use: the outcome waits in the panel, with Refresh
for (const [label, doc] of [["dialog", { querySelector: (s) => s === ".modal.show" ? {} : null }],
                            ["field", { activeElement: { matches: (s) => s === "input, select, textarea" } }]]) {
    open = []; timers = []; window.reloaded = false;
    Object.assign(document, { activeElement: null, querySelector: () => null }, doc);
    const elm = { innerHTML: "", addEventListener() {} };
    jobPanel(elm, urls, "tok", ["m"]);
    advance(0);
    answer("/r", empty);
    answer("/j/m", { ...running, id: "m", label: "Clone", state: "succeeded" });
    assert.ok(!window.reloaded && elm.innerHTML.includes('<span class="badge bg-success">succeeded</span>')
        && elm.innerHTML.includes("data-refresh"), "with a " + label + ": the outcome with Refresh, no reload");
}
Object.assign(document, { activeElement: null, querySelector: () => null });

// an XML edit not saved: no reload, as for the page's status poll
open = []; timers = []; window.reloaded = false;
window.xmlEditUnsaved = () => true;
const elx = { innerHTML: "", addEventListener() {} };
jobPanel(elx, urls, "tok", ["x"]);
advance(0);
answer("/r", empty);
answer("/j/x", { ...running, id: "x", state: "succeeded" });
assert.ok(!window.reloaded && elx.innerHTML.includes("data-refresh"), "an unsaved XML edit keeps the page");
delete window.xmlEditUnsaved;

// another job's outcome shown or still awaited: a quiet success does not wipe it
open = []; timers = []; window.reloaded = false;
const elo = { innerHTML: "", addEventListener() {} };
jobPanel(elo, urls, "tok", ["f", "s", "w"]);
advance(0);
answer("/r", empty);
answer("/j/f", { ...running, id: "f", label: "Migrate", state: "failed", error: "no route" });
answer("/j/s", { ...running, id: "s", label: "Clone", state: "succeeded" });
assert.ok(!window.reloaded && elo.innerHTML.includes("no route") && elo.innerHTML.includes("Clone"),
    "the failure stays, the success shows beside it");
answer("/j/w", { ...running, id: "w", label: "Snapshot", state: "succeeded" });
assert.ok(!window.reloaded, "still not while an outcome is shown");
open = []; timers = []; window.reloaded = false;
const elp = { innerHTML: "", addEventListener() {} };
jobPanel(elp, urls, "tok", ["s2", "f2"]);
advance(0);
answer("/r", empty);
answer("/j/s2", { ...running, id: "s2", state: "succeeded" });
assert.ok(!window.reloaded, "not while another outcome is awaited");
answer("/j/f2", { ...running, id: "f2", state: "failed", error: "refused" });
assert.ok(elp.innerHTML.includes("refused"), "which then shows");
// another job still running: its outcome would be lost to a reload
open = []; timers = []; window.reloaded = false;
const elr = { innerHTML: "", addEventListener() {} };
jobPanel(elr, urls, "tok", ["s3"]);
advance(0);
answer("/r", { ...empty, jobs: [{ ...running, id: "r3" }] });
answer("/j/s3", { ...running, id: "s3", state: "succeeded" });
assert.ok(!window.reloaded, "not while another job runs");
Date.now = realNow;
console.log("ok");
