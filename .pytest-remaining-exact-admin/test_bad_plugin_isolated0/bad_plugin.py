from cryodaq.analytics.base_plugin import AnalyticsPlugin, DerivedMetric


class BadPlugin(AnalyticsPlugin):
    plugin_id = "bad_plugin"

    def __init__(self):
        super().__init__(self.plugin_id)

    async def process(self, readings):
        raise RuntimeError("intentional failure for testing")
