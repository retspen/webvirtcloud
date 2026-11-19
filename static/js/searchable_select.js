// A <select data-searchable> of many users or VMs gets a search box (Tom Select).
document.querySelectorAll("select[data-searchable]").forEach(function (select) {
    new TomSelect(select, {
        // the box leaves its focused, taller look at once: else the next tap's
        // button moves away under the finger on a phone
        onItemAdd: function () { this.blur(); },
    });
});

// A <select multiple data-tags>: the tags there are, and a new one typed (the
// server checks it) of at most 12 characters (computes.models.TAG_LENGTH), as
// the tags are kept: without the spaces a paste brings, in lower case ("Prod"
// is "prod"). A name that cannot be a tag gets the rule (data-rule), not silence.
function tagName(input) {
    return input.trim().toLowerCase();
}
function isTagName(input) {
    return /^[a-z0-9][a-z0-9._-]{0,11}$/.test(tagName(input));
}
document.querySelectorAll("select[data-tags]").forEach(function (select) {
    new TomSelect(select, {
        create: function (input) {
            return {value: tagName(input), text: tagName(input)};
        },
        createFilter: function (input) {
            return isTagName(input) && !Object.hasOwn(this.options, tagName(input));
        },
        persist: false,
        render: {
            // the page's own words (data-add, data-rule): the library's are English
            option_create: function (data, escape) {
                return '<div class="create">' + escape(select.dataset.add.replace("%(tag)s", tagName(data.input))) + "</div>";
            },
            no_results: function (data, escape) {
                return isTagName(data.input) ? null : '<div class="no-results">' + escape(select.dataset.rule) + "</div>";
            },
        },
    });
});
