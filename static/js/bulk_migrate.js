// The Bulk Migrate page: another destination reloads the list; the header
// box ticks or unticks every VM that can migrate, "Also migrate the
// shut-off VMs" the shut-off ones.
function tick(selector, checked) {
    document.querySelectorAll(selector).forEach(function (box) {
        box.checked = checked;
    });
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
