from admin.permissions import IsSuperUser
from computes import utils
from computes.models import Compute
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from instances.models import Flavor, Instance
from instances.views import destroy as instance_destroy
from instances.views import (
    force_off,
    get_instance,
    powercycle,
    poweroff,
    poweron,
    resume,
    suspend,
)
from drf_spectacular.utils import extend_schema
from logs.audit import audit, changed_fields, snapshot
from operations import jobs
from operations.api.serializers import OperationSerializer
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from webvirtcloud.serializers import StatusSerializer

from .serializers import (
    CreateInstanceSerializer,
    FlavorSerializer,
    InstanceDetailsSerializer,
    InstanceSerializer,
    MigrateSerializer,
)


def instance_action_response(action, request, pk, message):
    response = action(request, pk)
    if response.status_code >= 400:
        return response
    return Response({"status": message})


class InstancesViewSet(viewsets.ViewSet):
    """
    A simple ViewSet for listing or retrieving ALL/Compute Instances.
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = InstanceSerializer
    lookup_value_converter = "int"

    def list(self, request):

        if request.user.is_superuser or request.user.has_perm(
            "instances.view_instances"
        ):
            queryset = Instance.objects.all().prefetch_related("userinstance_set")
        else:
            queryset = Instance.objects.filter(
                userinstance__user=request.user
            ).prefetch_related("userinstance_set")
        serializer = InstanceSerializer(
            queryset, many=True, context={"request": request}
        )

        return Response(serializer.data)

    def retrieve(self, request, pk=None, compute_pk=None):
        queryset = get_instance(request.user, pk)
        serializer = InstanceSerializer(queryset, context={"request": request})

        return Response(serializer.data)


class InstanceViewSet(viewsets.ViewSet):
    """
    A simple ViewSet for listing or retrieving Compute Instances.
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = InstanceSerializer
    lookup_value_converter = "int"

    def list(self, request, compute_pk=None):
        compute = get_object_or_404(Compute, pk=compute_pk)

        is_admin = request.user.is_superuser or request.user.has_perm(
            "instances.view_instances"
        )

        if not is_admin:
            if not Instance.objects.filter(
                compute=compute, userinstance__user=request.user
            ).exists():
                return Response([])

        utils.refresh_instance_database(compute)

        if is_admin:
            queryset = Instance.objects.filter(compute=compute).prefetch_related(
                "userinstance_set"
            )
        else:
            queryset = Instance.objects.filter(
                compute=compute, userinstance__user=request.user
            ).prefetch_related("userinstance_set")
        serializer = InstanceSerializer(
            queryset, many=True, context={"request": request}
        )

        return Response(serializer.data)

    @extend_schema(responses=InstanceDetailsSerializer)
    def retrieve(self, request, pk=None, compute_pk=None):
        queryset = get_instance(request.user, pk)
        if compute_pk is not None and str(queryset.compute_id) != str(compute_pk):
            raise Http404()
        serializer = InstanceDetailsSerializer(queryset, context={"request": request})

        return Response(serializer.data)

    @extend_schema(responses=StatusSerializer)
    def destroy(self, request, pk=None, compute_pk=None):
        queryset = get_instance(request.user, pk, perm_type="delete")
        if compute_pk is not None and str(queryset.compute_id) != str(compute_pk):
            raise Http404()
        return instance_action_response(instance_destroy, request, pk, "Instance is destroyed")

    @extend_schema(request=None, responses=StatusSerializer)
    @action(detail=True, methods=["post"])
    def poweron(self, request, pk=None, compute_pk=None):
        queryset = get_instance(request.user, pk, perm_type="power")
        if compute_pk is not None and str(queryset.compute_id) != str(compute_pk):
            raise Http404()
        return instance_action_response(poweron, request, pk, "poweron command send")

    @extend_schema(request=None, responses=StatusSerializer)
    @action(detail=True, methods=["post"])
    def poweroff(self, request, pk=None, compute_pk=None):
        queryset = get_instance(request.user, pk, perm_type="power")
        if compute_pk is not None and str(queryset.compute_id) != str(compute_pk):
            raise Http404()
        return instance_action_response(poweroff, request, pk, "poweroff command send")

    @extend_schema(request=None, responses=StatusSerializer)
    @action(detail=True, methods=["post"])
    def powercycle(self, request, pk=None, compute_pk=None):
        queryset = get_instance(request.user, pk, perm_type="power")
        if compute_pk is not None and str(queryset.compute_id) != str(compute_pk):
            raise Http404()
        return instance_action_response(powercycle, request, pk, "powercycle command send")

    @extend_schema(request=None, responses=StatusSerializer)
    @action(detail=True, methods=["post"])
    def forceoff(self, request, pk=None, compute_pk=None):
        queryset = get_instance(request.user, pk, perm_type="power")
        if compute_pk is not None and str(queryset.compute_id) != str(compute_pk):
            raise Http404()
        return instance_action_response(force_off, request, pk, "force off command send")

    @extend_schema(request=None, responses=StatusSerializer)
    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None, compute_pk=None):
        queryset = get_instance(request.user, pk)
        if compute_pk is not None and str(queryset.compute_id) != str(compute_pk):
            raise Http404()
        return instance_action_response(suspend, request, pk, "suspend command send")

    @extend_schema(request=None, responses=StatusSerializer)
    @action(detail=True, methods=["post"])
    def resume(self, request, pk=None, compute_pk=None):
        queryset = get_instance(request.user, pk)
        if compute_pk is not None and str(queryset.compute_id) != str(compute_pk):
            raise Http404()
        return instance_action_response(resume, request, pk, "resume command send")


class MigrateViewSet(viewsets.ViewSet):
    """
    A viewset for migrating instances.
    """

    permission_classes = [IsSuperUser]
    serializer_class = MigrateSerializer
    queryset = ""

    @extend_schema(responses={202: OperationSerializer, 400: dict})
    def create(self, request):
        serializer = MigrateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data
        raw = {"instance": data["instance"].pk, "target": data["target_compute"].pk,
               **{name: data.get(name, False) for name in ("live", "unsafe", "offline", "autoconverge", "compress")}}
        op = jobs.submit("instance.migrate", request.user, raw, data["submission_key"])
        return Response(OperationSerializer(op, context={"request": request}).data, status=status.HTTP_202_ACCEPTED,
                        headers={"Location": reverse("operation-detail", args=[op.pk])})


class FlavorViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows flavor to be viewed or edited.
    """

    queryset = Flavor.objects.all().order_by("id")
    lookup_value_converter = "int"
    serializer_class = FlavorSerializer

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [permissions.IsAuthenticated()]
        return [IsSuperUser()]

    def perform_create(self, serializer):
        with audit(self.request, None, f"Flavor {serializer.validated_data['label']}", "add"):
            serializer.save()

    def perform_update(self, serializer):
        flavor = serializer.instance
        subject, before = f"Flavor {flavor.label}", snapshot(flavor)
        with audit(self.request, None, subject, "change") as entry:
            serializer.save()
            fields = changed_fields(before, snapshot(flavor))
            entry.action = "change " + ", ".join(fields)
            entry.skip = not fields

    def perform_destroy(self, instance):
        with audit(self.request, None, f"Flavor {instance.label}", "delete"):
            instance.delete()


class CreateInstanceViewSet(viewsets.ViewSet):
    """
    A viewset for creating instances.
    """

    permission_classes = [IsSuperUser]
    serializer_class = CreateInstanceSerializer
    queryset = ""

    @extend_schema(responses={202: OperationSerializer, 400: dict})
    def create(self, request, compute_pk=None, arch=None, machine=None):
        serializer = CreateInstanceSerializer(data=request.data,
                                              context={"compute_pk": compute_pk, "arch": arch, "machine": machine})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        data = dict(serializer.validated_data)
        key = data.pop("submission_key")
        op = jobs.submit("instance.create", request.user, {**data, "compute": compute_pk, "arch": arch,
                                                           "machine": machine}, key)
        return Response(OperationSerializer(op, context={"request": request}).data, status=status.HTTP_202_ACCEPTED,
                        headers={"Location": reverse("operation-detail", args=[op.pk])})
