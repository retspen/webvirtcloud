// The password change form: the eye button shows or hides both new
// entries, and the rules the browser can check are ticked as you type.
// The server checks every rule again when the form is sent.
var newPassword = document.getElementById("id_new_password1");
var again = document.getElementById("id_new_password2");
var rules = document.getElementById("password-rules");

document.getElementById("toggle-new-password").addEventListener("click", function () {
    var shown = newPassword.type === "password";
    newPassword.type = again.type = shown ? "text" : "password";
    this.setAttribute("aria-pressed", String(shown));
    this.querySelector("i").className = shown ? "bi bi-eye-slash" : "bi bi-eye";
});

function tick() {
    var value = newPassword.value;
    // as Python counts them: characters, not UTF-16 units; any digit, as str.isdigit
    var met = {
        length: Array.from(value).length >= 8,
        letters: value !== "" && !/^[\p{Nd}\p{No}]+$/u.test(value),
        match: value !== "" && value === again.value,
    };
    Object.keys(met).forEach(function (rule) {
        var item = rules.querySelector('[data-rule="' + rule + '"]');
        item.classList.toggle("text-success", met[rule]);
        item.querySelector("i").className = (met[rule] ? "bi bi-check-circle-fill" : "bi bi-circle") + " me-2";
        item.querySelector(".visually-hidden").textContent = met[rule] ? rules.dataset.met : rules.dataset.unmet;
    });
}
newPassword.addEventListener("input", tick);
again.addEventListener("input", tick);
