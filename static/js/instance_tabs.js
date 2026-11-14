// The tab the VM page opens on.
//
// A redirect points at a pane (#access, #resize, #options, ...): open the tab
// that holds it first, then the pane itself; the page structure tells which
// tab holds which pane. Settings opens on its first section the user has;
// guest OS info is loaded whenever it is the section opened.
//
// show(target) opens the tab whose control targets "#id"; loadInfo() fetches
// the guest OS info.
function restoreInstanceTab(doc, hash, show, loadInfo) {
    var pane = hash && hash.length > 1 ? doc.getElementById(hash.slice(1)) : null;
    if (pane && pane.classList.contains("tab-pane")) {
        var holder = pane.parentElement;
        while (holder && !holder.classList.contains("tab-pane")) {
            holder = holder.parentElement;
        }
        if (holder) {
            show("#" + holder.id);
        }
        show(hash);
        if (hash === "#osinfo") {
            loadInfo();
        }
    }
    var settings = doc.getElementById("settings");
    var tabs = settings ? settings.querySelector("[role=tablist]") : null;
    if (tabs && !tabs.querySelector(".nav-link.active")) {
        var first = tabs.querySelector(".nav-link:not(#osinfo-tab)");
        if (first) {
            show(first.getAttribute("data-bs-target"));
        } else if (tabs.querySelector("#osinfo-tab")) {
            show("#osinfo");
            loadInfo();
        }
    }
}

if (typeof module !== "undefined") {
    module.exports = {restoreInstanceTab: restoreInstanceTab};
}
