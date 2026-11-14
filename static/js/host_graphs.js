// The host's CPU and memory charts (overview.html), polled every 5 s.
var state = document.getElementById("graph_state");
// the seconds each CPU point averages
var cpuWindows = [];
var cpuChart = lineChart(document.getElementById("cpuChart"), "%", [state.dataset.usage], {
    max: 100,
    tooltip: function (context, text) {
        var span = cpuWindows[context.dataIndex];
        return span ? text + ' (' + state.dataset.averageOver + ' ' + span + ' s)' : text;
    },
});
var memChart = lineChart(document.getElementById("memChart"), "GiB", [state.dataset.usage]);
var cpuNow = document.getElementById("cpu_now");
var memNow = document.getElementById("mem_now");
var lastUpdate = "–";

// bytes in GiB (1024³), one decimal
function gb(bytes) {
    return Math.round(bytes / 107374182.4) / 10;
}

// a failed reading leaves the charts as they were: say since when
function stale() {
    state.textContent = state.dataset.stale.replace("%(time)s", lastUpdate);
    state.classList.add("text-danger");
}

// the CPU sample of the previous answer: usage is taken since then
var cpuSample = null;
pollWhileVisible(5000, function () {
    // a host that keeps a reading waiting: the charts say they are not updated, and the next poll goes out
    return $.ajax({url: state.dataset.url, data: cpuSample ? {cpu_sample: cpuSample} : {}, dataType: "json",
                   timeout: 30000}).fail(stale);
}, function (data) {
    cpuSample = data.cpu_sample || null;
    cpuWindows.push(data.window);
    if (cpuWindows.length > CHART_POINTS) {
        cpuWindows.shift();
    }
    addPoint(cpuChart, data.timeline, [data.cpudata]);
    // a host that could not be read gives no values: a gap, same axis
    if (data.memdata.total) {
        memChart.options.scales.y.max = gb(data.memdata.total);
        addPoint(memChart, data.timeline, [gb(data.memdata.usage)]);
        memNow.textContent = gb(data.memdata.usage) + " / " + gb(data.memdata.total) + " GiB";
    } else {
        addPoint(memChart, data.timeline, [null]);
    }
    if (data.cpudata == null) {
        stale();
        return;
    }
    cpuNow.textContent = data.cpudata + " %";
    lastUpdate = data.timeline;
    state.textContent = state.dataset.updated.replace("%(time)s", data.timeline);
    state.classList.remove("text-danger");
}, 0);
