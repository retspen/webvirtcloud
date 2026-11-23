// A form's storage pool field (data-pools: compute 0's pool list, vmbackups.views.pools) offers
// the pools of the compute chosen in the same form. A name can still be typed: the server checks it
// as before. An answer for a compute no longer chosen is left out.
document.querySelectorAll("input[data-pools]").forEach(function (input) {
    var compute = input.form.elements.compute;
    if (!compute) return;
    var list = document.createElement("datalist");
    list.id = input.id + "-choices";
    input.after(list);
    input.setAttribute("list", list.id);
    input.setAttribute("autocomplete", "off");
    function offer() {
        var asked = compute.value;
        list.replaceChildren();
        if (!asked) return;
        $.getJSON(input.dataset.pools.replace("/0/", "/" + encodeURIComponent(asked) + "/")).done(function (pools) {
            if (compute.value !== asked) return;
            list.replaceChildren.apply(list, pools.map(function (pool) { return new Option(pool.name); }));
        });
    }
    compute.addEventListener("change", offer);
    offer();
});
