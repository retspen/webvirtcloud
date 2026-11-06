// node instance_tabs.test.js path/to/static/js/instance_tabs.js
const assert = require("assert");
const {restoreInstanceTab} = require(process.argv[2]);

// A minimal DOM: elements with an id, classes, a parent, children, and the
// few selectors restoreInstanceTab uses.
function el(id, classes, children = [], attrs = {}) {
    const node = {id, classList: new Set(classes), children, attrs, parentElement: null};
    node.classList.contains = (c) => node.classList.has(c);
    node.getAttribute = (name) => attrs[name];
    for (const child of children) child.parentElement = node;
    node.querySelector = (selector) => find(node, selector);
    return node;
}

function* walk(node) {
    for (const child of node.children) {
        yield child;
        yield* walk(child);
    }
}

function matches(node, selector) {
    if (selector === "[role=tablist]") return node.attrs.role === "tablist";
    if (selector === ".nav-link.active") return node.classList.has("nav-link") && node.classList.has("active");
    if (selector === ".nav-link:not(#osinfo-tab)") return node.classList.has("nav-link") && node.id !== "osinfo-tab";
    if (selector === "#osinfo-tab") return node.id === "osinfo-tab";
    throw new Error("unsupported selector " + selector);
}

function find(root, selector) {
    for (const node of walk(root)) if (matches(node, selector)) return node;
    return null;
}

function link(target, extra = []) {
    return el(target === "#osinfo" ? "osinfo-tab" : "", ["nav-link", ...extra], [], {"data-bs-target": target});
}

// The VM page: top-level panes, Settings with its own tabs and panes.
function page(settingsLinks) {
    const settings = el("settings", ["tab-pane"], [
        el("", ["nav", "nav-underline"], settingsLinks, {role: "tablist"}),
        el("", ["tab-content"], [el("osinfo", ["tab-pane"]), el("options", ["tab-pane"]), el("vncsettings", ["tab-pane"])]),
    ]);
    const root = el("", [], [el("", ["tab-content"], [el("power", ["tab-pane", "active"]), el("access", ["tab-pane"]), settings])]);
    root.getElementById = (id) => {
        for (const node of walk(root)) if (node.id === id) return node;
        return null;
    };
    return root;
}

function run(doc, hash) {
    const shown = [];
    let loaded = 0;
    restoreInstanceTab(doc, hash, (target) => shown.push(target), () => loaded++);
    return {shown, loaded};
}

const settled = () => page([link("#options", ["active"])]);

// a top-level pane opens directly
assert.deepStrictEqual(run(settled(), "#access").shown, ["#access"]);
// a pane inside Settings opens Settings first
assert.deepStrictEqual(run(settled(), "#options").shown, ["#settings", "#options"]);
// no hash, an unknown one, or one with odd characters opens nothing
for (const hash of ["", "#", "#nosuchpane", '#a"]b']) {
    assert.deepStrictEqual(run(settled(), hash).shown, [], hash);
}
// Settings without an active section opens its first one, not OS info
assert.deepStrictEqual(run(page([link("#osinfo"), link("#vncsettings")]), "").shown, ["#vncsettings"]);
// OS info as the only section is selected and loaded
assert.deepStrictEqual(run(page([link("#osinfo")]), ""), {shown: ["#osinfo"], loaded: 1});
// a redirect to OS info loads it
assert.deepStrictEqual(run(settled(), "#osinfo"), {shown: ["#settings", "#osinfo"], loaded: 1});
console.log("ok");
