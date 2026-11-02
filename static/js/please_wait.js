// The please-wait dialog (pleasewaitdialog.html) of a page that submits a long request.
function showPleaseWaitDialog() {
    var pleaseModal = new bootstrap.Modal(document.getElementById('pleaseWaitDialog'), {
        keyboard: false
    });
    pleaseModal.show();
    backgroundJobRunning = true;
}
function hidePleaseWaitDialog() {
    var pleaseModal = new bootstrap.Modal(document.getElementById('pleaseWaitDialog'), {
        keyboard: false
    })
    pleaseModal.hide();
    backgroundJobRunning = false;
}
