from cryodaq.analytics.base_plugin import AnalyticsPlugin, DerivedMetric


class GoodCompanionPlugin(AnalyticsPlugin):
    plugin_id = "good_companion"

    def __init__(self):
        super().__init__(self.plugin_id)

    async def process(self, readings):
        return [DerivedMetric.now(self.plugin_id, "companion_metric", 7.0, "arb")]
