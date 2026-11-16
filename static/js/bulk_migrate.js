// The Bulk Migrate page: another destination reloads the list; the header
// box ticks or unticks every VM that can migrate, "Also migrate the
// shut-off VMs" the shut-off ones. Spread over the hosts, a change reloads
// the list too: where each VM goes depends on the others. The Migrate
// button counts the ticked VMs and is off while none is.
const choose = document.getElementById("bulk-migrate-choose");
const spreading = choose?.dataset.spread !== undefined;

function tick(selector, checked) {
    document.querySelectorAll(selector).forEach(function (box) {
        box.checked = checked;
    });
}
function count() {
    const ticked = document.querySelectorAll(".bulk-migrate-vm:checked").length;
    const button = document.getElementById("bulk-migrate-submit");
    if (button) {
        button.disabled = ticked === 0;
        document.getElementById("bulk-migrate-count").textContent = ticked;
    }
}
document.getElementById("bulk-migrate-target")?.addEventListener("change", function (event) {
    if (event.target.value !== "spread") {
        // one host: the VMs ticked are the page's own choice again
        choose.querySelectorAll("input[name=shown]").forEach((input) => input.remove());
    }
    event.target.form.submit();
});
document.getElementById("bulk-migrate-all")?.addEventListener("change", function (event) {
    tick(".bulk-migrate-vm:not(:disabled)", event.target.checked);
});
document.getElementById("bulk-migrate-shut-off")?.addEventListener("change", function (event) {
    tick(".bulk-migrate-vm[data-shut-off]:not(:disabled)", event.target.checked);
});
document.addEventListener("change", function (event) {
    if (spreading && event.target.id !== "bulk-migrate-parallel" && event.target.id !== "bulk-migrate-target") {
        choose.submit();
        return;
    }
    count();
});
count();
