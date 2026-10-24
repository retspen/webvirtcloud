// The VM page's XML editor. Change shows the lines the edit changes in the
// VM's definition (instances.views.change_xml), and Save in that dialog
// defines it. A refusal shows in the dialog, and the edit stays in the editor.
(function () {
    var form = document.getElementById("xml-form");
    if (!form) {
        return; // the editor exists only for superusers
    }
    var editor = ace.edit("editor");
    editor.getSession().setMode("ace/mode/xml");
    var base = editor.getValue(); // the definition the editor opened with
    var dialog = document.getElementById("xml-review");
    if (!dialog) {
        return; // a running VM's editor only shows its XML
    }
    var modal = bootstrap.Modal.getOrCreateInstance(dialog);
    var error = document.getElementById("xml-review-error");
    var same = document.getElementById("xml-review-same");
    var diff = document.getElementById("xml-review-diff");
    var save = document.getElementById("xml-review-save");
    var reviewed = ""; // Save defines the XML the dialog shows, not later edits

    // null after a redirect (the VM is busy or moved): the page says why
    function post(xml, confirm) {
        var data = new FormData(form);
        data.set("inst_xml", xml);
        data.set("base", base);
        if (confirm) {
            data.set("confirm", "1");
        }
        return fetch(form.action, {method: "POST", body: data, redirect: "manual"}).then(function (response) {
            if (response.type === "opaqueredirect") {
                location.reload();
                return null;
            }
            return response.json();
        }).catch(function () {
            return {error: dialog.dataset.failed};
        });
    }

    function show(answer) {
        error.textContent = answer.error || "";
        error.classList.toggle("d-none", !answer.error);
        var lines = answer.diff || [];
        same.classList.toggle("d-none", Boolean(answer.error) || lines.length > 0);
        save.classList.toggle("d-none", lines.length === 0);
        save.disabled = false;
        diff.replaceChildren();
        // skip the two file header lines; + added, - removed, @@ where
        lines.slice(2).forEach(function (line) {
            var row = document.createElement("div");
            row.textContent = line;
            row.className = {"+": "text-success", "-": "text-danger", "@": "text-body-secondary"}[line[0]] || "";
            diff.appendChild(row);
        });
        diff.classList.toggle("d-none", lines.length === 0);
    }

    form.addEventListener("submit", function (event) {
        event.preventDefault();
        reviewed = editor.getValue();
        post(reviewed, false).then(function (answer) {
            if (answer) {
                show(answer);
                modal.show();
            }
        });
    });

    save.addEventListener("click", function () {
        save.disabled = true;
        post(reviewed, true).then(function (answer) {
            if (answer && answer.saved) {
                location.hash = "xmledit";
                location.reload();
            } else if (answer) {
                show({error: answer.error, diff: []});
            }
        });
    });
})();
