// The instance list's search box and state list.
//
// A VM row shows when its text contains the search, in any case, and the VM is
// in the chosen state. In the grouped list a search for a host's name shows
// all of its VMs, and the host's row shows while any of its VMs does.
function filterInstances(doc) {
    var text = doc.getElementById("filter").value.toLowerCase();
    var state = doc.getElementById("state-filter").value;
    doc.querySelectorAll(".searchable").forEach(function (group) {
        var host = group.dataset.host;
        var hostMatches = host !== undefined && host.toLowerCase().includes(text);
        var header = null, shown = false;
        group.querySelectorAll("tr").forEach(function (row) {
            var mark = row.querySelector("[data-state]");
            if (!mark) {
                header = row;
                return;
            }
            row.hidden = !((!state || mark.dataset.state === state) &&
                (hostMatches || row.textContent.toLowerCase().includes(text)));
            shown = shown || !row.hidden;
        });
        if (header) {
            header.hidden = !shown;
        }
    });
}

if (typeof module !== "undefined") {
    module.exports = {filterInstances: filterInstances};
} else {
    // the search is remembered for a day, as on the other lists
    var search = document.getElementById("filter");
    search.value = Cookies.get(document.title + "_filter") || "";
    search.addEventListener("input", function () {
        Cookies.set(document.title + "_filter", search.value, {expires: 1});
        filterInstances(document);
    });
    document.getElementById("state-filter").addEventListener("change", function () {
        filterInstances(document);
    });
    filterInstances(document);
}
