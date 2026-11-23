// The Balance page: unticking a VM keeps it where it is, ticking it again
// lets it move; either makes the proposal again. The header box ticks or
// unticks every VM listed. The boxes sit in the page's tables and belong
// to the proposal's form by their form attribute.
const form = document.getElementById("balance-form");
document.addEventListener("change", function (event) {
    if (!form || event.target.form !== form) {
        return;
    }
    if (event.target.id === "balance-all") {
        for (const box of form.elements) {
            if (box.name === "vm") {
                box.checked = event.target.checked;
            }
        }
    }
    form.submit();
});
