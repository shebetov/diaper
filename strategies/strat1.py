from .base import StrategyParameter, BaseStrategy


f_delta = lambda x, y: (x / y - 1) * 100


class Strategy(BaseStrategy):

    VERBOSE_NAME = "Персечение двух SMA"
    WINDOW_LENGTH = 30
    TIMEFRAME = "1m"
    MA1 = StrategyParameter("Период MA1", "int", 10)
    MA2 = StrategyParameter("Период MA2", "int", 27)
    BALANCE = StrategyParameter("Баланс для торговли", "int", 5)

    def __init__(self, strat_params):
        self.state = None
        self.strat_params = strat_params
        self.INDICATORS = {
            "sma1": ("sma", self.strat_params["MA1"]),
            "sma1_prev": ("sma", self.strat_params["MA1"], 1),
            "sma2": ("sma", self.strat_params["MA2"]),
            "sma2_prev": ("sma", self.strat_params["MA2"], 1)
        }

    def handle_data_candle(self, api, data, indi):
        last_candle = data["candles"][-1]
        delta = (f_delta(indi.get("sma1_prev"), indi.get("sma2_prev")), f_delta(indi.get("sma1"), indi.get("sma2")))
        buy_cond = [
            last_candle[4] < indi.get("sma1"),
            delta[-1] > delta[-2],
            delta[-1] < -0.1,
            last_candle[3] < indi.get("sma1") < last_candle[2],
        ]
        sell_cond = [
            last_candle[4] > indi.get("sma1"),
            delta[-1] < delta[-2],
            delta[-1] > -0.1,
            last_candle[3] < indi.get("sma1") < last_candle[2],
        ]
        print(f"{self.state} buy : {buy_cond} sell: {sell_cond}")
        if self.state is None:
            if all(buy_cond) or True:
                api.create_market_order(data["symbol"], "buy", self.strat_params["BALANCE"])
                self.state = "long"
            elif all(sell_cond):
                api.create_market_order(data["symbol"], "sell", self.strat_params["BALANCE"])
                self.state = "short"
        elif self.state == "long":
            if all(sell_cond) or (delta[-1] - delta[-2] > 0.18 and delta[-1] > 0):
                api.create_market_order(data["symbol"], "sell", 2*self.strat_params["BALANCE"])
                self.state = "short"
        elif self.state == "short":
            if all(sell_cond) or (delta[-1] - delta[-2] < -0.18 and delta[-1] < 0):
                api.create_market_order(data["symbol"], "buy", 2*self.strat_params["BALANCE"])
                self.state = "long"


    def handle_data_tick(self, api, data, indicators):
        pass#print("tick")
