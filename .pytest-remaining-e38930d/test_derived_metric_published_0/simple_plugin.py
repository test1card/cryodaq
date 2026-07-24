from cryodaq.analytics.base_plugin import AnalyticsPlugin, DerivedMetric


class SimplePlugin(AnalyticsPlugin):
    plugin_id = "simple_plugin"

    def __init__(self):
        super().__init__(self.plugin_id)
        self._configured = False
        self._config_value = None

    def configure(self, config):
        super().configure(config)
        self._configured = True
        self._config_value = config.get("test_key")

    async def process(self, readings):
        return [DerivedMetric.now(self.plugin_id, "test_metric", 42.0, "arb")]
