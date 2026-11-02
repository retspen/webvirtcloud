// A link marked data-history-back goes back to the previous page.
document.addEventListener("click", function (event) {
    if (event.target.closest("[data-history-back]")) {
        event.preventDefault();
        history.back();
    }
});
