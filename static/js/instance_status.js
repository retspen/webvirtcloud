// The VM page reloads when the VM's state changes (instance.html, #vm-summary).
backgroundJobRunning = false;
// not "status": that is window.status, which the browser may not keep
var vm_summary = document.getElementById("vm-summary");
var vm_status = Number(vm_summary.dataset.status);
var status_poll = pollWhileVisible(5000, function () {
    return $.getJSON(vm_summary.dataset.statusUrl);
}, function get_status(data) {
    // the page in use (a dialog open, a field in use, an XML edit not saved): the reload waits (poll.js)
    if (data['status'] != vm_status && !backgroundJobRunning && !pageInUse()) {
        window.location.reload();
    }
});
