// The search box of a list page, and the instance list's state list.
//
// A row shows when its text contains the search, in any case: plain text,
// not a pattern. A row with data-search is searched in that text only, not
// in its buttons and menus. With a state list, the row's [data-state] must
// be the chosen state too. In a grouped list a search for a group's host
// shows all of its rows, and its header row (data-group-header) shows while
// any of its rows does. A page's #no-match shows while no row does. The
// search is remembered for a day, per page.
//
// The instance list's state pills (#state-pills) set the state; each one's
// [data-count-state] counts the VMs of its state the search finds (its
// state left aside), "" all of them; a state's pill with none is hidden
// unless chosen. #filter-status tells screen readers how many VMs match,
// collapsed hosts' VMs too.
function filterTable(doc) {
    var text = doc.getElementById("filter").value.toLowerCase();
    var states = doc.getElementById("state-filter");
    var state = states ? states.value : "";
    var anyShown = false;
    var counts = {"": 0}, vms = 0, shownVms = 0;
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
            var found = hostMatches || searched.toLowerCase().includes(text);
            row.hidden = !((!state || (mark && mark.dataset.state === state)) && found);
            shown = shown || !row.hidden;
            if (mark) {
                vms += 1;
                shownVms += row.hidden ? 0 : 1;
                if (found) {
                    counts[""] += 1;
                    counts[mark.dataset.state] = (counts[mark.dataset.state] || 0) + 1;
                }
            }
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
    doc.querySelectorAll("[data-count-state]").forEach(function (count) {
        var n = counts[count.dataset.countState] || 0;
        count.textContent = n;
        count.parentElement.hidden = n === 0 && count.dataset.countState !== "" && count.dataset.countState !== state;
    });
    var status = doc.getElementById("filter-status");
    if (status) {
        status.textContent = status.dataset.text.replace("%(shown)s", shownVms).replace("%(all)s", vms);
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
    var pills = document.getElementById("state-pills");
    function chooseState(pill) {
        states.value = pill.dataset.pillState;
        pills.querySelectorAll("[data-pill-state]").forEach(function (other) {
            other.classList.toggle("active", other === pill);
            other.setAttribute("aria-pressed", other === pill);
        });
        filterTable(document);
    }
    if (pills) {
        pills.addEventListener("click", function (event) {
            var pill = event.target.closest("[data-pill-state]");
            if (pill) {
                chooseState(pill);
            }
        });
    }
    var clear = document.getElementById("clear-filters");
    if (clear) {
        clear.addEventListener("click", function () {
            search.value = "";
            Cookies.remove(document.title + "_filter");
            if (pills) {
                chooseState(pills.querySelector('[data-pill-state=""]'));
            } else if (states) {
                states.value = "";
            }
            filterTable(document);
        });
    }
    filterTable(document);
}
