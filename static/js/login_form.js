// The sign-in forms (login, OTP login): the eye button shows or hides the
// password, and a line says when Caps Lock is on. While the form is sent, its
// button shows it as every form's does (submit_busy.js).
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
