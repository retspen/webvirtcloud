// The search box of a list page, and the instance list's state list.
//
// A row (a table row, or another element with data-search, such as a card)
// shows when its text contains the search, in any case: plain text, not a
// pattern. A row with data-search is searched in that text only, not in its
// buttons and menus. With a state list, the row's [data-state] must
// be the chosen state too; with a tag list (#tag-filter), the chosen tag
// one of the row's data-tags (names split by spaces), or "-" none of them.
// A tag's badge ([data-tag-filter]) chooses it in the list; a row's "…"
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
    var tags = document.getElementById("tag-filter");
    if (tags) {
        try {
            var keptTag = sessionStorage.getItem(key + "_tag") || "";
            // a tag no row has any longer is forgotten: made again later, it is not chosen by itself
            if (Array.prototype.some.call(tags.options, function (option) { return option.value === keptTag; })) {
                tags.value = keptTag;
            } else {
                keep("", key + "_tag");
            }
        } catch (e) {
            // storage turned off: all tags
        }
        tags.addEventListener("change", function () {
            keep(tags.value, key + "_tag");
            filterTable(document);
        });
    } else {
        keep("", key + "_tag");  // no row has a tag: none is kept to come back later
    }
    document.addEventListener("click", function (event) {
        var more = event.target.closest("[data-show-tags]");
        if (more) {
            more.hidden = true;
            more.nextElementSibling.hidden = false;
            // the focus is not lost with the button: the first tag shown takes it
            more.nextElementSibling.querySelector("button, [tabindex]")?.focus();
            return;
        }
        var badge = event.target.closest("[data-tag-filter]");
        if (badge && tags) {
            tags.value = badge.dataset.tagFilter;
            keep(tags.value, key + "_tag");
            filterTable(document);
        }
    });
    var pills = document.getElementById("state-pills");
    function chooseState(pill) {
        states.value = pill.dataset.pillState;
        keep(states.value, key + "_state");
        pills.querySelectorAll("[data-pill-state]").forEach(function (other) {
            other.classList.toggle("active", other === pill);
            other.setAttribute("aria-pressed", other === pill);
        });
        filterTable(document);
    }
    if (pills) {
        var kept = "";
        try {
            kept = sessionStorage.getItem(key + "_state") || "";
        } catch (e) {
            // storage turned off: all states
        }
        var keptPill = kept && Array.prototype.find.call(pills.querySelectorAll("[data-pill-state]"), function (pill) {
            return pill.dataset.pillState === kept;
        });
        if (keptPill) {
            chooseState(keptPill);
        }
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
            keep("");
            if (tags) {
                tags.value = "";
                keep("", key + "_tag");
            }
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
