class Registry:
    active = True

    def get_plugin(self, slug, active=True):
        return self if self.active and slug == "customer-pricing" else None

    def get_setting(self, key, backup_value=None):
        return backup_value


registry = Registry()
