// The secrets page (secrets.html): the labels of a secret's usage and
// value follow its usage type (usage_texts from the view).
var usageTexts = JSON.parse(document.getElementById("usage-texts").textContent);

var usageType = document.getElementById("secret_usage_type");
if (usageType) {
    var showUsage = function () {
        var texts = usageTexts[usageType.value];
        document.getElementById("secret_usage_label").textContent = texts.usage;
        document.getElementById("secret_usage_help").textContent = texts.usageHelp;
        document.getElementById("secret_value_label").textContent = texts.value;
        document.getElementById("secret_value_help").textContent = texts.valueHelp + " " + usageTexts.later;
    };
    usageType.addEventListener("change", showUsage);
    showUsage();
}

var setValue = document.getElementById("SetSecretValue");
if (setValue) {
    setValue.addEventListener("show.bs.modal", function (event) {
        var row = event.relatedTarget.dataset;
        var texts = usageTexts[row.type] || usageTexts.none;
        var form = this.querySelector("form");
        form.reset();  // no value of another secret stays in the field
        form.elements.uuid.value = row.uuid;
        document.getElementById("value_usage").textContent = row.usage;
        document.getElementById("set_value_label").textContent = texts.value;
        document.getElementById("set_value_help").textContent = texts.valueHelp;
        // a passphrase's data stays encrypted with the old one
        var passphrase = ["volume", "tls", "vtpm"].includes(row.type);
        document.getElementById("set_value_note").hidden = !passphrase;
        form.elements.value.setAttribute("aria-describedby", passphrase ? "set_value_help set_value_note" : "set_value_help");
    });
}
