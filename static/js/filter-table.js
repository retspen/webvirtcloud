function filter_table() {
    var rex = new RegExp($(this).val(), 'i');
    $('.searchable tr').hide();
    $('.searchable tr').filter(function () {
        return rex.test($(this).text());
    }).show();
}
$(document).ready(function () {
    (function ($) {
        $('#filter').keyup(filter_table)
    }(jQuery));
});
