// The New pool dialog (create_stg_block.html).
// the ISO pool is a directory named iso; a path follows the pool's name
// until it is edited (after the page's scripts, Bootstrap's among them)
document.addEventListener('DOMContentLoaded', function () {
    var form = document.getElementById('pool-form');
    var name = form.elements.namedItem('name');
    var otherName = name.value;
    var hasCephSecrets = "cephSecrets" in form.dataset;
    form.querySelectorAll('[data-follow-name]').forEach(function (path) {
        path.dataset.derived = name.value ? path.dataset.followName + name.value : '';
    });
    name.addEventListener('input', function () {
        form.querySelectorAll('[data-follow-name]').forEach(function (path) {
            var derived = name.value ? path.dataset.followName + name.value : '';
            if (!path.value || path.value === path.dataset.derived) path.value = derived;
            path.dataset.derived = derived;
        });
    });
    // a new device or name: the erasing is agreed to again
    form.querySelectorAll('#pool_lvm_source, #pool_name').forEach(function (field) {
        field.addEventListener('input', function () { document.getElementById('pool_lvm_erase').checked = false; });
    });
    choiceDialog(document.getElementById('AddStgPool'), 'pool_kind', function (kind) {
        var iso = kind === 'iso';
        if (!name.readOnly) otherName = name.value;
        name.value = iso ? 'iso' : otherName;
        name.readOnly = iso;
        form.elements.namedItem('stg_type').value = iso ? 'dir' : kind;
        form.querySelector('button[name=create]').disabled = kind === 'rbd' && !hasCephSecrets;
    });
});
