// A button with data-confirm asks in the page's confirm dialog before it acts:
// the dialog's title and its confirming button carry the button's own words
// (or its accessible name, for an icon), its body the data-confirm question.
// Confirmed, the button is clicked again, so its form sends its name and value.
// A button in another dialog hides that one while asking (Bootstrap does not
// stack dialogs) and shows it again after; Cancel gives the focus back.
document.addEventListener("click", function (event) {
    var button = event.target.closest("button[data-confirm]");
    if (!button || button.dataset.confirmed) return;
    event.preventDefault();
    var dialog = document.getElementById("confirm-dialog");
    var parent = button.closest(".modal");
    var action = button.textContent.trim() || button.getAttribute("aria-label") || button.title;
    var ok = dialog.querySelector("[data-confirm-ok]");
    var confirmed = false;
    dialog.querySelector(".modal-title").textContent = action;
    dialog.querySelector(".modal-body").textContent = button.dataset.confirm;
    ok.textContent = action;
    ok.className = "btn " + (/\b(btn-|btn-outline-|text-)danger\b/.test(button.className) ? "btn-danger" : "btn-primary");
    ok.disabled = false;
    ok.onclick = function () {
        ok.disabled = true;  // once: the dialog is still open while it hides
        confirmed = true;
        bootstrap.Modal.getInstance(dialog).hide();
        button.dataset.confirmed = "1";
        button.click();
        delete button.dataset.confirmed;
    };
    dialog.addEventListener("hidden.bs.modal", function () {
        if (parent) {
            // a form sent in place (the flavors) keeps its dialog; a page sent away does not care
            bootstrap.Modal.getOrCreateInstance(parent).show();
        } else if (!confirmed) {
            // a menu's item is hidden with its menu: its toggle takes the focus
            var menu = button.closest(".dropdown");
            (menu ? menu.querySelector("[data-bs-toggle=dropdown]") : button).focus();
        }
    }, {once: true});
    var ask = function () { bootstrap.Modal.getOrCreateInstance(dialog).show(); };
    if (parent) {
        parent.addEventListener("hidden.bs.modal", ask, {once: true});
        bootstrap.Modal.getInstance(parent).hide();
    } else {
        ask();
    }
}, true);
