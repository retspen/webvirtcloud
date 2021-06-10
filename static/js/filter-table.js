function filter_table() {
    var rex = new RegExp($(this).val(), 'i');
    $('.searchable tr').hide();
    $('.searchable tr').filter(function () {
        return rex.test($(this).text());
    }).show();
    Cookies.set(document.title + "_filter", $(this).val(), { expires: 1 });
}
$(document).ready(function () {
    filter_cookie = Cookies.get(document.title + "_filter");
    if (filter_cookie) {
        $('#filter').val(filter_cookie);
        $('#filter').each(filter_table);
    }
    (function ($) {
        $('#filter').keyup(filter_table)
    }(jQuery));
});
