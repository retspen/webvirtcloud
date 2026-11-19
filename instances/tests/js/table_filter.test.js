// node table_filter.test.js path/to/static/js/table_filter.js
const assert = require("assert");
const {filterTable: filterInstances} = require(process.argv[2]);

// A minimal DOM: table bodies of rows; a VM row holds its state mark, a
// group's header row is marked as one.
function vm(text, state, search) {
    const mark = {dataset: {state}};
    return {textContent: text, dataset: search === undefined ? {} : {search}, hidden: false, hasAttribute: () => false,
            querySelector: (s) => (s === "[data-state]" ? mark : null)};
}
function hostRow(text) {
    return {textContent: text, dataset: {}, hidden: false, hasAttribute: (a) => a === "data-group-header", querySelector: () => null};
}
function plainRow(text) {
    return {textContent: text, dataset: {}, hidden: false, hasAttribute: () => false, querySelector: () => null};
}
function group(rows, host) {
    return {dataset: host ? {host} : {}, querySelectorAll: (s) => (s === "tr, [data-search], [data-group-header]" ? rows : [])};
}
function page(groups, text, state, noMatch, extra = {}) {
    // a list without a state list (state undefined) has no such element, nor one without tags a tag list
    const inputs = {filter: {value: text}, "state-filter": state === undefined ? undefined : {value: state},
                    "tag-filter": extra.tag === undefined ? undefined : {value: extra.tag},
                    "no-match": noMatch, "filter-status": extra.status};
    return {
        getElementById: (id) => inputs[id],
        querySelectorAll: (s) => (s === ".searchable" ? groups : s === "[data-count-state]" ? extra.counts || []
                                  : s === "[data-count-tag]" ? extra.tagCounts || [] : []),
    };
}
const visible = (rows) => rows.filter((r) => !r.hidden).map((r) => r.textContent);

// the flat list: search and state together
let rows = [vm("web-1 Active", "Active"), vm("inactive-db Off", "Off"), vm("Web-2 Off", "Off")];
filterInstances(page([group(rows)], "", ""));
assert.deepStrictEqual(visible(rows), ["web-1 Active", "inactive-db Off", "Web-2 Off"], "no filter shows all");
filterInstances(page([group(rows)], "WEB", ""));
assert.deepStrictEqual(visible(rows), ["web-1 Active", "Web-2 Off"], "search ignores case");
filterInstances(page([group(rows)], "", "Active"));
assert.deepStrictEqual(visible(rows), ["web-1 Active"], "state is the VM's, not a word in its name");
filterInstances(page([group(rows)], "web", "Off"));
assert.deepStrictEqual(visible(rows), ["Web-2 Off"], "both apply");
filterInstances(page([group(rows)], "web-1 (", ""));
assert.deepStrictEqual(visible(rows), [], "the search is text, not a pattern");

// the grouped list: a host row shows while any of its VMs does
const header1 = hostRow("host-a Connected"), a = [header1, vm("web-1 Active", "Active"), vm("db-1 Off", "Off")];
const header2 = hostRow("host-b Connected"), b = [header2, vm("web-9 Off", "Off")];
const groups = [group(a, "host-a"), group(b, "host-b")];
filterInstances(page(groups, "db", ""));
assert.deepStrictEqual(visible(a), ["host-a Connected", "db-1 Off"]);
assert.deepStrictEqual(visible(b), [], "a host without a match is hidden");
filterInstances(page(groups, "HOST-B", ""));
assert.deepStrictEqual(visible(b), ["host-b Connected", "web-9 Off"], "a host's name shows all its VMs");
assert.deepStrictEqual(visible(a), []);
filterInstances(page(groups, "host-a", "Off"));
assert.deepStrictEqual(visible(a), ["host-a Connected", "db-1 Off"], "the state applies to a host's VMs too");
filterInstances(page(groups, "Connected", ""));
assert.deepStrictEqual(visible(a), [], "a host row's other text is not its name");

// the interfaces list: a type's heading shows while any of its cards does
const bridges = [hostRow("Bridges 2"), vm("x", undefined, "br-v101"), vm("x", undefined, "br-v102")];
const vlans = [hostRow("VLANs 1"), vm("x", undefined, "bond1.101")];
filterInstances(page([group(bridges), group(vlans)], "v102"));
assert.deepStrictEqual(bridges.map((r) => r.hidden), [false, true, false], "a card is found by its data-search");
assert.deepStrictEqual(vlans.map((r) => r.hidden), [true, true], "a type without a match is hidden, its heading too");

// any other list: no state list, no groups; its rows are filtered by their text
const plain = [plainRow("alice Active"), plainRow("bob (vda) Blocked"), plainRow("carol Active")];
filterInstances(page([group(plain)], "ACTIVE"));
assert.deepStrictEqual(visible(plain), ["alice Active", "carol Active"], "a plain list is searched");
filterInstances(page([group(plain)], "(vda"));
assert.deepStrictEqual(visible(plain), ["bob (vda) Blocked"], "a bracket is text there too");
filterInstances(page([group(plain)], ""));
assert.deepStrictEqual(visible(plain), ["alice Active", "bob (vda) Blocked", "carol Active"]);

// a row with data-search is searched there only: its menus' words are not the VM's
const menus = [vm("web-1 Active Force off Power cycle", "Active", "web-1 alice"), vm("db-1 Off Start", "Off", "db-1 bob")];
filterInstances(page([group(menus)], "off", ""));
assert.deepStrictEqual(visible(menus), [], "a menu's 'Force off' is not a match");
filterInstances(page([group(menus)], "BOB", ""));
assert.deepStrictEqual(visible(menus), ["db-1 Off Start"], "an owner is searched");

// the page says so when nothing matches, and not otherwise
const noMatch = {hidden: true};
filterInstances(page([group(menus)], "nothing-like-this", "", noMatch));
assert.strictEqual(noMatch.hidden, false, "no row: the message shows");
filterInstances(page([group(menus)], "web", "", noMatch));
assert.strictEqual(noMatch.hidden, true, "a row: the message goes");

// the state pills count the VMs the search finds, each state's and all; a
// state without any is hidden unless chosen; the status says how many show
const count = (state) => ({dataset: {countState: state}, textContent: "", parentElement: {hidden: false}});
const counts = [count(""), count("Active"), count("Off"), count("Crashed")];
const status = {dataset: {text: "%(shown)s of %(all)s VMs match"}, textContent: ""};
const fleet = [vm("web-1", "Active", "web-1"), vm("web-2", "Off", "web-2"), vm("db-1", "Active", "db-1")];
filterInstances(page([group(fleet)], "web", "Off", undefined, {counts, status}));
assert.deepStrictEqual(counts.map((c) => c.textContent), [2, 1, 1, 0], "counts follow the search, not the state");
assert.deepStrictEqual(counts.map((c) => c.parentElement.hidden), [false, false, false, true]);
assert.strictEqual(status.textContent, "1 of 3 VMs match");
filterInstances(page([group(fleet)], "", "Crashed", undefined, {counts, status}));
assert.strictEqual(counts[3].parentElement.hidden, false, "the chosen state stays, even empty");
filterInstances(page([group(fleet)], "no-such-vm", "Active", undefined, {counts, status}));
assert.strictEqual(counts[0].parentElement.hidden, false, "All stays when nothing is found");

// the tag list: a row shows with the chosen tag among its own (data-tags), a whole name
const withTags = (row, tags) => Object.assign(row, {dataset: Object.assign(row.dataset, {tags})});
const tagged = [withTags(vm("web-1", "Active", "web-1"), "prod web"), withTags(vm("db-1", "Off", "db-1"), "prod"),
                withTags(vm("web-2", "Active", "web-2"), "")];
filterInstances(page([group(tagged)], "", "", undefined, {tag: "prod"}));
assert.deepStrictEqual(visible(tagged), ["web-1", "db-1"]);
filterInstances(page([group(tagged)], "web", "", undefined, {tag: "prod"}));
assert.deepStrictEqual(visible(tagged), ["web-1"], "the search and the tag both apply");
filterInstances(page([group(tagged)], "", "", undefined, {tag: "pro"}));
assert.deepStrictEqual(visible(tagged), [], "a tag is a whole name");
filterInstances(page([group(tagged)], "", "", undefined, {tag: ""}));
assert.deepStrictEqual(visible(tagged), ["web-1", "db-1", "web-2"], "no tag chosen: all");
filterInstances(page([group(tagged)], "", "", undefined, {tag: "-"}));
assert.deepStrictEqual(visible(tagged), ["web-2"], "-: the rows without a tag");
const tagCounts = [count(""), count("Active"), count("Off")];
filterInstances(page([group(tagged)], "", "Active", undefined, {tag: "prod", counts: tagCounts}));
assert.deepStrictEqual(tagCounts.map((c) => c.textContent), [2, 1, 1], "the state counts follow the tag");
// the tag pills count as the state pills: the rows the search and the state find, the tag aside; one with none hides
const countTag = (name) => ({dataset: {countTag: name}, textContent: "", parentElement: {hidden: false}});
const tagPillCounts = [countTag("-"), countTag("prod"), countTag("web")];
filterInstances(page([group(tagged)], "", "Off", undefined, {tag: "web", tagCounts: tagPillCounts}));
assert.deepStrictEqual(tagPillCounts.map((c) => c.textContent), [0, 1, 0]);
assert.deepStrictEqual(tagPillCounts.map((c) => c.parentElement.hidden), [true, false, false], "the chosen tag stays");
filterInstances(page([group(tagged)], "web", "", undefined, {tag: "", tagCounts: tagPillCounts}));
assert.deepStrictEqual(tagPillCounts.map((c) => c.textContent), [1, 1, 1], "and follow the search");
// a tag named as an object's own property ("constructor") is counted as any other
const objectNamed = [withTags(vm("app-1", "Active", "app-1"), "constructor")];
const constructorCount = [countTag("constructor")];
filterInstances(page([group(objectNamed)], "", "", undefined, {tag: "", tagCounts: constructorCount}));
assert.strictEqual(constructorCount[0].textContent, 1);
filterInstances(page([group(objectNamed)], "nothing", "", undefined, {tag: "", tagCounts: constructorCount}));
assert.deepStrictEqual([constructorCount[0].textContent, constructorCount[0].parentElement.hidden], [0, true]);
const hostVms = [hostRow("host-a"), withTags(vm("web-1", "Active", "web-1"), "prod"), withTags(vm("db-1", "Active", "db-1"), "")];
filterInstances(page([group(hostVms, "host-a")], "host-a", "", undefined, {tag: "prod"}));
assert.deepStrictEqual(visible(hostVms), ["host-a", "web-1"], "a host's name and a tag: its VMs with the tag");

// a search is without case and accents in any language: "istanbul" finds "İSTANBUL"
const turkish = [vm("İSTANBUL-1", "Active"), vm("ankara", "Active"), vm("Şişli", "Off")];
filterInstances(page([group(turkish)], "istanbul", ""));
assert.deepStrictEqual(visible(turkish), ["İSTANBUL-1"]);
filterInstances(page([group(turkish)], "sisli", ""));
assert.deepStrictEqual(visible(turkish), ["Şişli"]);

// the pills: the chosen state and tag are remembered as the search is, so a list the poll reloads keeps them
const vmModule = require("vm");
const fs = require("fs");
const pill = (value) => ({dataset: {pill: value}, classList: {toggle() {}}, setAttribute() {}});
function pillRow(values) {
    const row = {pills: values.map(pill), querySelectorAll: () => row.pills,
                 addEventListener: (name, fn) => { row.click = fn; }};
    return row;
}
// runs table_filter.js on a page of these elements, the stored values given; its document click listener
function run(elements, stored) {
    const listeners = {};
    const doc = {title: "VMs", getElementById: (id) => elements[id], querySelectorAll: () => [],
                 addEventListener: (name, fn) => { listeners[name] = fn; }};
    const storage = {getItem: (k) => stored[k] || null, setItem: (k, v) => { stored[k] = v; }, removeItem: (k) => { delete stored[k]; }};
    vmModule.runInNewContext(fs.readFileSync(process.argv[2], "utf8"), {document: doc, sessionStorage: storage});
    return listeners.click;
}
const listPage = () => ({
    filter: {value: "", hasAttribute: () => false, addEventListener() {}, focus() { this.focused = true; }},
    "state-filter": {value: "", addEventListener() {}},
    "state-pills": pillRow(["", "Active", "Off"]),
    "tag-filter": {value: ""},
    "tag-pills": pillRow(["", "-", "prod", "web"]),
});
{
    const stored = {"VMs_filter_state": "Off", "VMs_filter_tag": "prod"};
    const elements = listPage();
    const click = run(elements, stored);
    assert.strictEqual(elements["state-filter"].value, "Off");
    assert.strictEqual(elements["tag-filter"].value, "prod", "the chosen tag is remembered too");
    // a tag's pill pressed
    const tags = elements["tag-pills"];
    tags.click({target: {closest: () => tags.pills[1]}});
    assert.deepStrictEqual([elements["tag-filter"].value, stored["VMs_filter_tag"]], ["-", "-"]);
    // a tag's badge chooses its pill
    click({target: {closest: (s) => (s === "[data-tag-filter]" ? {dataset: {tagFilter: "web"}} : null)}});
    assert.strictEqual(elements["tag-filter"].value, "web", "a badge chooses its tag");
    assert.strictEqual(stored["VMs_filter_tag"], "web", "and it is remembered");
    // "…" shows a VM's other tags, and the first of them takes the focus
    let focused = null;
    const others = {hidden: true, querySelector: () => ({focus: () => { focused = "d4"; }})};
    const ellipsis = {hidden: false, nextElementSibling: others};
    click({target: {closest: (s) => (s === "[data-show-tags]" ? ellipsis : null)}});
    assert.deepStrictEqual([others.hidden, ellipsis.hidden, focused], [false, true, "d4"]);
    // tags that are not buttons (no tag pills on the page): the tags shown take it
    const plain = {hidden: true, querySelector: () => null, focus: () => { focused = "plain"; }};
    click({target: {closest: (s) => (s === "[data-show-tags]" ? {hidden: false, nextElementSibling: plain} : null)}});
    assert.strictEqual(focused, "plain");
}

// "Clear the filters" hides with the message it is in: the search box takes the focus
{
    const elements = listPage();
    elements["clear-filters"] = {addEventListener: (name, fn) => { elements["clear-filters"].click = fn; }};
    run(elements, {"VMs_filter_tag": "prod"});
    elements["clear-filters"].click();
    assert.deepStrictEqual([elements["tag-filter"].value, elements.filter.focused], ["", true]);
}

// a kept tag no pill has any longer is forgotten: made again later, it is not chosen by itself
{
    const stored = {"VMs_filter_tag": "gone"};
    const elements = listPage();
    run(elements, stored);
    assert.deepStrictEqual([elements["tag-filter"].value, stored], ["", {}]);
    // nor when the list has no tag left to offer (no tag pills on the page)
    stored["VMs_filter_tag"] = "prod";
    delete elements["tag-pills"];
    delete elements["tag-filter"];
    run(elements, stored);
    assert.deepStrictEqual(stored, {});
}
