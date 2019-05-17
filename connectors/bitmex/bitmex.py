#from bitmex_websocket import BitMEXWebsocket
import json
import ccxt
import time
import os
from collections import deque
import logging



def sentry(func):
    def func_wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except:
            pass  # client.captureException()

    return func_wrapper


round_ = lambda x: round(float(x) * 2) / 2


class Bitmex:
    # PUBLIC
    timeframes = {
        "1m": [lambda x: x.second % 60 == 0, 1],
        "5m": [lambda x: x.minute % 5 == 0 and x.second % 60 == 0, 5],
        "15m": [lambda x: x.minute % 15 == 0, 15],
        "30m": [lambda x: x.minute % 30 == 0, 30],
        "1h": [lambda x: x.minute % 60 == 0, 60],
        "4h": [lambda x: x.hour % 4 == 0 and x.minute % 60 == 0, 240],
    }

    def define_api(self):
        if os.path.exists(".keys/bitmex.json"):
            with open(".keys/bitmex.json") as f:
                data = json.load(f)
                self.api = ccxt.bitmex(
                    {"apiKey": data.get("api_key"), "secret": data.get("secret")}
                )
                if self.test:
                    if 'test' in self.api.urls:
                        self.api.urls['api'] = self.api.urls['test']

    def add_ws(self, symbols):
        if os.path.exists(".keys/bitmex.json"):
            with open(".keys/bitmex.json") as f:
                data = json.load(f)
                for s in symbols:
                    if s not in self.wss.keys():
                        try:
                            ws = BitMEXWebsocket(
                                endpoint=self.ws_endpoint,
                                symbol=s,
                                api_key=data.get("api_key"),
                                api_secret=data.get("secret"),
                            )
                            # time.sleep(1)
                            ws.get_instrument()
                            self.wss[s] = ws
                        except websocket.WebSocketTimeoutException:
                            print("ws connection error")
                            return False
        return True

    def __init__(self):
        self.test = True
        self.ws_endpoint = "wss://www.bitmex.com/realtime"
        self.wss = {}
        self.api = None
        self.limit = 500
        self.define_api()
        self.name_converter = {("XBTUSD", "BTC/USD")}
        self.limit = 500
        self._call_handlers = []

    def register_call_handler(self, handler):
        self._call_handlers.append(handler)

    def notify_call_handlers(self, method_name, params, result):
        for handler in self._call_handlers:
            handler(method_name, params, result)

    def ws_exit(self):
        for ws in self.wss:
            self.wss[ws].exit()

    def ws_get_balance(self):
        """
        add something
        """
        fields = ["walletBalance", "marginBalance", "availableMargin"]
        funds = self._get_balance()
        r = {f: funds[f] for f in fields}
        return r

    def convert(self, symbol):
        """Приводит валюту currency к стандартному виду"""
        for pair in self.name_converter:
            if symbol == pair[0]:
                return pair[1]
        return symbol

    # ORDERS
    def create_order(self, symbol, order_type, side, amount, price=None, params=None):
        """
        https://www.bitmex.com/api/explorer/#!/Order/Order_new
        """

        symbol = self.convert(symbol)
        price = round_(price) if price else None
        print(
            f"symbol={symbol}, type={order_type}, side={side}, amount={amount}, price={price}, params={params}"
        )
        if params:
            order = self.api.create_order(
                symbol=symbol,
                type=order_type,
                side=side,
                amount=int(amount),
                price=price,
                params=params,
            )
        else:
            order = self.api.create_order(
                symbol=symbol,
                type=order_type,
                side=side,
                amount=int(amount),
                price=price,
            )
        self.notify_call_handlers("create_order", dict(symbol=symbol, order_type=order_type, side=side, amount=amount), order)
        return order

    def create_market_order(self, symbol, side, amount):
        order_type = "Market"
        order = self.create_order(symbol, order_type, side, amount)
        return order

    def create_stoplimit_order(self, symbol, side, amount, price, stopPx):
        """
        price  - limit price to create order
        stopPx - trigger price to place order
        """
        params = {"stopPx": round_(stopPx)}
        order_type = "StopLimit"
        order = self.create_order(symbol, order_type, side, amount, price, params)
        return order

    def create_takeprofitlimit_order(self, symbol, side, amount, price, stopPx):
        # self.api.price_to_precision(symbol, stopPx)}
        params = {"stopPx": round_(stopPx)}
        order_type = "LimitIfTouched"
        order = self.create_order(symbol, order_type, side, amount, price, params)
        return order

    def create_stop_order(self, symbol, side, amount, stopPx):
        params = {"stopPx": round_(stopPx)}
        order_type = "Stop"
        order = self.create_order(symbol, order_type, side, amount, params)
        return order

    def create_limit_order(self, symbol, side, amount, price=None):
        """ordType
        if price is None, nearest from orderbook
        """
        if not price:
            ws_symbol = symbol
            price = self._price_for_non_price_order(ws_symbol, side)
        order_type = "Limit"
        order = self.create_order(symbol, order_type, side, amount, price)
        return order

    def cancel_order(self, id, symbol):
        symbol = self.convert(symbol)
        return self.api.cancel_order(id, symbol)

    # END ORDERS

    def ws_market_with_depth(self, symbol, depth=5):
        # переписать через heap
        orderbook = self.wss[symbol].market_depth()
        sell = sorted(
            [o for o in orderbook if o["side"] == "Sell"], key=lambda x: -x["price"]
        )
        buy = sorted(
            [o for o in orderbook if o["side"] == "Buy"], key=lambda x: -x["price"]
        )
        return sell[-depth:] + buy[:depth]

    def fetch_last_candles(self, symbol, tf, count):
        symbol = self.convert(symbol)
        temp_lst = []
        minute = self.timeframes[tf][1]
        start = int(time.time()) * 1000 - (count + 1) * minute * 60 * 1000
        while len(temp_lst) < count + 1:
            candles = self.api.fetch_ohlcv(
                symbol, timeframe=tf, since=start, limit=self.limit
            )
            temp_lst += candles
            start += len(candles) * minute * 60 * 1000
        return temp_lst[:-1]

    def fetch_markets(self):
        return [r["symbol"] for r in self.api.publicGetInstrumentActive()]

    def check_filled(self, order_id, symbol):
        """
        >>> check_filled(123456789, 'BTC/USD')
        {'status': 'open', 'filled': 30.0, 'remaining': 70.0}
        """
        symbol = self.convert(symbol)
        order = self._check_order(order_id, symbol)
        if not order:
            return None
        else:
            return {
                "status": order["status"],
                "filled": order["filled"],
                "remaining": order["remaining"],
            }

        """if order['status'] == 'canceled':
            print("\n  [✖] canceled")
        elif order['status'] == 'closed':
            print(f"\n  [✔] filled: {order['filled']} remaining: {order['remaining']}")
        else:
            print(f"  [*] filled: {order['filled']} remaining: {order['remaining']}")"""

    # PRIVATE
    def _get_balance(self):
        if self.wss:
            ws = next(iter(self.wss.values()))
            if ws.ws.sock.connected:
                funds = ws.funds()
                return funds

    def _price_for_non_price_order(self, symbol, side):
        ws = self.wss[symbol]
        price = None
        if ws.ws.sock.connected:
            if side == "buy":
                price = self.ws_market_with_depth(ws, 1)[1]["price"]
            if side == "sell":
                price = self.ws_market_with_depth(ws, 1)[0]["price"]
        return price

    def _check_order(self, order_id, symbol):
        try:
            order = self.api.fetch_order(id=order_id, symbol=symbol)
        # здесь должен быть ccxt.base.errors.OrderNotFound
        except ccxt.OrderNotFound:
            print("Order not found")
            # client.user_context({order_id})
            # client.captureException()
            return None
        return order
