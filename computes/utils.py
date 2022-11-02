from instances.models import Instance


def refresh_instance_database(compute):
    domains = compute.proxy.wvm.listAllDomains()
    domain_names = [d.name() for d in domains]
    domain_uuids = [d.UUIDString() for d in domains]
    # Delete instances that're not on host from DB
    Instance.objects.filter(compute=compute).exclude(name__in=domain_names).delete()
    Instance.objects.filter(compute=compute).exclude(uuid__in=domain_uuids).delete()
    # Create instances that're on host but not in DB
    names = Instance.objects.filter(compute=compute).values_list("name", flat=True)
    for domain in domains:
        if domain.name() not in names:
            Instance(
                compute=compute, name=domain.name(), uuid=domain.UUIDString()
            ).save()
