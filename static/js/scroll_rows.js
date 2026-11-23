// A row of tabs or sections that scrolls sideways on a phone (overflow-x-auto)
// keeps its current item in sight: centred in the row, the page stays put.
(function () {
    function centre(item) {
        var row = item.closest(".overflow-x-auto");
        if (!row) return;
        var box = row.getBoundingClientRect(), own = item.getBoundingClientRect();
        row.scrollLeft += own.left - box.left - (box.width - own.width) / 2;
    }
    document.addEventListener("shown.bs.tab", function (event) { centre(event.target); });
    document.querySelectorAll(".overflow-x-auto [aria-current]").forEach(centre);
})();
