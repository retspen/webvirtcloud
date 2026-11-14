// The VM list grouped by host (allinstances_index_grouped.html): a host's
// VMs collapse under its row. A collapsed host's VM rows are hidden by its
// table body's class, so the search (table_filter.js, the hidden attribute)
// can still hide them too.
function set_host_collapsed(tbody, collapsed) {
    $(tbody).toggleClass('host-collapsed', collapsed);
    $(tbody).find('[aria-controls]').attr('aria-expanded', !collapsed);
    $(tbody).find('.host-chevron').toggleClass('bi-chevron-down', collapsed).toggleClass('bi-chevron-up', !collapsed);
    $(tbody).find('.host-collapsed-badge').toggleClass('d-none', !collapsed);
    // expanded while any host is, as the next click collapses them all
    $('#hide-all-instances').attr('aria-expanded', $('tbody.searchable').not('.host-collapsed').length > 0);
}

// every host the same way: collapsed, unless all already are
$('#hide-all-instances').on('click', function () {
    var bodies = $('tbody.searchable');
    var collapse = bodies.not('.host-collapsed').length > 0;
    bodies.each(function () { set_host_collapsed(this, collapse); });
});

$('.host-toggle').on('click', function () {
    var tbody = $(this).closest('tbody');
    set_host_collapsed(tbody, !tbody.hasClass('host-collapsed'));
});
