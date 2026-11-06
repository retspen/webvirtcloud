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

// A list a page loads (jQuery) that the server could not give: its error goes
// with the page's messages. A load a newer one aborted has none.
function showLoadError(xhr) {
  const text = (xhr.responseJSON || {}).error;
  if (!text) return;
  const alert = document.createElement("div");
  alert.className = "alert alert-danger";
  alert.setAttribute("role", "alert");
  alert.textContent = text;
  document.querySelector("#messages").append(alert);
}
window.showLoadError = showLoadError;
