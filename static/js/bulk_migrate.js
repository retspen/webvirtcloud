// The Bulk Migrate page: another destination reloads the list; the header
// box ticks or unticks every VM that can migrate, "Also migrate the
// shut-off VMs" the shut-off ones. The Migrate button counts the ticked
// VMs and is off while none is.
function tick(selector, checked) {
    document.querySelectorAll(selector).forEach(function (box) {
        box.checked = checked;
    });
}
function count() {
    const ticked = document.querySelectorAll("input[name=instance]:checked").length;
    const button = document.getElementById("bulk-migrate-submit");
    if (button) {
        button.disabled = ticked === 0;
        document.getElementById("bulk-migrate-count").textContent = ticked;
    }
}
document.getElementById("bulk-migrate-target")?.addEventListener("change", function (event) {
    event.target.form.submit();
});
document.getElementById("bulk-migrate-all")?.addEventListener("change", function (event) {
    tick("input[name=instance]:not(:disabled)", event.target.checked);
});
document.getElementById("bulk-migrate-shut-off")?.addEventListener("change", function (event) {
    tick("input[data-shut-off]:not(:disabled)", event.target.checked);
});
document.addEventListener("change", count);
count();
