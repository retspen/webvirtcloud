// After a refused submission, start at the error. The places an error
// can be, most specific first: a refused field, its form's summary, an
// open dialog's copy of the messages (the page's are behind it), the
// page's messages. A page that sets itself up first has
// data-error-focus="manual" and calls this when it is ready.
const ERROR_PLACES = [".is-invalid", ".form-errors", ".modal.show .modal-messages .alert-danger",
                      "#messages .alert-danger"];

function focusFirstError() {
  for (const selector of ERROR_PLACES) {
    const target = [...document.querySelectorAll(selector)].find(e => e.offsetParent !== null);
    if (target) {
      if (!target.matches("input, select, textarea")) target.tabIndex = -1;
      target.focus();
      return;
    }
  }
}
window.focusFirstError = focusFirstError;
if (document.body.dataset.errorFocus !== "manual") focusFirstError();
