// The VM page's Stats tab (stats_tab.html): its charts are polled while the
// tab is shown and made once; superusers' Logs view loads its rows each time
// it is shown.
(function () {
    var pane = document.getElementById("graphics");
    var stats_tab = document.querySelector('#graphics-tab');
    var stats_poll = null;
    // the seconds each CPU point averages
    var cpuWindows = [];
    // the usage sample of the previous answer: the next one averages since then
    var statsSample = null;
    // a reading for the line above a chart: one decimal, a dash where it is missing
    function reading(value) {
        return value == null ? "–" : String(Math.round(value * 10) / 10);
    }
    stats_tab.addEventListener('hidden.bs.tab', function () {
        stats_poll.stop();
    });
    stats_tab.addEventListener('shown.bs.tab', function () {
        if (stats_poll !== null) {
            stats_poll.start();
            return;
        }
        var cpuChart = lineChart(document.getElementById("cpuChart"), "%", ["Usage"], {
            max: 100,
            tooltip: function (context, text) {
                var span = cpuWindows[context.dataIndex];
                return span ? text + ' (' + pane.dataset.averageOver + ' ' + span + ' s)' : text;
            },
        });
        var memChart = lineChart(document.getElementById("memChart"), "MiB", ["Usage (RSS)"]);
        var diskChart = {};
        pane.querySelectorAll("canvas[data-disk]").forEach(function (canvas) {
            diskChart[canvas.dataset.disk] = lineChart(canvas, "MB/s", ["Read", "Write"]);
        });
        // two NICs with one MAC (a misconfiguration) share the first one's chart
        var netChart = {};
        pane.querySelectorAll("canvas[data-mac]").forEach(function (canvas) {
            var mac = canvas.dataset.mac;
            netChart[mac] = netChart[mac] || lineChart(canvas, "Mbit/s", ["Inbound", "Outbound"]);
        });

        // the first point at once, then every 5 s like the host graph
        stats_poll = pollWhileVisible(5000, function () {
            return $.getJSON(pane.dataset.url, statsSample ? {sample: statsSample} : {})
                .fail(function () {
                    statsSample = null;
                });
        }, function graph_usage(data) {
            statsSample = data.sample || null;
            cpuWindows.push(data.window);
            if (cpuWindows.length > CHART_POINTS) {
                cpuWindows.shift();
            }
            addPoint(cpuChart, data.timeline, [data.cpudata]);
            document.getElementById("cpuNow").textContent = reading(data.cpudata) + " %";
            // a VM whose memory could not be read gives total 0: a gap, same axis;
            // the RSS may pass the balloon size: then the axis grows to it
            if (data.memdata.total) {
                var used = Math.round(data.memdata.used / 1024), total = Math.round(data.memdata.total / 1024);
                memChart.options.scales.y.max = Math.max(total, used);
                addPoint(memChart, data.timeline, [used]);
                document.getElementById("memNow").textContent = used + " / " + total + " MiB";
            } else {
                addPoint(memChart, data.timeline, [null]);
                document.getElementById("memNow").textContent = "";
            }
            // a disk or NIC added after the page loaded has no chart until a reload,
            // and one removed keeps its last points
            function push(chart, id, labels, unit, values) {
                if (chart) {
                    addPoint(chart, data.timeline, values);
                    document.getElementById(id).textContent =
                        labels[0] + " " + reading(values[0]) + " · " + labels[1] + " " + reading(values[1]) + " " + unit;
                }
            }
            data.blkdata.forEach(function (disk) {
                push(diskChart[disk.dev], "blk" + disk.dev + "Now", [pane.dataset.read, pane.dataset.write], "MB/s", disk.data);
            });
            data.netdata.forEach(function (nic) {
                push(netChart[nic.mac], "net" + nic.mac + "Now", [pane.dataset.in, pane.dataset.out], "Mbit/s", nic.data);
            });
        }, 0);
    });

    // a click or the arrow keys: the rows of the moment each time Logs is shown
    var logsTab = document.getElementById("logs-tab");
    if (!logsTab) return;
    var table = document.getElementById("logs_table");
    logsTab.addEventListener("shown.bs.tab", function () {
        var tbody = $(table).children("tbody");
        function note(text) {
            tbody.empty().append($("<tr>").append($("<td colspan='4' class='text-body-secondary'>").text(text)));
        }
        $.getJSON(table.dataset.url, function (data) {
            if (!data.length) {
                note(table.dataset.empty);
                return;
            }
            // Log messages contain user-entered names (snapshots, disks, clones);
            // insert them as text, never as HTML.
            tbody.empty();
            $.each(data, function (id, row) {
                $("<tr>")
                    .append($("<td>").addClass("text-nowrap").text(row['date']))
                    .append($("<td>").text(row['user']))
                    .append($("<td>").text(row['message']))
                    .append($("<td>").text(row['result']))
                    .appendTo(tbody);
            });
        }).fail(function () {
            note(table.dataset.failed);
        });
    });
})();
