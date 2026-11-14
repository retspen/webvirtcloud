from django.apps import AppConfig


class OperationsConfig(AppConfig):
    name = "operations"

    def ready(self):
        # every installed app's jobs.py registers its kinds
        from django.utils.module_loading import autodiscover_modules

        autodiscover_modules("jobs")
