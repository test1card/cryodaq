from pathlib import Path

from cryodaq.analytics.base_plugin import AnalyticsPlugin, DerivedMetric


class TeardownPlugin(AnalyticsPlugin):
    plugin_id = "teardown_plugin"

    def __init__(self):
        super().__init__(self.plugin_id)

    def teardown(self):
        # Record teardown by touching a sentinel file next to the plugin.
        sentinel = Path(__file__).with_name("teardown_called.flag")
        sentinel.write_text("1", encoding="utf-8")

    async def process(self, readings):
        return [DerivedMetric.now(self.plugin_id, "m", 1.0, "arb")]
