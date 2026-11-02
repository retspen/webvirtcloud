// The network filters page (nwfilters.html): the Clone dialog takes the
// filter of its row, and the New filter dialog's XML editor fills its form.
var cloneDialog = document.getElementById("CloneNWFilter");
if (cloneDialog) {
    cloneDialog.addEventListener("show.bs.modal", function (event) {
        var name = event.relatedTarget.dataset.name;
        this.querySelector("form").elements.nwfiltername.value = name;
        document.getElementById("clone_source").textContent = name;
        document.getElementById("clone_name").value = name + "-copy";
    });
}

var textarea = document.getElementById("create_editor");
var editor = ace.edit("create_editor");
editor.getSession().setMode("ace/mode/xml");
editor.setOption("textInputAriaLabel", textarea.getAttribute("aria-label"));
var input = $('input[name="nwfilter_xml"]');
input.val(editor.getSession().getValue());  // the starter too, if sent as it is
editor.getSession().on("change", function () {
    input.val(editor.getSession().getValue());
});
// the editor measures itself when its dialog is shown
document.getElementById("AddNWFilter").addEventListener("shown.bs.modal", () => editor.resize());
