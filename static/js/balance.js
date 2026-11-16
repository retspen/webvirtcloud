// The Balance page: unticking a VM keeps it where it is, ticking it again
// lets it move; either makes the proposal again. The header box ticks or
// unticks every VM listed.
const form = document.getElementById("balance-form");
form?.addEventListener("change", function (event) {
    if (event.target.id === "balance-all") {
        form.querySelectorAll("input[name=vm]").forEach(function (box) {
            box.checked = event.target.checked;
        });
    }
    form.submit();
});
