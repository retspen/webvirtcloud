// A VM list follows libvirt: it polls the states of its VMs (instances:states)
// at once, then every 5 s, as the VM page, and reloads when an answer differs
// from the states the page was rendered with, then from the answer before: a
// VM started or stopped, made, removed or renamed outside the page included.
// The page in use or the job panel showing something: it waits for the next
// answer. poll.js gives the polling.
function vmStatesKey(states) {
    return Object.keys(states).sort().map(function (id) {
        var host = states[id];
        return id + ":" + (host.ok ? Object.keys(host.vms).sort().map(function (uuid) {
            return uuid + "=" + host.vms[uuid].join("/");
        }).join(",") : "unreadable");
    }).join(";");
}

function followVmStates(url, rendered) {
    var last = vmStatesKey(rendered);
    return pollWhileVisible(5000, function () { return $.getJSON(url); }, function (data) {
        var key = vmStatesKey(data.computes);
        if (key !== last) {
            if (!pageInUse() && !window.backgroundJobRunning) {
                window.location.reload();
            }
            return; // in use: the change stays against the answer before
        }
        last = key;
    }, 0);
}
