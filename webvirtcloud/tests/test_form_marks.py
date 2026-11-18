"""A rejected form marks its fields in error, not the others: a green
"valid" mark beside a form that was not saved reads as if it were."""

from django import forms
from django.template import Context, Template
from django.test import SimpleTestCase


class ExampleForm(forms.Form):
    name = forms.CharField()
    size = forms.IntegerField()


class FormMarksTestCase(SimpleTestCase):
    def render(self, form):
        return Template("{% load django_bootstrap5 %}{% bootstrap_form form %}").render(Context({"form": form}))

    def test_only_fields_in_error_are_marked(self):
        html = self.render(ExampleForm({"name": "ok", "size": "x"}))
        self.assertIn("is-invalid", html)
        self.assertNotIn("is-valid", html.replace("is-invalid", ""))

    def test_a_form_not_sent_is_not_marked(self):
        html = self.render(ExampleForm())
        self.assertNotIn("is-invalid", html)
        self.assertNotIn("is-valid", html)
