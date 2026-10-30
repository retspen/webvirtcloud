// The VM page's XML editor. Review changes shows the lines the edit changes
// in the VM's definition (instances.views.change_xml), and Save in that dialog
// defines it. A refusal shows in the dialog, and the edit stays in the editor.
// An edit not saved yet keeps the page from reloading itself on a VM state
// change (window.xmlEditUnsaved), and the browser asks before leaving it.
(function () {
    var form = document.getElementById("xml-form");
    if (!form) {
        return; // the editor exists only for superusers
    }
    var editor = ace.edit("editor");
    editor.getSession().setMode("ace/mode/xml");
    var base = editor.getValue(); // the definition the editor opened with
    var dialog = document.getElementById("xml-review");
    var modal = bootstrap.Modal.getOrCreateInstance(dialog);
    var error = document.getElementById("xml-review-error");
    var same = document.getElementById("xml-review-same");
    var diff = document.getElementById("xml-review-diff");
    var save = document.getElementById("xml-review-save");
    var reviewed = ""; // Save defines the XML the dialog shows, not later edits
    var clean = base; // the XML the page has: the opened definition, or the one Save just defined

    window.xmlEditUnsaved = function () {
        return editor.getValue() !== clean;
    };
    window.addEventListener("beforeunload", function (event) {
        if (window.xmlEditUnsaved()) {
            event.preventDefault();
        }
    });
    dialog.addEventListener("hidden.bs.modal", function () {
        editor.focus();
    });

    // The answer: diff, saved, or error (detail when the VM is busy or moved).
    // Any other failure, such as a redirect, keeps the edit and says so.
    function post(xml, confirm) {
        var data = new FormData(form);
        data.set("inst_xml", xml);
        data.set("base", base);
        if (confirm) {
            data.set("confirm", "1");
        }
        return fetch(form.action, {
            method: "POST", body: data, redirect: "manual", headers: {"X-Requested-With": "XMLHttpRequest"},
        }).then(function (response) {
            return response.json();
        }).then(function (answer) {
            return {diff: answer.diff, saved: answer.saved, error: answer.error || answer.detail};
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
        var xml = editor.getValue();
        // the last answer shown is the one Save sends, whatever order answers come in
        post(xml, false).then(function (answer) {
            reviewed = xml;
            show(answer);
            modal.show();
        });
    });

    save.addEventListener("click", function () {
        save.disabled = true;
        post(reviewed, true).then(function (answer) {
            if (answer.saved) {
                clean = reviewed;
                location.hash = "xmledit";
                location.reload();
            } else {
                // the diff stays, and Save can be tried again
                error.textContent = answer.error;
                error.classList.remove("d-none");
                save.disabled = false;
            }
        });
    });
})();
