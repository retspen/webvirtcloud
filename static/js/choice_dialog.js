// A create dialog of one form whose radio cards choose what is made (the
// New pool and New network dialogs): a fieldset shows for the choices in
// its data-kinds, the others are hidden and disabled, so neither checked
// nor sent; onChoose(value) does what else a choice changes. A form the
// server refused (data-open on the dialog) opens again with what was
// entered: the choice sent back, or the first when it is offered no more,
// and focus on the first refused field shown, or on the reasons.
function choiceDialog(dialog, radioName, onChoose) {
    var form = dialog.querySelector("form");
    var radios = form.querySelectorAll("input[name=" + radioName + "]");
    function choose(value) {
        form.querySelectorAll("fieldset[data-kinds]").forEach(function (fields) {
            fields.hidden = fields.disabled = !fields.dataset.kinds.split(" ").includes(value);
        });
        onChoose(value);
    }
    radios.forEach(function (radio) {
        radio.addEventListener("change", function () { choose(radio.value); });
    });
    var chosen = form.querySelector("input[name=" + radioName + "]:checked") || radios[0];
    chosen.checked = true;
    choose(chosen.value);
    if (dialog.hasAttribute("data-open")) {
        dialog.addEventListener("shown.bs.modal", function () {
            var refused = Array.from(form.querySelectorAll("[aria-invalid=true]")).find(function (field) {
                return !field.closest("fieldset[hidden]");
            });
            var reasons = form.querySelector(".form-errors");
            if (refused) {
                refused.focus();
            } else if (reasons) {
                reasons.tabIndex = -1;
                reasons.focus();
            }
        }, {once: true});
        bootstrap.Modal.getOrCreateInstance(dialog).show();
    }
}
