from django.contrib.admin.apps import AdminConfig


class ArenaFlowAdminConfig(AdminConfig):
    default_site = 'arenasystem.admin_site.ArenaFlowAdminSite'

    def ready(self):
        super().ready()
        from . import checks  # noqa: F401
