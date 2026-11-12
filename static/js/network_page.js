// A network's page (network.html): its XML editor and the dialogs its rows open.
var editor = ace.edit("edit_editor");
editor.getSession().setMode("ace/mode/xml");
var editInput = $('input[name="edit_xml"]');
editor.getSession().on("change", function () {
    editInput.val(editor.getSession().getValue());
});
// the editor measures itself when its section is shown
document.getElementById("network-xml").addEventListener("shown.bs.collapse", () => editor.resize());

// a dialog opened by a row's button gets that row's values, one opened by an Add button starts empty
function fillFrom(dialogId, fill) {
    var dialog = document.getElementById(dialogId);
    if (dialog) dialog.addEventListener("show.bs.modal", function (event) {
        fill(dialog.querySelector("form"), event.relatedTarget.dataset);
    });
}
fillFrom("FixedAddress", function (form, data) {
    form.elements.original.value = data.original || "";
    // the entry as shown: a change made meanwhile is not undone
    form.elements.original_id.value = data.original ? data.mac : "";
    form.elements.original_name.value = data.original ? data.name : "";
    form.elements.address.value = data.address || "";
    form.elements.mac.value = data.mac || "";
    form.elements.name.value = data.name || "";
    // Add starts from the first subnet, not the one a row chose before
    form.elements.ip_index.value = data.ipIndex || form.elements.ip_index.options[0].value;
    document.getElementById("fixed_subnet_row").hidden = Boolean(data.original);
});
fillFrom("DhcpRange", function (form, data) {
    form.elements.ip_index.value = data.ipIndex;
    form.elements.range_start.value = data.start;
    form.elements.range_end.value = data.end;
    document.getElementById("dhcp_subnet").textContent = data.subnet;
});
fillFrom("QosLimit", function (form, data) {
    var direction = form.elements.qos_direction;
    direction.querySelectorAll("option").forEach(function (option) {
        option.disabled = data.direction ? option.value !== data.direction : option.hasAttribute("data-taken");
    });
    direction.value = data.direction || direction.querySelector("option:not(:disabled)").value;
    form.elements.qos_average.value = data.average || "";
    form.elements.qos_peak.value = data.peak || "";
    form.elements.qos_burst.value = data.burst || "";
});
