function filter_table() {
    var rex = new RegExp($(this).val(), 'i');
    $('.searchable tr').hide();
    $('.searchable tr').filter(function () {
        return rex.test($(this).text());
    }).show();
    Cookies.set("instances_filter", $(this).val(), { expires: 1 });
}
$(document).ready(function () {
    instances_filter_cookie = Cookies.get("instances_filter");
    if (instances_filter_cookie) {
        $('#filter').val(instances_filter_cookie);
        $('#filter').each(filter_table);
    }
    (function ($) {
        $('#filter').keyup(filter_table)
    }(jQuery));
});
