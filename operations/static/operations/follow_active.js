// Reloads the page while it shows an active job, so the page follows the job to its end.
setInterval(function () {
    // not while a form is filled in or a dialog asks (a job's Cancel)
    if (!document.hidden && !document.querySelector("form :focus, .modal.show")) {
        window.location.reload();
    }
}, 5000);
