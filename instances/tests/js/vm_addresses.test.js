// Behaviour of static/js/vm_addresses.js with a fake document and fetch.
// Run by instances/tests/test_vm_addresses.py:
// node vm_addresses.test.js static/js/vm_addresses.js
const fs = require("fs");
const assert = require("assert");

function place(family, macs, empty) {
    const classes = new Set(["text-body-secondary"]);
    return { dataset: { addressFamily: family, addressMac: macs, empty }, textContent: "Reading…",
             classList: { toggle(name, on) { if (on) classes.add(name); else classes.delete(name); } }, classes };
}
// the header (the VM's NICs), a NIC's IPv4 and IPv6, a NIC the guest has no address on
const header = place("ipv4", "52:54:00:00:00:01 52:54:00:00:00:02 ", "—");
const ipv4 = place("ipv4", "52:54:00:00:00:01", "No IPv4 address known");
const ipv6 = place("ipv6", "52:54:00:00:00:01", "unknown");
const other = place("ipv4", "52:54:00:00:00:02", "No IPv4 address known");
global.document = { querySelectorAll: () => [header, ipv4, ipv6, other], currentScript: { dataset: { url: "/instances/7/addresses/" } } };
let asked = null;
global.fetch = (url) => {
    asked = url;
    // a guest's own bridge (docker0) is not one of the VM's NICs
    return Promise.resolve({ ok: true, json: () => ({
        "52:54:00:00:00:01": { ipv4: ["192.0.2.10"], ipv6: ["2001:db8::10/64"] },
        "02:42:ac:11:00:01": { ipv4: ["172.17.0.1"], ipv6: [] } }) });
};
eval(fs.readFileSync(process.argv[2], "utf8"));
setTimeout(() => {
    assert.strictEqual(asked, "/instances/7/addresses/");
    assert.strictEqual(header.textContent, "192.0.2.10", "only the VM's NICs");
    assert.strictEqual(ipv4.textContent, "192.0.2.10");
    assert.strictEqual(ipv6.textContent, "2001:db8::10/64");
    assert.ok(!ipv4.classes.has("text-body-secondary"), "an address is not muted");
    assert.strictEqual(other.textContent, "No IPv4 address known");
    assert.ok(other.classes.has("text-body-secondary"));
}, 0);
