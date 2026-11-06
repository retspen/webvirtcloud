// The please-wait dialog (pleasewaitdialog.html) of a page that submits a long request.
function showPleaseWaitDialog() {
    var pleaseModal = new bootstrap.Modal(document.getElementById('pleaseWaitDialog'), {
        keyboard: false
    });
    pleaseModal.show();
    backgroundJobRunning = true;
}
// a form marked data-please-wait shows the dialog while it is sent
document.addEventListener("submit", function (event) {
    if (event.target.matches("form[data-please-wait]")) showPleaseWaitDialog();
});
