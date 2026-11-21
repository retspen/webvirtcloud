// A session that ends while the page is open: a script's request is answered 401
// (webvirtcloud.middleware.LoginRequiredMiddleware). sessionEnd() says so, with a link to sign
// in and come back here, and the page stops asking and reloading (poll.js, pageInUse): what it
// shows is no longer updated. A jQuery request's 401 calls it; a fetch's caller does. Gives
// the words it shows.
function sessionEnd() {
    var notice = document.getElementById("session-ended");
    if (notice && !window.sessionEnded) {
        window.sessionEnded = true;
        var link = document.createElement("a");
        link.className = "alert-link";
        link.href = notice.dataset.href;
        link.textContent = notice.dataset.link;
        notice.className = "alert alert-warning";
        notice.setAttribute("role", "alert");
        notice.replaceChildren(notice.dataset.text + " ", link);
        notice.hidden = false;
    }
    return notice ? notice.dataset.text : "";
}
$(document).ajaxError(function (event, xhr) {
    if (xhr.status === 401) {
        sessionEnd();
    }
});
