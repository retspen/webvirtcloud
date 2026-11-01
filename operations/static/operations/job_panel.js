// The job panel of a resource page (operations framework). It polls the
// resource's jobs, shows progress and outcomes, and keeps the page's own
// status poll from reloading (backgroundJobRunning) while it shows anything.
// A job that succeeds without a warning reloads the page instead.

// The Bootstrap colour of each job state, for badges and alerts; the jobs
// pages use the same map (operations/templatetags/operations.py)
var JOB_STATE_COLORS = {
    queued: "secondary", running: "primary", cancelling: "info", succeeded: "success",
    failed: "danger", cancelled: "secondary", uncertain: "warning",
};

function jobPanel(element, urls, csrfToken, initialIds) {
    var shown = {};     // id -> job in the last active list
    var pending = {};   // id -> true: left the list (or just submitted), outcome not fetched yet
    var inflight = {};  // id -> true: its outcome is being fetched
    var dismissed = {}; // id -> true: never shown again
    var outcomes = {};  // id -> finished job, until dismissed
    var cancelling = {}; // id -> true: its cancel request runs
    var notice = "";    // why the last cancel failed, until dismissed
    (initialIds || []).forEach(function (id) { pending[id] = true; });
    var last = { jobs: [], others: [], short_operation: false, worker_last_seen: null };
    var rendered = null; // the panel's last html: an unchanged one is not rebuilt (focus stays)
    var holding = false; // the panel set backgroundJobRunning (the please-wait dialog sets it too)
    if (initialIds && initialIds.length) {
        // a remembered job must not be lost to a status reload before the first poll answers
        window.backgroundJobRunning = true;
        holding = true;
    }

    function esc(text) {
        return String(text === null || text === undefined ? "" : text)
            .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }

    function bar(job) {
        if (!job.progress_total) { return ""; }
        var pct = Math.floor(100 * job.progress_done / job.progress_total);
        // libvirt takes a while to finish the last percent: a full moving bar, not a stuck number
        var finishing = job.state === "running" && pct >= 99;
        return '<div class="progress mt-2" role="progressbar" aria-valuenow="' + (finishing ? 100 : pct)
            + '" aria-valuemin="0" aria-valuemax="100"><div class="progress-bar'
            + (finishing ? " progress-bar-striped progress-bar-animated" : "") + '" style="width:'
            + (finishing ? 100 : pct) + '%">' + (finishing ? "Finishing\u2026" : pct + "%") + "</div></div>";
    }

    // label, state badge and muted phase on one line, the buttons on its right
    function header(label, state, phase, buttons) {
        return '<div class="d-flex flex-wrap align-items-center gap-2"><strong>' + esc(label) + "</strong>"
            + '<span class="badge bg-' + JOB_STATE_COLORS[state]
            // the theme draws white text on a warning badge
            + (JOB_STATE_COLORS[state] === "warning" ? " text-dark" : "") + '">' + esc(state) + "</span>"
            + (phase ? '<span class="small text-body-secondary">' + esc(phase) + "</span>" : "")
            + (buttons ? '<div class="ms-auto d-flex gap-2">' + buttons + "</div>" : "") + "</div>";
    }

    function alertHtml(state, body) {
        return '<div class="alert alert-' + JOB_STATE_COLORS[state] + ' mb-3" role="status">' + body + "</div>";
    }

    function errorHtml(job) {
        return job.error ? '<div class="small mt-2">' + esc(job.error) + "</div>" : "";
    }

    function jobHtml(job) {
        var cancel = job.cancellable ? '<button type="button" class="btn btn-sm btn-outline-danger" data-cancel="'
            + esc(job.id) + '"' + (cancelling[job.id] ? " disabled" : "") + ">Cancel</button>" : "";
        // an uncertain job keeps its claims, so it stays in the list with its error
        return alertHtml(job.state, header(job.label, job.state, job.phase, cancel) + errorHtml(job) + bar(job));
    }

    function outcomeHtml(job) {
        var left = (job.result && job.result.left_behind) || [];
        var note = job.result && job.result.warning ? '<div class="small mt-2">' + esc(job.result.warning) + "</div>" : "";
        var warn = note + (left.length ? '<div class="small mt-2">Files not removed:</div><ul class="list-unstyled small mb-0">'
            + left.map(function (path) { return '<li class="text-break"><code>' + esc(path) + "</code></li>"; }).join("") + "</ul>" : "");
        var buttons = '<button type="button" class="btn btn-sm btn-primary" data-refresh="1">Refresh</button>'
            + '<button type="button" class="btn btn-sm btn-outline-secondary" data-dismiss="' + esc(job.id)
            + '">Dismiss</button>';
        return alertHtml(job.state, header(job.label, job.state, "", buttons) + errorHtml(job) + warn);
    }

    function render() {
        var html = notice ? alertHtml("failed", '<div class="d-flex flex-wrap align-items-center gap-2"><span>'
            + esc(notice) + '</span><div class="ms-auto"><button type="button" class="btn btn-sm btn-outline-secondary"'
            + ' data-dismiss-error="1">Dismiss</button></div></div>') : "";
        last.jobs.forEach(function (job) { html += jobHtml(job); });
        Object.keys(outcomes).forEach(function (id) { html += outcomeHtml(outcomes[id]); });
        last.others.forEach(function (o) {
            html += '<div class="alert alert-secondary mb-3" role="status">' + header(o.label, o.state, "", "") + "</div>";
        });
        if (last.short_operation) {
            html += '<div class="alert alert-secondary mb-3" role="status">A short operation is in progress.</div>';
        }
        // a job the worker has to start, run or stop, not one a request runs (the Jobs page uses the same rule)
        var waiting = last.jobs.some(function (j) {
            return ["queued", "running", "cancelling"].indexOf(j.state) >= 0 && !j.in_request;
        });
        var seen = last.worker_last_seen ? new Date(last.worker_last_seen) : null;
        if (waiting && (!seen || Date.now() - seen.getTime() > 60000)) {
            html += '<div class="alert alert-warning mb-3" role="status">Worker unavailable, last seen '
                + esc(seen ? seen.toLocaleString() : "never") + ".</div>";
        }
        if (html !== rendered) {
            element.innerHTML = html;
            rendered = html;
        }
        var busy = html !== "" || Object.keys(pending).length > 0;
        if (busy) {
            window.backgroundJobRunning = true;
        } else if (holding) {
            window.backgroundJobRunning = false;
        }
        holding = busy;
    }

    // a job that did what it was asked, with nothing more to read: the page shows its effect
    function quiet(job) {
        var result = job.result || {};
        return job.state === "succeeded" && !result.warning && !(result.left_behind || []).length;
    }

    function fetchOutcome(id) {
        if (inflight[id]) { return; }
        inflight[id] = true;
        $.getJSON(urls.job(id))
            .done(function (job) {
                if (dismissed[id]) { delete pending[id]; return; }
                // still active: pending until a list shows it (one older than the job may not) or it
                // ends; the next poll asks for it again
                if (["queued", "running", "cancelling"].indexOf(job.state) >= 0) { return; }
                delete pending[id];
                // only when no other job runs, is shown or awaited: a reload would lose its outcome
                var others = Object.keys(outcomes).length + Object.keys(pending).length + Object.keys(shown).length;
                // the page in use (poll.js): its outcome waits in the panel, with Refresh
                if (quiet(job) && !pageInUse() && !others) {
                    window.location.reload(); // the job is not remembered again: no loop
                    return;
                }
                outcomes[id] = job;
                render();
            })
            .fail(function (xhr) {
                // not allowed or gone: asking again cannot help; a network error or 5xx can pass
                if (xhr.status === 403 || xhr.status === 404) {
                    delete pending[id];
                    render();
                }
            })
            .always(function () { delete inflight[id]; });
    }

    function onData(data) {
        var now = {};
        data.jobs.forEach(function (job) { now[job.id] = job; });
        Object.keys(shown).forEach(function (id) { if (!now[id]) { pending[id] = true; } });
        Object.keys(now).forEach(function (id) { delete pending[id]; });
        shown = now;
        last = data;
        Object.keys(pending).forEach(fetchOutcome);
        render();
    }

    element.addEventListener("click", function (ev) {
        var t = ev.target;
        if (t.dataset.refresh) { window.location.reload(); }
        if (t.dataset.dismiss) { dismissed[t.dataset.dismiss] = true; delete outcomes[t.dataset.dismiss]; render(); }
        if (t.dataset.dismissError) { notice = ""; render(); }
        if (t.dataset.cancel && !cancelling[t.dataset.cancel]) { cancel(t.dataset.cancel); }
    });

    function cancel(id) {
        cancelling[id] = true;
        notice = "";
        render();
        $.ajax({ url: urls.cancel(id), type: "POST", headers: { "X-CSRFToken": csrfToken } })
            .fail(function (xhr) {
                // e.g. a queued job started meanwhile and cannot be stopped any more
                notice = (xhr.responseJSON && xhr.responseJSON.detail)
                    || (xhr.status ? "Cancel failed (HTTP " + xhr.status + ")." : "Cancel failed: the server could not be reached.");
            })
            .always(function () {
                delete cancelling[id];
                render();
                poller.stop(); // ask for the list now
                poller.start();
            });
    }

    var poller = pollWhileVisible(3000, function () { return $.getJSON(urls.resource); }, onData, 0);
    // follow a job the page just started, as a remembered one
    poller.track = function (id) {
        pending[id] = true;
        render();
        poller.stop(); // ask for the list now
        poller.start();
    };
    return poller;
}
