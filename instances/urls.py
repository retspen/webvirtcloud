from django.urls import path

from . import views

app_name = "instances"

urlpatterns = [
    path("", views.index, name="index"),
    path("flavor/create/", views.flavor_create, name="flavor_create"),
    path("flavor/<int:pk>/update/", views.flavor_update, name="flavor_update"),
    path("flavor/<int:pk>/delete/", views.flavor_delete, name="flavor_delete"),
    path("<int:pk>/", views.instance, name="instance"),
    path("<int:pk>/poweron/", views.poweron, name="poweron"),
    path("<int:pk>/powercycle/", views.powercycle, name="powercycle"),
    path("<int:pk>/poweroff/", views.poweroff, name="poweroff"),
    path("<int:pk>/suspend/", views.suspend, name="suspend"),
    path("<int:pk>/resume/", views.resume, name="resume"),
    path("<int:pk>/force_off/", views.force_off, name="force_off"),
    path("<int:pk>/destroy/", views.destroy, name="destroy"),
    path("<int:pk>/migrate/", views.migrate, name="migrate"),
    path("<int:pk>/status/", views.status, name="status"),
    path("<int:pk>/stats/", views.stats, name="stats"),
    path("<int:pk>/osinfo/", views.osinfo, name="osinfo"),
    path("<int:pk>/rootpasswd/", views.set_root_pass, name="rootpasswd"),
    path("<int:pk>/add_public_key/", views.add_public_key, name="add_public_key"),
    path("<int:pk>/resizevm_cpu/", views.resizevm_cpu, name="resizevm_cpu"),
    path("<int:pk>/resize_memory/", views.resize_memory, name="resize_memory"),
    path("<int:pk>/resize_disk/", views.resize_disk, name="resize_disk"),
    path("<int:pk>/add_new_vol/", views.add_new_vol, name="add_new_vol"),
    path("<int:pk>/delete_vol/", views.delete_vol, name="delete_vol"),
    path("<int:pk>/add_owner/", views.add_owner, name="add_owner"),
    path("<int:pk>/add_existing_vol/", views.add_existing_vol, name="add_existing_vol"),
    path("<int:pk>/edit_volume/", views.edit_volume, name="edit_volume"),
    path("<int:pk>/detach_vol/", views.detach_vol, name="detach_vol"),
    path("<int:pk>/add_cdrom/", views.add_cdrom, name="add_cdrom"),
    path("<int:pk>/detach_cdrom/<str:dev>/", views.detach_cdrom, name="detach_cdrom"),
    path("<int:pk>/unmount_iso/", views.unmount_iso, name="unmount_iso"),
    path("<int:pk>/mount_iso/", views.mount_iso, name="mount_iso"),
    path("<int:pk>/snapshot/", views.snapshot, name="snapshot"),
    path("<int:pk>/delete_snapshot/", views.delete_snapshot, name="delete_snapshot"),
    path("<int:pk>/revert_snapshot/", views.revert_snapshot, name="revert_snapshot"),
    path("<int:pk>/create_external_snapshot/", views.create_external_snapshot, name="create_external_snapshot"),
    path("<int:pk>/revert_external_snapshot/", views.revert_external_snapshot, name="revert_external_snapshot"),
    path("<int:pk>/delete_external_snapshot/", views.delete_external_snapshot, name="delete_external_snapshot"),
    path("<int:pk>/set_vcpu/", views.set_vcpu, name="set_vcpu"),
    path("<int:pk>/set_vcpu_hotplug/", views.set_vcpu_hotplug, name="set_vcpu_hotplug"),
    path("<int:pk>/set_autostart/", views.set_autostart, name="set_autostart"),
    path("<int:pk>/unset_autostart/", views.unset_autostart, name="unset_autostart"),
    path("<int:pk>/set_bootmenu/", views.set_bootmenu, name="set_bootmenu"),
    path("<int:pk>/unset_bootmenu/", views.unset_bootmenu, name="unset_bootmenu"),
    path("<int:pk>/set_bootorder/", views.set_bootorder, name="set_bootorder"),
    path("<int:pk>/change_xml/", views.change_xml, name="change_xml"),
    path("<int:pk>/set_guest_agent/", views.set_guest_agent, name="set_guest_agent"),
    path("<int:pk>/set_video_model/", views.set_video_model, name="set_video_model"),
    path("<int:pk>/change_network/", views.change_network, name="change_network"),
    path("<int:pk>/add_network/", views.add_network, name="add_network"),
    path("<int:pk>/delete_network/", views.delete_network, name="delete_network"),
    path("<int:pk>/set_link_state/", views.set_link_state, name="set_link_state"),
    path("<int:pk>/set_qos/", views.set_qos, name="set_qos"),
    path("<int:pk>/unset_qos/", views.unset_qos, name="unset_qos"),
    path(
        "<int:pk>/del_owner/", views.del_owner, name="del_owner"
    ),  # no links to this one???
    path("<int:pk>/clone/", views.clone, name="clone"),
    path("<int:pk>/update_console/", views.update_console, name="update_console"),
    path("<int:pk>/change_options/", views.change_options, name="change_options"),
    path(
        "<int:pk>/getvvfile/", views.getvvfile, name="getvvfile"
    ),  # no links to this one???
    path(
        "create/<int:compute_id>/",
        views.create_instance_select_type,
        name="create_instance_select_type",
    ),
    path(
        "create/<int:compute_id>/<str:arch>/<str:machine>/",
        views.create_instance,
        name="create_instance",
    ),
    path(
        "guess_mac_address/<vname>/", views.guess_mac_address, name="guess_mac_address"
    ),
    path("guess_clone_name/", views.guess_clone_name, name="guess_clone_name"),
    path("random_mac_address/", views.random_mac_address, name="random_mac_address"),
    path("check_instance/<vname>/", views.check_instance, name="check_instance"),
    path("<int:pk>/sshkeys/", views.sshkeys, name="sshkeys"),
]
