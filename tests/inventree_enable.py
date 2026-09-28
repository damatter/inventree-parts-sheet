"""One-time equivalent of enabling both plugins on a new test server."""

from common.models import InvenTreeSetting
from django.conf import settings
from django.core.management import call_command
from django.utils.text import slugify
from plugin.helpers import get_entrypoints
from plugin.models import PluginConfig
from plugin.registry import registry

print(
    "Plugin runtime:",
    settings.PLUGINS_ENABLED,
    settings.PLUGIN_TESTING,
    [str(entry) for entry in get_entrypoints()],
)

for key in ("ENABLE_PLUGINS_APP", "ENABLE_PLUGINS_URL", "ENABLE_PLUGINS_INTERFACE"):
    InvenTreeSetting.set_setting(key, True)
for plugin in registry.collect_plugins():
    # A fresh database also needs records for built-in plugins. The shell command
    # cannot auto-create them; an absent built-in record aborts host initialization
    # before either installed third-party plugin can be reached.
    slug = slugify(getattr(plugin, "SLUG", None) or plugin.NAME)
    config = PluginConfig.objects.filter(key=slug).first() or PluginConfig(key=slug)
    config.name = plugin.NAME
    if slug in ("parts-sheet", "customer-pricing"):
        config.active = True
    config.save(no_reload=True)

registry.reload_plugins(collect=True, force_reload=True, full_reload=True)
print("Plugin discovery:", list(registry.plugins), registry.errors)
print("Registered apps:", registry.installed_apps)
assert registry.get_plugin("parts-sheet", active=True), registry.errors
assert registry.get_plugin("customer-pricing", active=True), registry.errors
call_command("migrate", interactive=False)
