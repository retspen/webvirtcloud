// A form sent to the server shows it: the button that sent it turns a spinner
// and takes no second click until the answer comes; a page's reload or a job's
// result waits meanwhile (poll.js pageInUse). It is as before when the page
// stays: its leaving asked about unsaved work (an XML edit, an ISO upload) or
// the browser's history brings it back. A form a script sends itself (it
// prevents the submit) is left as it is.
function submitBusyEnd() {
    document.querySelectorAll("button[data-busy]").forEach(function (button) {
        button.disabled = false;
        delete button.dataset.busy;
        button.querySelectorAll("[data-busy-spinner]").forEach(function (spinner) { spinner.remove(); });
    });
}
var submitLeaveAsked = false;
document.addEventListener("submit", function (event) {
    var button = event.submitter;
    if (event.target.method !== "post" || !button || button.tagName !== "BUTTON") return;
    // after the submit: the form's data, which has the button's name and value, is taken by then
    setTimeout(function () {
        if (event.defaultPrevented || submitLeaveAsked) {
            submitLeaveAsked = false;
            return;
        }
        button.disabled = true;
        button.dataset.busy = "1";
        button.insertAdjacentHTML("afterbegin", '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true" data-busy-spinner></span>');
    }, 0);
});
// after the page's own handlers (they are added as it loads): one asks before leaving
window.addEventListener("load", function () {
    window.addEventListener("beforeunload", function (event) {
        if (event.defaultPrevented) {
            submitLeaveAsked = true;
            submitBusyEnd();
        }
    });
});
window.addEventListener("pageshow", function (event) {
    if (event.persisted) submitBusyEnd();
});
