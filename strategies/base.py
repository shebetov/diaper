

class StrategyParameter:

    def __init__(self, verbose_name, value_type, default):
        self.verbose_name = verbose_name
        self.value_type = value_type
        self.default = default


class BaseStrategy:

    VERBOSE_NAME = "Базовая стратегия"

    def __init(self, strat_params):
        self.state = None
        self.strat_params = strat_params
        self.INDICATORS = {}

    def handle_data_candle(self, api, data, indicators):
        pass

    def handle_data_tick(self, api, data, indicators):
        pass
