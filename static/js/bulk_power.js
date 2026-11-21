// The VM list's bulk action bar. Only the chosen VMs on screen count: one a
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
        var tooMany = chosen > Number(count.dataset.max);  // the server takes at most that many
        form.querySelectorAll("button[name='action']").forEach(function (button) { button.disabled = tooMany; });
        count.textContent = (tooMany ? count.dataset.tooMany : count.dataset.text).replace("%(count)s", chosen);
        count.classList.toggle("text-danger", tooMany);
        // the bar at the window's foot, while any VM is chosen; the page ends above it
        form.hidden = chosen === 0;
        if (form.hidden) {
            document.body.style.removeProperty("padding-bottom");
        } else {  // over base.html's pb-5
            document.body.style.setProperty("padding-bottom", form.offsetHeight + "px", "important");
        }
        shown.disabled = boxes.length === 0;
        shown.checked = boxes.length > 0 && chosen === boxes.length;
        shown.indeterminate = chosen > 0 && chosen < boxes.length;
    }
    document.getElementById("bulk-power-clear").addEventListener("click", function () {
        document.querySelectorAll("input[name='vm'][form='bulk-power']").forEach(function (box) { box.checked = false; });
        update();
    });
    // a menu of the bar opens on its text box
    form.addEventListener("shown.bs.dropdown", function (event) {
        event.target.parentElement.querySelector("input[type='text']").focus();
    });
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
    // Enter in a text box would send the form with its first button, Start: in a snapshot's
    // name it takes the snapshots, in a tag (added or removed?) it sends nothing
    form.querySelectorAll("input[type='text']").forEach(function (box) {
        box.addEventListener("keydown", function (event) {
            if (event.key === "Enter" && !event.isComposing) {  // not an input method's choice
                event.preventDefault();
                if (box.name === "snapshot_name") {
                    form.querySelector("button[value='snapshot']").click();
                }
            }
        });
    });
    form.addEventListener("submit", function (event) {
        document.querySelectorAll("input[name='vm'][form='bulk-power']:checked").forEach(function (box) {
            if (!box.getClientRects().length) {
                box.checked = false;  // hidden: not sent
            }
        });
        // counted again: rows may have come on screen since the buttons were last set
        if (document.querySelectorAll("input[name='vm'][form='bulk-power']:checked").length > Number(count.dataset.max)) {
            event.preventDefault();
            update();
        }
    });
    update();
})();

// whether VMs on screen are chosen, or a snapshot name or tag typed in the bar shown: the list's reload
// (poll.js pageInUse) waits meanwhile
function bulkPowerChosen() {
    return Array.prototype.some.call(document.querySelectorAll("input[name='vm'][form='bulk-power']:checked"),
        function (box) { return box.getClientRects().length > 0; })
        || Array.prototype.some.call(document.querySelectorAll("#bulk-power:not([hidden]) input[type='text']"),
            function (box) { return box.value.trim() !== ""; });
}
