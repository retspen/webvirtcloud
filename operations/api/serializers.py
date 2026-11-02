from datetime import timedelta

from django.utils import timezone
from django.utils.translation import gettext as _
from rest_framework import serializers

from operations.jobs import KINDS, label_of
from operations.models import Operation
from operations.utils import shown_label, words


class OperationSerializer(serializers.ModelSerializer):
    label = serializers.SerializerMethodField()
    phase = serializers.SerializerMethodField()
    error = serializers.SerializerMethodField()
    result = serializers.SerializerMethodField()
    resource_label = serializers.SerializerMethodField()
    cancellable = serializers.SerializerMethodField()
    in_request = serializers.SerializerMethodField()

    class Meta:
        model = Operation
        fields = ["id", "kind", "label", "username", "resource", "resource_label", "state", "phase",
                  "progress_done", "progress_total", "result", "error", "created_at", "started_at",
                  "finished_at", "cancel_requested", "cancellable", "in_request", "resolution", "resolution_note"]
        read_only_fields = fields

    def get_label(self, op) -> str:
        return str(_(label_of(op.kind)))

    def get_phase(self, op) -> str:
        """The phase in the viewer's language; a job running past its time
        limit says so (one that can be cancelled is cancelled instead)."""
        phase = _(op.phase) if op.phase else ""
        if op.state == Operation.RUNNING and op.time_limit and op.started_at \
                and timezone.now() - op.started_at > timedelta(seconds=op.time_limit):
            return (_("%(phase)s (over its time limit)") % {"phase": phase}).strip()
        return phase

    def get_error(self, op) -> str:
        return words(op.error)

    def get_result(self, op) -> dict:
        """What the job made; its warning in the viewer's language."""
        if op.result.get("warning"):
            return {**op.result, "warning": words(op.result["warning"])}
        return op.result

    def get_resource_label(self, op) -> str:
        return shown_label(op, self.context["request"].user)

    def get_cancellable(self, op) -> bool:
        kind = KINDS.get(op.kind)
        return op.state == Operation.QUEUED or bool(kind and kind.cancellable and op.state == Operation.RUNNING)

    def get_in_request(self, op) -> bool:
        """A request runs it: it does not wait for the worker."""
        return op.in_request


class OperationSummarySerializer(serializers.Serializer):
    kind = serializers.CharField()
    label = serializers.CharField()
    state = serializers.CharField()
    since = serializers.DateTimeField()


class ResourceJobsSerializer(serializers.Serializer):
    jobs = OperationSerializer(many=True)
    others = OperationSummarySerializer(many=True)
    short_operation = serializers.BooleanField()
    worker_last_seen = serializers.DateTimeField(allow_null=True)
