// A list's filter form (data-filter-form) asks the server again once a choice
// changes or Enter is pressed in a text box: it has no button of its own.
document.querySelectorAll("form[data-filter-form]").forEach(function (form) {
    form.addEventListener("change", function (event) {
        if (event.target.matches("select, input[type='checkbox']")) {
            form.requestSubmit();
        }
    });
    form.addEventListener("keydown", function (event) {
        if (event.key === "Enter" && !event.isComposing && event.target.matches("input:not([type]), input[type='text'], input[type='search']")) {
            event.preventDefault();
            form.requestSubmit();
        }
    });
});
