from django.urls import path

from . import views

urlpatterns = [
    path("groups/", views.group_list, name="group_list"),
    path("groups/create/", views.group_create, name="group_create"),
    path("groups/<int:pk>/update/", views.group_update, name="group_update"),
    path("groups/<int:pk>/delete/", views.group_delete, name="group_delete"),
    path("users/", views.user_list, name="user_list"),
    path("users/create/", views.user_create, name="user_create"),
    path("users/<int:pk>/update_password/", views.user_update_password, name="user_update_password"),
    path("users/<int:pk>/update/", views.user_update, name="user_update"),
    path("users/<int:pk>/delete/", views.user_delete, name="user_delete"),
    path("users/<int:pk>/block/", views.user_block, name="user_block"),
    path("users/<int:pk>/unblock/", views.user_unblock, name="user_unblock"),
    path("logs/", views.logs, name="logs"),
]
