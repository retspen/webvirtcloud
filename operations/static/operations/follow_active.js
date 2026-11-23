// Reloads the page while it shows an active job, so the page follows the job to its end.
setInterval(function () {
    // not while a form is filled in or a dialog asks (a job's Cancel); a page whose session
    // ended stays as it is: a 401 to its job panel said so (session_end.js)
    if (!document.hidden && !window.sessionEnded && !document.querySelector("form :focus, .modal.show")) {
        window.location.reload();
    }
}, 5000);
