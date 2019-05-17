import pytest
import time
from exp2 import bitmex, timeframes
import pandas as pd
import numpy as np


def test_len_of_warm_up_deq_greater_limit():
    assert len(bitmex.fetch_last_candles("XBTUSD", "5m", 1380)) == 1380


def test_numpy_mean_std():
    a = bitmex.fetch_last_candles("XBTUSD", "5m", 1380)
    btc_data = list(map(lambda x: x[4], a))
    btc_data1 = pd.DataFrame(
        list(a), columns=["timestamp", "open", "high", "low", "close", "volume"]
    )
    assert btc_data1["close"].mean() == np.mean(btc_data)
    assert btc_data1["close"].std(ddof=0) == np.std(btc_data)


def test_len_of_warm_up_deq():
    assert len(bitmex.fetch_last_candles("XBTUSD", "5m", 380)) == 380


def test_actual_last_candle_in_warm_up_deq_greater_limit():
    tf = "5m"
    last_candle = bitmex.fetch_last_candles("XBTUSD", tf, 505)[-1]
    tf = timeframes[tf][1]
    assert time.time() - last_candle[0] < tf * 60 * 1000


def test_actual_last_candle_in_warm_up_deq():
    tf = "5m"
    last_candle = bitmex.fetch_last_candles("XBTUSD", tf, 35)[-1]
    tf = timeframes[tf][1]
    assert time.time() - last_candle[0] < tf * 60 * 1000


def test_actual_last_candle():
    tf = "5m"
    last_candle = bitmex.fetch_last_candles("XBTUSD", tf, 1)[-1]
    tf = timeframes[tf][1]
    assert time.time() - last_candle[0] < tf * 60 * 1000


def test_market_order_create():
    order = bitmex.create_market_order("XBTUSD", "buy", 2)
    bitmex.create_market_order("XBTUSD", "sell", 2)
    assert order["type"] == "market"
    assert order["amount"] == 2.0


def test_limit_order_create():
    order = bitmex.create_limit_order("XBTUSD", "buy", 2, 1000)
    bitmex.api.cancel_order(order["id"], "XBTUSD")
    assert order["type"] == "limit"
    assert order["amount"] == 2.0


def test_takeptofitlimit_order_create():
    order = bitmex.create_takeprofitlimit_order("XBTUSD", "sell", 2, 20000, 19000)
    bitmex.api.cancel_order(order["id"], "XBTUSD")
    assert order["type"] == "limitiftouched"
    assert order["amount"] == 2.0


def test_stoplimit_order_create():
    order = bitmex.create_stoplimit_order("XBTUSD", "buy", 2, 20000, 21000)
    bitmex.api.cancel_order(order["id"], "XBTUSD")
    assert order["type"] == "stoplimit"
    assert order["amount"] == 2.0


def test_check_filled():
    order = bitmex.create_stoplimit_order("XBTUSD", "buy", 2, 20000, 21000)
    status = bitmex.check_filled(order["id"], "XBTUSD")
    bitmex.api.cancel_order(order["id"], "XBTUSD")
    assert list(status.keys()) == ["status", "filled", "remaining"]
