// node table_filter.test.js path/to/static/js/table_filter.js
const assert = require("assert");
const {filterTable: filterInstances} = require(process.argv[2]);

// A minimal DOM: table bodies of rows; a VM row holds its state mark, a
// group's header row is marked as one.
function vm(text, state) {
    const mark = {dataset: {state}};
    return {textContent: text, hidden: false, hasAttribute: () => false,
            querySelector: (s) => (s === "[data-state]" ? mark : null)};
}
function hostRow(text) {
    return {textContent: text, hidden: false, hasAttribute: (a) => a === "data-group-header", querySelector: () => null};
}
function plainRow(text) {
    return {textContent: text, hidden: false, hasAttribute: () => false, querySelector: () => null};
}
function group(rows, host) {
    return {dataset: host ? {host} : {}, querySelectorAll: (s) => (s === "tr" ? rows : [])};
}
function page(groups, text, state) {
    // a list without a state list (state undefined) has no such element
    const inputs = {filter: {value: text}, "state-filter": state === undefined ? undefined : {value: state}};
    return {
        getElementById: (id) => inputs[id],
        querySelectorAll: (s) => (s === ".searchable" ? groups : []),
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

// any other list: no state list, no groups; its rows are filtered by their text
const plain = [plainRow("alice Active"), plainRow("bob (vda) Blocked"), plainRow("carol Active")];
filterInstances(page([group(plain)], "ACTIVE"));
assert.deepStrictEqual(visible(plain), ["alice Active", "carol Active"], "a plain list is searched");
filterInstances(page([group(plain)], "(vda"));
assert.deepStrictEqual(visible(plain), ["bob (vda) Blocked"], "a bracket is text there too");
filterInstances(page([group(plain)], ""));
assert.deepStrictEqual(visible(plain), ["alice Active", "bob (vda) Blocked", "carol Active"]);
