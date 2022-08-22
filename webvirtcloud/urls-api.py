from django.urls import include, path
from rest_framework_nested import routers

from computes.api.viewsets import ComputeArchitecturesView, ComputeViewSet
from networks.api.viewsets import NetworkViewSet
from interfaces.api.viewsets import InterfaceViewSet
from storages.api.viewsets import StorageViewSet, VolumeViewSet
from instances.api.viewsets import FlavorViewSet, \
                                    InstancesViewSet, \
                                    InstanceViewSet, \
                                    MigrateViewSet, \
                                    CreateInstanceViewSet


router = routers.SimpleRouter()
router.register(r'computes', ComputeViewSet)
router.register(r'migrate', MigrateViewSet, basename='instance-migrate')
router.register(r'flavor', FlavorViewSet, basename='instance-flavor')
router.register(r'instances', InstancesViewSet, basename='instance')

compute_router = routers.NestedSimpleRouter(router, r'computes', lookup='compute')
compute_router.register(r'instances', InstanceViewSet, basename='compute-instance')
compute_router.register(r'instances/create/(?P<arch>[^/.]+)/(?P<machine>[^/.]+)', CreateInstanceViewSet, basename='instance-create')
compute_router.register(r'networks', NetworkViewSet, basename='compute-network')
compute_router.register(r'interfaces', InterfaceViewSet, basename='compute-interface')
compute_router.register(r'storages', StorageViewSet, basename='compute-storage')
compute_router.register(r'archs', ComputeArchitecturesView, basename='compute-archs')

storage_router = routers.NestedSimpleRouter(compute_router, r'storages', lookup='storage')
storage_router.register(r'volumes', VolumeViewSet, basename='compute-storage-volumes')


urlpatterns = [
    path('', include(router.urls)),
    path('', include(compute_router.urls)),
    path('', include(storage_router.urls)),
]
