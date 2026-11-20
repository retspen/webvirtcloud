// The VM list's bulk power form. Only the chosen VMs on screen count: one a
// filter or a collapsed host hides is neither counted nor sent, so a VM chosen
// before the filters changed is not powered unseen. "Choose the VMs shown"
// chooses or clears those on screen, and shows whether all, some or none are.
(function () {
    var form = document.getElementById("bulk-power");
    var shown = document.getElementById("bulk-power-shown");
    var count = document.getElementById("bulk-power-count");
    function onScreen() {
        return Array.prototype.filter.call(document.querySelectorAll("input[name='vm'][form='bulk-power']"),
            function (box) { return box.getClientRects().length > 0; });
    }
    function update() {
        var boxes = onScreen();
        var chosen = boxes.filter(function (box) { return box.checked; }).length;
        form.querySelectorAll("button[name='action']").forEach(function (button) { button.disabled = chosen === 0; });
        count.textContent = chosen ? count.dataset.text.replace("%(count)s", chosen) : "";
        shown.disabled = boxes.length === 0;
        shown.checked = boxes.length > 0 && chosen === boxes.length;
        shown.indeterminate = chosen > 0 && chosen < boxes.length;
    }
    shown.addEventListener("change", function () {
        var choose = shown.checked;
        onScreen().forEach(function (box) { box.checked = choose; });
        update();
    });
    // a box, the search, a state or tag pill or a host's collapse changes what is on screen; not
    // "Choose the VMs shown" itself: its input event comes before its change, which chooses the boxes
    function changed(event) {
        if (event.target !== shown) {
            setTimeout(update, 0);
        }
    }
    ["change", "input", "click"].forEach(function (type) { document.addEventListener(type, changed); });
    // and a filter that answers later (the address search) hides rows by itself
    var later = null;
    new MutationObserver(function () {
        clearTimeout(later);
        later = setTimeout(update, 50);
    }).observe(document.querySelector(".table-responsive") || document.body,
               {attributes: true, attributeFilter: ["hidden", "class"], subtree: true});
    // Enter in the tag box would send the form with its first button, Start: it sends nothing
    var tagBox = document.getElementById("bulk-tag");
    if (tagBox) {
        tagBox.addEventListener("keydown", function (event) {
            if (event.key === "Enter") {
                event.preventDefault();
            }
        });
    }
    form.addEventListener("submit", function () {
        document.querySelectorAll("input[name='vm'][form='bulk-power']:checked").forEach(function (box) {
            if (!box.getClientRects().length) {
                box.checked = false;  // hidden: not sent
            }
        });
    });
    update();
})();

// whether VMs on screen are chosen: the list's reload (poll.js pageInUse) waits meanwhile
function bulkPowerChosen() {
    return Array.prototype.some.call(document.querySelectorAll("input[name='vm'][form='bulk-power']:checked"),
        function (box) { return box.getClientRects().length > 0; });
}
