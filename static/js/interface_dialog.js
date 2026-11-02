// The New interface dialog (create_iface_block.html).
// a static address's fields show with its choice (after the page's
// scripts, Bootstrap's among them)
document.addEventListener('DOMContentLoaded', function () {
    var form = document.getElementById('interface-form');
    form.querySelectorAll('select[data-static]').forEach(function (method) {
        var fields = form.querySelector(method.dataset.static);
        function show() { fields.hidden = fields.disabled = method.value !== 'static'; }
        method.addEventListener('change', show);
        show();
    });
    choiceDialog(document.getElementById('AddInterface'), 'itype', function () {});
});
