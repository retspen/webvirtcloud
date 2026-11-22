// Live line charts of the host overview and the VM page (Chart.js 4): the
// last CHART_POINTS readings, a gap where a reading is missing, and the
// colours of the selected Bootstrap theme. A reading is placed at the time
// it came: one that took longer stands farther from the one before. Each
// is labelled with the time the panel gave it.
var CHART_POINTS = 10;
// the pixels a tick's label needs from the next one
var TICK_ROOM = 60;
// a reading as the page's language writes it (a decimal comma in Turkish), one decimal at most;
// no thousands separator, as the panel's own pages
var PAGE_LANGUAGE = document.documentElement.lang || undefined;
var formatNumber = new Intl.NumberFormat(PAGE_LANGUAGE, {maximumFractionDigits: 1, useGrouping: false}).format;

(function () {
    var style = getComputedStyle(document.body);
    Chart.defaults.color = style.getPropertyValue("--bs-body-color").trim();
    Chart.defaults.borderColor = style.getPropertyValue("--bs-border-color").trim();
    Chart.defaults.locale = PAGE_LANGUAGE;  // the tooltips' numbers
})();

// labels: one per line. options: max (the y axis top), tooltip(context, text)
// to add to a point's tooltip text.
function lineChart(canvas, unit, labels, options) {
    var style = getComputedStyle(document.body);
    var colours = ["--bs-primary-rgb", "--bs-info-rgb"].map(function (name) {
        return style.getPropertyValue(name).trim();
    });
    options = options || {};
    return new Chart(canvas, {
        type: "line",
        data: {
            labels: [],
            datasets: labels.map(function (label, i) {
                return {
                    label: label,
                    data: [],
                    borderColor: "rgb(" + colours[i] + ")",
                    backgroundColor: "rgba(" + colours[i] + ", 0.3)",
                    fill: true,
                    pointRadius: 2,
                };
            }),
        },
        options: {
            animation: false,
            maintainAspectRatio: false,
            scales: {
                x: {
                    type: "linear",
                    // a tick at each reading, named by its label
                    afterBuildTicks: function (axis) {
                        axis.ticks = axis.chart.data.datasets[0].data.map(function (point) { return {value: point.x}; });
                    },
                    // a reading's label, unless the next one stands too close for it to be read (a
                    // long step, after the page was hidden, leaves the others packed together)
                    ticks: {
                        maxRotation: 0,
                        autoSkip: false,
                        callback: function (value, index, ticks) {
                            var next = ticks[index + 1];
                            var room = next && this.getPixelForValue(next.value) - this.getPixelForValue(value);
                            return next && room < TICK_ROOM ? "" : labelAt(this.chart, value);
                        },
                    },
                },
                // the axis as Chart.js writes it (its precision, the page language), with the unit
                y: {min: 0, max: options.max, ticks: {callback: function () { return Chart.Ticks.formatters.numeric.apply(this, arguments) + " " + unit; }}},
            },
            plugins: {
                legend: {display: labels.length > 1},
                tooltip: {
                    callbacks: {
                        title: function (items) {
                            return items.length ? labelAt(items[0].chart, items[0].parsed.x) : "";
                        },
                        label: function (context) {
                            var text = context.dataset.label + ": " + context.formattedValue + " " + unit;
                            return options.tooltip ? options.tooltip(context, text) : text;
                        },
                    },
                },
            },
        },
    });
}

// the label of the reading at x (seconds) of chart: the panel's time of it
function labelAt(chart, x) {
    return (chart.timeLabels || {})[x] || "";
}

// values: one per line, null for a reading that is missing; at, the
// reading's time in seconds, now if not given
function addPoint(chart, label, values, at) {
    var x = at === undefined ? Date.now() / 1000 : at;
    chart.timeLabels = chart.timeLabels || {};  // a reading's x: its label
    chart.timeLabels[x] = label;
    chart.data.datasets.forEach(function (set, i) {
        set.data.push({x: x, y: values[i] == null ? null : values[i]});
    });
    if (chart.data.datasets[0].data.length > CHART_POINTS) {
        var gone = chart.data.datasets[0].data[0].x;
        chart.data.datasets.forEach(function (set) {
            set.data.shift();
        });
        // the label goes with its last reading: two may have come at one time
        if (!chart.data.datasets[0].data.some(function (point) { return point.x === gone; })) {
            delete chart.timeLabels[gone];
        }
    }
    chart.update();
}
