// A network filter's page (nwfilter.html).
// each editor's text goes in its form's hidden field, the starter too if sent as it is,
// and it measures itself when its section or dialog is shown
function xmlEditor(textareaId, fieldName, shownBy, shownEvent) {
    var textarea = document.getElementById(textareaId);
    var form = textarea.closest("form");
    var editor = ace.edit(textareaId);
    editor.getSession().setMode("ace/mode/xml");
    editor.setOption("textInputAriaLabel", textarea.getAttribute("aria-label"));
    var field = form.elements[fieldName];
    field.value = editor.getSession().getValue();
    editor.getSession().on("change", function () {
        field.value = editor.getSession().getValue();
    });
    document.getElementById(shownBy).addEventListener(shownEvent, () => editor.resize());
}
xmlEditor("edit_editor", "edit_xml", "nwfilter-xml", "shown.bs.collapse");
xmlEditor("rule_editor", "nwfilterrule_xml", "AddNWFilterRule", "shown.bs.modal");
