// The search box of a list page, and the instance list's state list.
//
// A row shows when its text contains the search, in any case: plain text,
// not a pattern. A row with data-search is searched in that text only, not
// in its buttons and menus. With a state list, the row's [data-state] must
// be the chosen state too. In a grouped list a search for a group's host
// shows all of its rows, and its header row (data-group-header) shows while
// any of its rows does. A page's #no-match shows while no row does. The
// search is remembered for a day, per page.
function filterTable(doc) {
    var text = doc.getElementById("filter").value.toLowerCase();
    var states = doc.getElementById("state-filter");
    var state = states ? states.value : "";
    var anyShown = false;
    doc.querySelectorAll(".searchable").forEach(function (group) {
        var host = group.dataset.host;
        var hostMatches = host !== undefined && host.toLowerCase().includes(text);
        var header = null, shown = false;
        group.querySelectorAll("tr").forEach(function (row) {
            if (row.hasAttribute("data-group-header")) {
                header = row;
                return;
            }
            var mark = row.querySelector("[data-state]");
            var searched = row.dataset.search !== undefined ? row.dataset.search : row.textContent;
            row.hidden = !((!state || (mark && mark.dataset.state === state)) &&
                (hostMatches || searched.toLowerCase().includes(text)));
            shown = shown || !row.hidden;
        });
        if (header) {
            header.hidden = !shown;
        }
        anyShown = anyShown || shown;
    });
    var noMatch = doc.getElementById("no-match");
    if (noMatch) {
        noMatch.hidden = anyShown;
    }
}

if (typeof module !== "undefined") {
    module.exports = {filterTable: filterTable};
} else {
    var search = document.getElementById("filter");
    var states = document.getElementById("state-filter");
    search.value = Cookies.get(document.title + "_filter") || "";
    search.addEventListener("input", function () {
        Cookies.set(document.title + "_filter", search.value, {expires: 1});
        filterTable(document);
    });
    if (states) {
        states.addEventListener("change", function () {
            filterTable(document);
        });
    }
    var clear = document.getElementById("clear-filters");
    if (clear) {
        clear.addEventListener("click", function () {
            search.value = "";
            Cookies.remove(document.title + "_filter");
            if (states) {
                states.value = "";
            }
            filterTable(document);
        });
    }
    filterTable(document);
}
