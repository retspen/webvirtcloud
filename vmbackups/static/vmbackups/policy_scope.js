// A backup schedule's Which VMs: only the field of the choice made shows (vmbackups.forms.PolicyForm).
(function () {
    var choices = document.querySelectorAll("input[name='scope']");
    function show() {
        var chosen = document.querySelector("input[name='scope']:checked");
        document.querySelectorAll("[data-scope]").forEach(function (field) {
            field.hidden = !chosen || field.dataset.scope !== chosen.value;
        });
    }
    choices.forEach(function (choice) { choice.addEventListener("change", show); });
    show();
})();
