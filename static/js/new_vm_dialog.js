// The new-VM dialog's CPU bars and capacity lines, read when the
// dialog opens, two reads at a time: a CPU read holds a worker for
// a second, a capacity read while it reads the host's VMs. Answers
// of an earlier opening are ignored.
const addInstance = document.getElementById("AddInstance");
let opening = 0, queue = [], reading = 0;

function setCpuUsage(cell, percent, text) {
    const meter = cell.querySelector(".progress");
    cell.querySelector(".progress-bar").style.width = (percent || 0) + "%";
    if (percent === null) {
        meter.removeAttribute("aria-valuenow");
    } else {
        meter.setAttribute("aria-valuenow", percent);
    }
    cell.querySelector(".cpu-usage-value").textContent = text;
}

// data: the answer, or null when the read failed
function show(element, data) {
    if (element.classList.contains("compute-capacity")) {
        element.textContent = data === null ? "" : data.trim();
        return;
    }
    const usage = data !== null && typeof data.cpudata === "number" ? Math.round(data.cpudata) : null;
    setCpuUsage(element, usage, usage === null ? "—" : usage + "%");
}

function readNext() {
    while (reading < 2 && queue.length) {
        const element = queue.shift(), current = opening;
        reading++;
        $.get(element.dataset.url)
            .done((data) => { if (current === opening) show(element, data); })
            .fail(() => { if (current === opening) show(element, null); })
            .always(() => { reading--; readNext(); });
    }
}

addInstance.addEventListener("show.bs.modal", function () {
    opening++;
    addInstance.querySelectorAll(".cpu-usage").forEach((cell) => setCpuUsage(cell, null, "…"));
    // host by host, as the list shows them
    queue = Array.from(addInstance.querySelectorAll(".cpu-usage, .compute-capacity"));
    readNext();
});
addInstance.addEventListener("hide.bs.modal", function () {
    opening++;
    queue = [];
});
