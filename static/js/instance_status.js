// The VM page reloads when the VM's state changes (instance.html, #vm-summary).
backgroundJobRunning = false;
// not "status": that is window.status, which the browser may not keep
var vm_summary = document.getElementById("vm-summary");
var vm_status = Number(vm_summary.dataset.status);
var host_lost = document.getElementById("vm-host-lost");
var status_poll = pollWhileVisible(5000, function () {
    // a failed read (a host that does not answer, a session that ended) leaves the
    // page as it was: it says so until a read is answered
    return $.getJSON(vm_summary.dataset.statusUrl).fail(function () { host_lost.hidden = false; });
}, function get_status(data) {
    host_lost.hidden = true;
    // the page in use (a dialog open, a field in use, an XML edit not saved): the reload waits (poll.js)
    if (data['status'] != vm_status && !backgroundJobRunning && !pageInUse()) {
        window.location.reload();
    }
});
