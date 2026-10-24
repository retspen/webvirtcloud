// Every table marked data-sortable sorts by a click on, or Enter in, a column
// header (tablesort.min.js). Each table body sorts on its own; a row or
// header with data-sort-method="none" stays where it is.
document.querySelectorAll("table[data-sortable]").forEach(function (table) {
    new Tablesort(table);
});
