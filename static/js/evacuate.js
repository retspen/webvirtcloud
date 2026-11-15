// The evacuate page: "Also migrate the shut-off VMs" ticks or unticks them.
document.getElementById("evacuate-shut-off")?.addEventListener("change", function (event) {
    document.querySelectorAll("input[data-shut-off]:not(:disabled)").forEach(function (box) {
        box.checked = event.target.checked;
    });
});
