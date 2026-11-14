from django.urls import include, path
from rest_framework_nested import routers

from computes.api.viewsets import ComputeArchitecturesView, ComputeViewSet
from networks.api.viewsets import NetworkViewSet
from interfaces.api.viewsets import InterfaceViewSet
from operations.api.viewsets import OperationViewSet
from storages.api.viewsets import StorageViewSet, VolumeViewSet
from instances.api.viewsets import FlavorViewSet, \
                                    InstancesViewSet, \
                                    InstanceViewSet, \
                                    MigrateViewSet, \
                                    CreateInstanceViewSet


router = routers.SimpleRouter(use_regex_path=False)
router.register(r'computes', ComputeViewSet)
router.register(r'migrate', MigrateViewSet, basename='instance-migrate')
router.register(r'flavor', FlavorViewSet, basename='instance-flavor')
router.register(r'instances', InstancesViewSet, basename='instance')
router.register(r'operations', OperationViewSet, basename='operation')

compute_router = routers.NestedSimpleRouter(router, r'computes', lookup='compute', use_regex_path=False)
compute_router.register(r'instances', InstanceViewSet, basename='compute-instance')
compute_router.register('instances/create/<str:arch>/<str:machine>', CreateInstanceViewSet, basename='instance-create')
compute_router.register(r'networks', NetworkViewSet, basename='compute-network')
compute_router.register(r'interfaces', InterfaceViewSet, basename='compute-interface')
compute_router.register(r'storages', StorageViewSet, basename='compute-storage')
compute_router.register(r'archs', ComputeArchitecturesView, basename='compute-archs')

storage_router = routers.NestedSimpleRouter(compute_router, r'storages', lookup='storage', use_regex_path=False)
storage_router.register(r'volumes', VolumeViewSet, basename='compute-storage-volumes')


urlpatterns = [
    path('', include(router.urls)),
    path('', include(compute_router.urls)),
    path('', include(storage_router.urls)),
]
