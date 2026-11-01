// Repeats request() while the page is visible and passes each answer to
// onData. request() returns a jQuery promise (e.g. $.getJSON(url)); onData is
// called after the poller's own bookkeeping, so an error in it does not stop
// the polling. One request at a time: the next one starts
// interval ms after the previous one has finished, so a slow host does not
// pile up requests, each holding a web worker. A hidden page asks nothing;
// when it is shown again it asks at once. stop() pauses, start() resumes
// at once (for example while a tab of the page is shown). The first request
// goes out after firstDelay ms, the interval if it is not given.
function pollWhileVisible(interval, request, onData, firstDelay) {
    var timer = null;
    var running = false;
    var stopped = false;

    function run() {
        timer = null;
        if (stopped || document.hidden) {
            return;
        }
        running = true;
        request()
            .always(function () {
                running = false;
                if (!stopped && !document.hidden) {
                    timer = setTimeout(run, interval);
                }
            })
            .done(onData);
    }

    function resume() {
        if (!stopped && !document.hidden && !running && timer === null) {
            run();
        }
    }

    document.addEventListener("visibilitychange", resume);
    timer = setTimeout(run, firstDelay === undefined ? interval : firstDelay);

    return {
        stop: function () {
            stopped = true;
            clearTimeout(timer);
            timer = null;
        },
        start: function () {
            stopped = false;
            resume();
        },
    };
}

// The user is in the page: a dialog open, a field in use or an XML edit not
// saved. A poll that would reload the page waits for its next answer.
function pageInUse() {
    var active = document.activeElement;
    return !!document.querySelector(".modal.show")
        || !!(active && active.matches && active.matches("input, select, textarea"))
        || !!(window.xmlEditUnsaved && window.xmlEditUnsaved());
}
