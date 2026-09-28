"""One-time equivalent of enabling both plugins on a new test server."""
from common.models import InvenTreeSetting
from plugin.models import PluginConfig

for key in ("ENABLE_PLUGINS_APP", "ENABLE_PLUGINS_URL", "ENABLE_PLUGINS_INTERFACE"):
    InvenTreeSetting.set_setting(key, True)
for slug in ("parts-sheet", "customer-pricing"):
    config = PluginConfig.objects.filter(key=slug).first() or PluginConfig(key=slug)
    config.active = True
    config.save(no_reload=True)
