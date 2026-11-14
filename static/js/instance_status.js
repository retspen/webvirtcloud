// The VM page reloads when the VM's state changes (instance.html, #vm-summary),
// or when the VM is gone: the page then says so.
backgroundJobRunning = false;
// not "status": that is window.status, which the browser may not keep
var vm_summary = document.getElementById("vm-summary");
var vm_status = Number(vm_summary.dataset.status);
var host_lost = document.getElementById("vm-host-lost");

function reloadWhenFree() {
    // the page in use (a dialog open, a field in use, an XML edit not saved): the reload waits (poll.js)
    if (!backgroundJobRunning && !pageInUse()) {
        window.location.reload();
    }
}

var status_poll = pollWhileVisible(5000, function () {
    return $.getJSON(vm_summary.dataset.statusUrl).fail(function (xhr) {
        // a failed read (a host that does not answer, a session that ended, the VM gone while
        // the page is in use) leaves the page as it was: it says so until a read is answered
        host_lost.hidden = false;
        if (xhr.status == 404) {
            reloadWhenFree();
        }
    });
}, function get_status(data) {
    host_lost.hidden = true;
    if (data['status'] != vm_status) {
        reloadWhenFree();
    }
});
