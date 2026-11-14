"""After a refused submission the page starts at the error: error_focus.js
focuses the first visible invalid field, else the error message.
The script runs in Node against a stand-in document."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from django.conf import settings

SCRIPT = Path(settings.BASE_DIR, "static/js/error_focus.js").read_text()

HARNESS = """
const els = %s;
let focused = null;
for (const e of els) { e.focus = () => { focused = e; }; e.matches = () => Boolean(e.field); }
const document = {
  body: {dataset: %s},
  querySelectorAll: sel => els.filter(e => e.sel === sel),
};
const window = globalThis;
%s
if (%s) window.focusFirstError();
console.log(JSON.stringify({focused: focused && focused.name, tabIndex: focused && focused.tabIndex !== undefined ? focused.tabIndex : null}));
"""


class ErrorFocusTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def focused(self, els, dataset=None, call=False):
        script = HARNESS % (json.dumps(els), json.dumps(dataset or {}), SCRIPT, "true" if call else "false")
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_focus_goes_to_the_error(self):
        invalid = {"sel": ".is-invalid", "offsetParent": {}, "name": "field", "field": True}
        hidden = {"sel": ".is-invalid", "offsetParent": None, "name": "hidden", "field": True}
        summary = {"sel": ".form-errors", "offsetParent": {}, "name": "summary"}
        alert = {"sel": "#messages .alert-danger", "offsetParent": {}, "name": "message"}
        in_modal = {"sel": ".modal.show .modal-messages .alert-danger", "offsetParent": {}, "name": "modal message"}
        for els, expected in (
            ([hidden, invalid, summary, alert], {"focused": "field", "tabIndex": None}),
            ([hidden, summary, in_modal, alert], {"focused": "summary", "tabIndex": -1}),  # a hidden field's error
            ([hidden, alert], {"focused": "message", "tabIndex": -1}),
            ([hidden, in_modal, alert], {"focused": "modal message", "tabIndex": -1}),  # the page's copy is behind the dialog
            ([], {"focused": None, "tabIndex": None}),
        ):
            with self.subTest(expected=expected["focused"]):
                self.assertEqual(self.focused(els), expected)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_a_page_can_focus_the_error_itself(self):
        invalid = {"sel": ".is-invalid", "offsetParent": {}, "name": "field", "field": True}
        self.assertEqual(self.focused([invalid], {"errorFocus": "manual"}), {"focused": None, "tabIndex": None})
        self.assertEqual(self.focused([invalid], {"errorFocus": "manual"}, call=True), {"focused": "field", "tabIndex": None})

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_a_list_the_server_could_not_give_says_why_with_the_page_s_messages(self):
        script = ("const added = []; const messages = {append: e => added.push(e)};"
                  "const document = {body: {dataset: {errorFocus: 'manual'}}, querySelector: () => messages,"
                  " createElement: () => ({setAttribute(k, v) { this[k] = v; }})}; const window = globalThis;"
                  + SCRIPT +
                  "showLoadError({responseJSON: {error: 'Cannot recv data'}}); showLoadError({status: 0});"
                  "console.log(JSON.stringify(added.map(e => [e.className, e.role, e.textContent])));")
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        # an aborted load (no answer) adds nothing
        self.assertEqual(json.loads(result.stdout), [["alert alert-danger", "alert", "Cannot recv data"]])
