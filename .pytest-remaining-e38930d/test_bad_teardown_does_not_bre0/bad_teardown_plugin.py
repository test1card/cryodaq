from cryodaq.analytics.base_plugin import AnalyticsPlugin, DerivedMetric


class BadTeardownPlugin(AnalyticsPlugin):
    plugin_id = "bad_teardown_plugin"

    def __init__(self):
        super().__init__(self.plugin_id)

    def teardown(self):
        raise RuntimeError("teardown boom")

    async def process(self, readings):
        return [DerivedMetric.now(self.plugin_id, "m", 1.0, "arb")]
