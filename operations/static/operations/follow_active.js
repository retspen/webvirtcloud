// Reloads the page while it shows an active job, so the page follows the job to its end.
setInterval(function () {
    if (!document.hidden && !document.querySelector("form :focus")) {
        window.location.reload();
    }
}, 5000);
