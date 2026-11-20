// The sign-in forms (login, OTP login): the eye button shows or hides the
// password, a line says when Caps Lock is on, and while the form is sent its
// button is disabled and says so.
document.getElementById("btn-toggle-pwd").addEventListener("click", function () {
    var password = document.getElementById("id_password");
    var shown = password.type === "password";
    password.type = shown ? "text" : "password";
    var icon = document.getElementById("toggle-icon");
    icon.classList.toggle("bi-eye", !shown);
    icon.classList.toggle("bi-eye-slash", shown);
});

["keydown", "keyup"].forEach(function (type) {
    document.getElementById("id_password").addEventListener(type, function (event) {
        var on = event.getModifierState && event.getModifierState("CapsLock");
        document.getElementById("caps-lock").classList.toggle("d-none", !on);
    });
});
// Caps Lock may change elsewhere: the line waits for the next key here
document.getElementById("id_password").addEventListener("blur", function () {
    document.getElementById("caps-lock").classList.add("d-none");
});

document.getElementById("form-signin").addEventListener("submit", function () {
    var button = document.getElementById("btn-signin");
    button.disabled = true;
    var spinner = document.createElement("span");
    spinner.className = "spinner-border spinner-border-sm me-2";
    spinner.setAttribute("aria-hidden", "true");
    button.replaceChildren(spinner, button.dataset.busyText);
});
