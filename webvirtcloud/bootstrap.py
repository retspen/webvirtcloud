"""django-bootstrap5's field renderer, marking only the fields in error."""

from django_bootstrap5.renderers import FieldRenderer as BootstrapFieldRenderer


class FieldRenderer(BootstrapFieldRenderer):
    """A sent form marks its fields in error red and leaves the others as
    they were: a green "valid" mark on a form that was not saved reads as if
    it had been."""

    def get_server_side_validation_classes(self):
        return "is-invalid" if self.field_errors else ""
