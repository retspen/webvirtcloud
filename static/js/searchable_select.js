// A <select data-searchable> of many users or VMs gets a search box (Tom Select).
document.querySelectorAll("select[data-searchable]").forEach(function (select) {
    new TomSelect(select, {
        // the box leaves its focused, taller look at once: else the next tap's
        // button moves away under the finger on a phone
        onItemAdd: function () { this.blur(); },
    });
});
