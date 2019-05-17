import websocket
import threading
import traceback
import json
import logging
import urllib
import math
import time
import hmac, hashlib
import pika
import os

NAMESPACE = "ws_orders"

RABBITMQ_CONF = {
    "host": "localhost",
    "exchange": "ws_bitmex",
    "queue": NAMESPACE,
    "routing_key": NAMESPACE,
}


def _get_logger(name):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    file_handler = logging.FileHandler(name + "_log.txt")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(console_handler)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


_get_logger(NAMESPACE)


def get_json_from_file(filename):
    with open(filename, "r") as f:
        return json.load(f)


# Utility method for finding an item in the store..
def findItemByKeys(keys, table, matchData):
    for item in table:
        matched = True
        for key in keys:
            if item[key] != matchData[key]:
                matched = False
        if matched:
            return item


class BitMEXWSOrder:

    # Don't grow a table larger than this amount. Helps cap memory usage.
    MAX_TABLE_LEN = 200
    ENDPOINT = "wss://www.bitmex.com/realtime?subscribe=order"

    def __init__(self, rabbitmq_conf=None):
        """Connect to the websocket and initialize data stores."""
        self.logger = logging.getLogger(NAMESPACE)
        self.logger.debug("Initializing WebSocket.")

        self._define_api()

        self.RM_CONF = rabbitmq_conf
        if rabbitmq_conf:
            self._connect_rabbitmq()

        self.data = []
        self.keys = []
        self.exited = False

        # We can subscribe right in the connection querystring, so let's build that.
        # Subscribe to all pertinent endpoints
        wsURL = self.ENDPOINT
        self.logger.info("Connecting to %s" % wsURL)
        self.__connect(wsURL)
        self.logger.info("Connected to WS.")

        self.wst.join()

    def _connect_rabbitmq(self):
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(self.RM_CONF["host"])
        )
        channel = connection.channel()
        channel.exchange_declare(
            exchange=self.RM_CONF["exchange"], exchange_type="fanout"
        )
        channel.queue_declare(queue=self.RM_CONF["queue"])
        self.rm_connection = connection
        self.rm_channel = channel

    def _define_api(self):
        if os.path.exists("keys/bitmex_key.json"):
            with open("keys/bitmex_key.json") as f:
                data = json.load(f)
                self.api_key = data.get("api_key")
                self.api_secret = data.get("secret")
        else:
            raise AttributeError("keys/auth.json does not exist")
        if not (self.api_key and self.api_secret):
            raise AttributeError("api_key or secret is missing in keys/auth.json")

    def exit(self):
        """Call this to exit - will close websocket."""
        self.exited = True
        self.ws.close()

    def get_orders(self):
        self.logger.info("get_orders:")
        self.logger.info(self.data)
        return self.data[0]

    def _send_rabbit_msg(self, t, order):
        msg = {}
        msg["generator"] = {"name": NAMESPACE, "version": 1}
        msg["exchange"] = "bitmex"
        msg["timestamp"] = t
        msg["source"] = "WS"
        msg["websocket_id"] = time.time()

        msg["id"] = order["orderID"]
        msg["price"] = order["price"]
        msg["symbol"] = order["symbol"]
        msg["side"] = order["side"]
        msg["triggered"] = order["triggered"]

        msg["stopPx"] = order["stopPx"]
        msg["type"] = order["ordType"]
        msg["status"] = order["ordStatus"]
        msg["filled"] = order["cumQty"]
        msg["remain"] = order["leavesQty"]

        self.logger.info("rabbit msg " + str(msg))
        if self.RM_CONF:
            properties = pika.BasicProperties(content_type="application/json")
            self.rm_channel.basic_publish(
                exchange=self.RM_CONF["exchange"],
                routing_key=self.RM_CONF["routing_key"],
                body=json.dumps(msg),
                properties=properties,
            )

    #
    # End Public Methods
    #
    def _reconn(self):
        while True:
            try:
                self.ws.run_forever(ping_interval=5, ping_timeout=4)
            except:
                pass

    def __connect(self, wsURL):
        """Connect to the websocket in a thread."""
        self.logger.debug("Starting thread")

        self.ws = websocket.WebSocketApp(
            wsURL,
            on_message=self.__on_message,
            on_close=self.__on_close,
            on_open=self.__on_open,
            on_error=self.__on_error,
            header=self.__get_auth(),
        )

        self.wst = threading.Thread(target=lambda: self._reconn())
        self.wst.daemon = True
        self.wst.start()
        self.logger.debug("Started thread")

        # Wait for connect before continuing
        conn_timeout = 5
        while not self.ws.sock or not self.ws.sock.connected and conn_timeout:
            time.sleep(1)
            conn_timeout -= 1
        if not conn_timeout:
            self.logger.error("Couldn't connect to WS! Exiting.")
            self.exit()
            raise websocket.WebSocketTimeoutException(
                "Couldn't connect to WS! Exiting."
            )

    def __get_auth(self):
        """Return auth headers. Will use API Keys if present in settings."""
        if self.api_key:
            self.logger.info("Authenticating with API Key.")
            # To auth to the WS using an API key, we generate a signature of a nonce and
            # the WS API endpoint.
            nonce = self._generate_nonce()
            return [
                "api-nonce: " + str(nonce),
                "api-signature: "
                + self._generate_signature(
                    self.api_secret, "GET", "/realtime", nonce, ""
                ),
                "api-key:" + self.api_key,
            ]
        else:
            self.logger.info("Not authenticating.")
            return []

    def __send_command(self, command, args=None):
        """Send a raw command."""
        if args is None:
            args = []
        self.ws.send(json.dumps({"op": command, "args": args}))

    def __on_message(self, ws, message):
        """Handler for parsing WS messages."""
        t = time.time()
        updated_orders = []

        message = json.loads(message)
        self.logger.debug(json.dumps(message))

        table = message["table"] if "table" in message else None
        action = message["action"] if "action" in message else None
        try:
            if "subscribe" in message:
                self.logger.debug("Subscribed to %s." % message["subscribe"])
            elif action:

                # There are four possible actions from the WS:
                # 'partial' - full table image
                # 'insert'  - new row
                # 'update'  - update row
                # 'delete'  - delete row
                if action == "partial":
                    self.logger.debug("%s: partial" % table)
                    self.data += message["data"]

                    updated_orders = message["data"]

                    # Keys are communicated on partials to let you know how to uniquely identify
                    # an item. We use it for updates.
                    self.keys = message["keys"]
                elif action == "insert":
                    self.logger.debug("%s: inserting %s" % (table, message["data"]))
                    self.data += message["data"]

                    updated_orders = message["data"]

                    # Limit the max length of the table to avoid excessive memory usage.
                    # Don't trim orders because we'll lose valuable state if we do.
                    if (
                        table not in ["order", "orderBookL2"]
                        and len(self.data) > self.MAX_TABLE_LEN
                    ):
                        self.data = self.data[int(self.MAX_TABLE_LEN / 2) :]

                elif action == "update":
                    self.logger.debug("%s: updating %s" % (table, message["data"]))
                    # Locate the item in the collection and update it.
                    for updateData in message["data"]:
                        item = findItemByKeys(self.keys, self.data, updateData)
                        if not item:
                            return  # No item found to update. Could happen before push
                        item.update(updateData)

                        if any(
                            [
                                x in updateData
                                for x in ["ordStatus", "cumQty" "leavesQty"]
                            ]
                        ):
                            updated_orders.append(item)

                        # Remove cancelled / filled orders
                        if table == "order" and item["leavesQty"] <= 0:
                            self.data.remove(item)
                elif action == "delete":
                    self.logger.debug("%s: deleting %s" % (table, message["data"]))
                    # Locate the item in the collection and remove it.
                    for deleteData in message["data"]:
                        item = findItemByKeys(self.keys, self.data, deleteData)
                        self.data.remove(item)
                else:
                    raise Exception("Unknown action: %s" % action)
        except:
            raise websocket.WebSocketException()

        for order in updated_orders:
            self._send_rabbit_msg(t, order)

    def __on_error(self, ws, error):
        """Called on fatal websocket errors. We exit on these."""
        if not self.exited:
            self.logger.error("Error : %s" % error)
            # self.rm_connection.close()
            # self.__init__()
            raise websocket.WebSocketException(error)

    def __on_open(self, ws):
        """Called when the WS opens."""
        self.logger.debug("Websocket Opened.")

    def __on_close(self, ws):
        """Called on websocket close."""
        self.rm_connection.close()
        self.logger.info("Websocket Closed")
        raise websocket.WebSocketException()

    @staticmethod
    def _generate_nonce():
        return int(round(time.time() * 1000))

    @staticmethod
    def _generate_signature(secret, verb, url, nonce, data):
        """Generate a request signature compatible with BitMEX."""
        # Parse the url so we can remove the base and extract just the path.
        parsedURL = urllib.parse.urlparse(url)
        path = parsedURL.path
        if parsedURL.query:
            path = path + "?" + parsedURL.query

        message = (verb + path + str(nonce) + data).encode("utf-8")
        signature = hmac.new(
            secret.encode("utf-8"), message, digestmod=hashlib.sha256
        ).hexdigest()
        return signature


if __name__ == "__main__":
    ws = BitMEXWSOrder(rabbitmq_conf=RABBITMQ_CONF)
