from plugin import InvenTreePlugin
from plugin.mixins import AppMixin, UrlsMixin, UserInterfaceMixin

from . import __version__


class PartsSheetPlugin(AppMixin, UrlsMixin, UserInterfaceMixin, InvenTreePlugin):
    NAME = "PartsSheet"
    SLUG = "parts-sheet"
    TITLE = "Parts Sheet"
    DESCRIPTION = "The whole catalogue in a familiar editable parts sheet"
    VERSION = __version__
    AUTHOR = "Matt Dick"
    WEBSITE = "https://github.com/damatter/inventree-parts-sheet"
    LICENSE = "MIT"
    MIN_VERSION = "1.3.2"
    MAX_VERSION = "1.3.99"

    def setup_urls(self):
        from django.urls import path
        from InvenTree.permissions import auth_exempt

        def lazy(name):
            def dispatch(request, *args, **kwargs):
                from . import views
                return getattr(views, name)(request, *args, **kwargs)
            return dispatch
        return [path("", lazy("index"), name="index"),
                path("assets/<str:filename>", auth_exempt(lazy("asset")), name="asset"),
                path("api/<str:action>/", lazy("api"), name="api")]

    def source(self, function):
        return f"/{self.base_url.lstrip('/')}assets/shortcut.js:{function}?v={self.VERSION}"

    def get_ui_dashboard_items(self, request, context, **kwargs):
        from django.core.exceptions import PermissionDenied

        from .services import require_part
        try:
            require_part(request.user, "view")
        except PermissionDenied:
            return []
        return [{"key": "parts-sheet", "title": self.TITLE,
                 "description": self.DESCRIPTION, "source": self.source("renderPartsSheet"),
                 "options": {"width": 3, "height": 2}}]

    def get_ui_spotlight_actions(self, request, context, **kwargs):
        return [{"key": "open-parts-sheet", "title": self.TITLE, "icon": "ti:table",
                 "source": self.source("openPartsSheet")}] if self.get_ui_dashboard_items(request, context) else []
