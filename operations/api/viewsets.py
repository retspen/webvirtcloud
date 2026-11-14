from django.http import Http404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from operations import jobs
from operations.models import Claim, Operation, last_seen, worker_gone
from operations.utils import may_see, summary, visible

from .serializers import OperationSerializer, ResourceJobsSerializer

SHOWN_STATES = Operation.ACTIVE + (Operation.UNCERTAIN,)


class Pages(PageNumberPagination):
    page_size = 50


class OperationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = OperationSerializer
    pagination_class = Pages

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # schema generation has no user
            return Operation.objects.none()
        user = self.request.user
        qs = Operation.objects.all() if user.is_superuser else Operation.objects.filter(user=user)
        fields = ("state", "kind", "resource", "username") if user.is_superuser else ("state", "kind", "resource")
        for field in fields:
            if value := self.request.query_params.get(field):
                qs = qs.filter(**{field: value})
        return qs

    @extend_schema(request=None, responses=OperationSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        op = self.get_object()
        return Response(OperationSerializer(jobs.cancel(op.pk, request.user), context={"request": request}).data)

    @extend_schema(parameters=[OpenApiParameter("key", str, required=True)], responses=ResourceJobsSerializer)
    @action(detail=False, methods=["get"])
    def resource(self, request):
        key = request.query_params.get("key", "")
        if not key:
            raise ValidationError({"key": "required"})
        if not visible(request.user, key):
            raise Http404
        active = list(Operation.objects.filter(claims__resource=key, state__in=SHOWN_STATES).distinct())
        mine = [op for op in active if may_see(op, request.user)]
        others = [summary(op, request.user) for op in active if not may_see(op, request.user)]
        seen = last_seen()
        short = Claim.objects.filter(resource=key, operation__isnull=True, expires_at__gt=timezone.now()).exists()
        return Response(ResourceJobsSerializer(
            {"jobs": mine, "others": others, "short_operation": short, "worker_last_seen": seen,
             "worker_gone": worker_gone(seen)},
            context={"request": request}).data)
