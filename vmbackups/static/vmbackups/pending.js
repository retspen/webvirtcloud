// A backup being made or deleted: the page reads it again until it is done,
// while the backups are in view (the VM page's Backups tab, the Backups page)
// and nothing is open on them (a menu, a dialog) or being typed into.
(function () {
    if (!document.querySelector("[data-backup-pending]")) return;
    var check = function () {
        var pane = document.getElementById("backups");
        var hidden = pane && pane.classList.contains("tab-pane") && !pane.classList.contains("active");
        var busy = document.querySelector(".dropdown-menu.show, .modal.show, input:focus, select:focus, textarea:focus");
        if (window.sessionEnded) {
            return;  // signed out: the page keeps its notice (session_end.js)
        }
        if (hidden || busy || document.hidden) {
            setTimeout(check, 4000);
        } else {
            location.reload();
        }
    };
    setTimeout(check, 4000);
})();
