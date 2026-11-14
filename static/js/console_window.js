// A console button (data-url, data-window) opens the console in one window
// per VM: opening it again reloads that window.
document.addEventListener("click", function (event) {
    var button = event.target.closest("button[data-window]");
    if (button) window.open(button.dataset.url, button.dataset.window, "width=850,height=650");
});
