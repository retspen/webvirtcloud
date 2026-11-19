// The search box of a list page, and the instance list's state list.
//
// A row (a table row, or another element with data-search, such as a card)
// shows when its text contains the search, in any case: plain text, not a
// pattern. A row with data-search is searched in that text only, not in its
// buttons and menus. With a state list, the row's [data-state] must
// be the chosen state too; with tag pills (#tag-pills, #tag-filter), the chosen tag
// one of the row's data-tags (names split by spaces), or "-" none of them.
// A tag's badge ([data-tag-filter]) chooses its pill; a row's "…"
// ([data-show-tags]) shows its other tags. In a grouped list a search for a group's host
// shows all of its rows, and its header row (data-group-header) shows while
// any of its rows does. A page's #no-match shows while no row does. The
// search is remembered for a day, per page, unless its box has data-forget.
//
// The instance list's state pills (#state-pills) set the state; each one's
// [data-count-state] counts the VMs of its state the search finds (its
// state left aside, the tag not), "" all of them; a state's pill with none is hidden
// unless chosen; the chosen state and tag are remembered as the search is, so that a
// list the poll reloads keeps it. #filter-status tells screen readers how
// many VMs match, collapsed hosts' VMs too.

// text as it is compared: without case and accents, whatever the browser's
// language ("İSTANBUL", "istanbul" and "Istanbul" are one; so are "ş" and "s")
function fold(text) {
    return text.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/ı/g, "i");
}

function filterTable(doc) {
    var text = fold(doc.getElementById("filter").value);
    var states = doc.getElementById("state-filter");
    var state = states ? states.value : "";
    var tags = doc.getElementById("tag-filter");
    var tag = tags ? tags.value : "";
    var anyShown = false;
    var counts = {"": 0}, vms = 0, shownVms = 0;
    doc.querySelectorAll(".searchable").forEach(function (group) {
        var host = group.dataset.host;
        var hostMatches = host !== undefined && fold(host).includes(text);
        var header = null, shown = false;
        group.querySelectorAll("tr, [data-search], [data-group-header]").forEach(function (row) {
            if (row.hasAttribute("data-group-header")) {
                header = row;
                return;
            }
            var mark = row.querySelector("[data-state]");
            var searched = row.dataset.search !== undefined ? row.dataset.search : row.textContent;
            var rowTags = row.dataset.tags || "";
            var tagged = !tag || (tag === "-" ? rowTags === "" : rowTags.split(" ").indexOf(tag) >= 0);
            var found = (hostMatches || fold(searched).includes(text)) && tagged;
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
    module.exports = {filterTable: filterTable, fold: fold};
} else {
    var search = document.getElementById("filter");
    var states = document.getElementById("state-filter");
    // a list's search is kept for this tab, in the browser only; a form's
    // search ([data-forget], the group form's members) starts empty
    var remember = !search.hasAttribute("data-forget");
    var key = document.title + "_filter";
    function keep(value, which) {
        try {
            if (value) {
                sessionStorage.setItem(which || key, value);
            } else {
                sessionStorage.removeItem(which || key);
            }
        } catch (e) {
            // storage turned off: the search is not kept
        }
    }
    try {
        search.value = remember && sessionStorage.getItem(key) || "";
    } catch (e) {
        search.value = "";
    }
    search.addEventListener("input", function () {
        if (remember) {
            keep(search.value);
        }
        filterTable(document);
    });
    if (states) {
        states.addEventListener("change", function () {
            filterTable(document);
        });
    }
    // a row of pills (data-pill="value"): the one pressed sets its filter (a hidden
    // input) and is remembered under which, as the search is; the value kept is chosen
    // again, or forgotten when no pill has it any longer (a tag made again later is
    // not chosen by itself). Gives the function that chooses a value's pill.
    function pillRow(pills, input, which) {
        var all = pills.querySelectorAll("[data-pill]");
        function choose(pill) {
            input.value = pill.dataset.pill;
            keep(input.value, which);
            all.forEach(function (other) {
                other.classList.toggle("active", other === pill);
                other.setAttribute("aria-pressed", other === pill);
            });
            filterTable(document);
        }
        function chooseValue(value) {
            var pill = Array.prototype.find.call(all, function (one) { return one.dataset.pill === value; });
            if (pill) {
                choose(pill);
            }
            return pill;
        }
        pills.addEventListener("click", function (event) {
            var pill = event.target.closest("[data-pill]");
            if (pill) {
                choose(pill);
            }
        });
        var kept = "";
        try {
            kept = sessionStorage.getItem(which) || "";
        } catch (e) {
            // storage turned off: all
        }
        if (kept && !chooseValue(kept)) {
            keep("", which);
        }
        return chooseValue;
    }
    var statePills = document.getElementById("state-pills");
    var chooseState = statePills && pillRow(statePills, states, key + "_state");
    var tagPills = document.getElementById("tag-pills");
    var chooseTag = tagPills && pillRow(tagPills, document.getElementById("tag-filter"), key + "_tag");
    if (!tagPills) {
        keep("", key + "_tag");  // no row has a tag: none is kept to come back later
    }
    document.addEventListener("click", function (event) {
        var more = event.target.closest("[data-show-tags]");
        if (more) {
            var others = more.nextElementSibling;
            more.hidden = true;
            others.hidden = false;
            // the focus is not lost with the button: the first tag shown takes it, or the tags if they are not buttons
            (others.querySelector("button") || others).focus();
            return;
        }
        var badge = event.target.closest("[data-tag-filter]");
        if (badge && chooseTag) {
            chooseTag(badge.dataset.tagFilter);
        }
    });
    var clear = document.getElementById("clear-filters");
    if (clear) {
        clear.addEventListener("click", function () {
            search.value = "";
            keep("");
            if (chooseTag) {
                chooseTag("");
            }
            if (chooseState) {
                chooseState("");
            } else if (states) {
                states.value = "";
            }
            filterTable(document);
        });
    }
    filterTable(document);
}
