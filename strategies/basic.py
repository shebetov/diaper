from .base import StrategyParameter, BaseStrategy


class Strategy(BaseStrategy):

    VERBOSE_NAME = "Персечение двух SMA"
    WINDOW_LENGTH = 100
    TIMEFRAME = "5m"

    def __init__(self, strat_params):
        super().__init__(strat_params)

    def handle_data_candle(self, api, data, indi):
        pass

    def handle_data_tick(self, api, data, indicators):
        pass
