// A <select data-searchable> of many users or VMs gets a search box (Tom Select).
document.querySelectorAll("select[data-searchable]").forEach(function (select) {
    new TomSelect(select, {
        // the box leaves its focused, taller look at once: else the next tap's
        // button moves away under the finger on a phone
        onItemAdd: function () { this.blur(); },
    });
});

// A <select multiple data-tags>: the tags there are, and a new one typed (the
// server checks it), in lower case as the tags are kept: "Prod" is "prod".
document.querySelectorAll("select[data-tags]").forEach(function (select) {
    new TomSelect(select, {
        create: function (input) {
            return {value: input.toLowerCase(), text: input.toLowerCase()};
        },
        createFilter: function (input) {
            return /^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$/.test(input) && !this.options[input.toLowerCase()];
        },
        persist: false,
        render: {
            // the page's own words (data-add): the library's are English
            option_create: function (data, escape) {
                return '<div class="create">' + escape(select.dataset.add.replace("%(tag)s", data.input)) + "</div>";
            },
            no_results: null,
        },
    });
});
