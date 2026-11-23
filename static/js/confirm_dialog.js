// confirmAction asks in the page's confirm dialog before act runs: action is its
// title and its confirming button's words, question its body. opener is what
// asked (or null): in another dialog, that one is hidden while asking (Bootstrap
// does not stack dialogs) and shown again after; not confirmed, it takes the focus
// back, or its menu's toggle, as a menu's item is hidden with its menu.
function confirmAction(action, question, danger, act, opener) {
    var dialog = document.getElementById("confirm-dialog");
    var parent = opener && opener.closest(".modal");
    var ok = dialog.querySelector("[data-confirm-ok]");
    var confirmed = false;
    dialog.querySelector(".modal-title").textContent = action;
    dialog.querySelector(".modal-body").textContent = question;
    ok.textContent = action;
    ok.className = "btn " + (danger ? "btn-danger" : "btn-primary");
    ok.disabled = true;  // until shown: Bootstrap does not hide a dialog still coming in
    dialog.addEventListener("shown.bs.modal", function () { ok.disabled = false; }, {once: true});
    ok.onclick = function () {
        ok.disabled = true;  // once: the dialog is still open while it hides
        confirmed = true;
        bootstrap.Modal.getInstance(dialog).hide();
        act();
    };
    dialog.addEventListener("hidden.bs.modal", function () {
        if (parent) {
            // a form sent in place (the flavors) keeps its dialog; a page sent away does not care
            bootstrap.Modal.getOrCreateInstance(parent).show();
        } else if (!confirmed && opener && opener.isConnected) {
            var menu = opener.closest(".dropdown-menu");
            var toggle = menu && menu.parentElement.querySelector("[data-bs-toggle=dropdown]");
            (toggle || opener).focus();
        }
    }, {once: true});
    var ask = function () { bootstrap.Modal.getOrCreateInstance(dialog).show(); };
    if (parent) {
        parent.addEventListener("hidden.bs.modal", ask, {once: true});
        bootstrap.Modal.getInstance(parent).hide();
    } else {
        ask();
    }
}

// A button with data-confirm asks first, in its own words (or its accessible name,
// for an icon); confirmed, it is clicked again, so its form sends its name and value.
document.addEventListener("click", function (event) {
    var button = event.target.closest("button[data-confirm]");
    if (!button || button.dataset.confirmed) return;
    event.preventDefault();
    var action = button.textContent.trim() || button.getAttribute("aria-label") || button.title;
    confirmAction(action, button.dataset.confirm, /\b(btn-|btn-outline-|text-)danger\b/.test(button.className), function () {
        button.dataset.confirmed = "1";
        button.click();
        delete button.dataset.confirmed;
    }, button);
}, true);
