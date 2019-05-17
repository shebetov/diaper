import os
import time
from datetime import datetime
import logging
from collections import deque
import tkinter as tk
import tkinter.ttk as ttk
from tkinter.filedialog import askopenfilename
import numpy as np
import matplotlib.pyplot as plt
from matplotlib import dates, ticker
from mpl_finance import candlestick_ohlc
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from PIL import ImageTk, Image
from strategies.base import StrategyParameter
import utils
from plyer import notification


TIMEFRAMES = {
    "1m": [lambda x: x.second % 60 == 0, 1],
    "5m": [lambda x: x.minute % 5 == 0 and x.second % 60 == 0, 5],
    "15m": [lambda x: x.minute % 15 == 0, 15],
    "30m": [lambda x: x.minute % 30 == 0, 30],
    "1h": [lambda x: x.minute % 60 == 0, 60],
    "4h": [lambda x: x.hour % 4 == 0 and x.minute % 60 == 0, 240],
}

plt.rc('font', size=8)

def _get_logger(name):
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
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


def get_available_exchanges():
    path = "connectors/"
    return [name for name in os.listdir(path) if os.path.isdir(path + name)]


class IndicatorsHandler:

    def __init__(self, config):
        self.candles = None
        self._cache = {}
        self._INDICATORS = {}
        for k, v in config.items():
            self._cache[k] = []
            self._INDICATORS[k] = (getattr(__import__("indicators."+v[0], fromlist=[v[0]]), v[0]), v[1:])

    def update_candles(self, candles):
        self.candles = candles
        for k, v in self._INDICATORS.items():
            self._cache[k].append(self.get(k))
        return self._cache

    def get(self, key):
        indi = self._INDICATORS[key]
        return indi[0](self.candles, *indi[1])


class ScrollableFrame(tk.Frame):
    def __init__(self, parent, minimal_canvas_size, *args, **kw):
        tk.Frame.__init__(self, parent, *args, **kw)

        self.minimal_canvas_size = minimal_canvas_size

        vscrollbar = tk.Scrollbar(self, orient=tk.VERTICAL)
        vscrollbar.pack(fill=tk.Y, side=tk.RIGHT, expand=tk.FALSE)

        self.canvas = tk.Canvas(self, bd=0, highlightthickness=0, yscrollcommand=vscrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=tk.TRUE)

        vscrollbar.config(command=self.canvas.yview)

        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)

        self.canvas.config(scrollregion='0 0 %s %s' % self.minimal_canvas_size)


        self.interior = interior = tk.Frame(self.canvas)
        self.canvas.create_window(0, 0, window=interior, anchor=tk.NW)

        def _configure_interior(event):
            size = (max(interior.winfo_reqwidth(), self.minimal_canvas_size[0]), max(interior.winfo_reqheight(), self.minimal_canvas_size[1]))
            self.canvas.config(scrollregion='0 0 %s %s' % size)
            if interior.winfo_reqwidth() != self.canvas.winfo_width():
                self.canvas.config(width=interior.winfo_reqwidth())
        interior.bind('<Configure>', _configure_interior)


class Executor:

    def __init__(self, tk_app, strategy, exchange_api, symbol):
        self.tk_app = tk_app
        self.strategy = strategy
        self.exchange_api = exchange_api
        self.symbol = symbol

    def warm_up(self):
        pass

    def _run(self):
        data = {
            "symbol": self.symbol
        }
        indicators_handler = IndicatorsHandler(self.strategy.INDICATORS)
        next_candle_time = self.exchange_api.fetch_last_candles(self.symbol, self.strategy.TIMEFRAME, 1)[0][0] / 1000 + TIMEFRAMES[self.strategy.TIMEFRAME][1] * 60

        while not self.tk_app.is_stopped:
            if time.time() > next_candle_time:
                now = datetime.now()
                print(f"{now} {self.strategy.state}")
                data["candles"] = deque(
                    self.exchange_api.fetch_last_candles(data["symbol"], self.strategy.TIMEFRAME,
                                                         self.strategy.WINDOW_LENGTH), self.strategy.WINDOW_LENGTH
                )
                data["indicators"] = indicators_handler.update_candles(data["candles"])
                self.strategy.handle_data_candle(self.exchange_api, data, indicators_handler)
                self.tk_app._update_chart_data = data
                time.sleep(0.1)
                next_candle_time += TIMEFRAMES[self.strategy.TIMEFRAME][1] * 60
            self.strategy.handle_data_tick(self.exchange_api, data, indicators_handler)
            time.sleep(0.2)

    @utils.threaded
    def run(self, *args, **kwargs):
        self._run(*args, **kwargs)


class Application(tk.Frame):

    def __init__(self, master=None):
        super().__init__(master)
        self.master = master
        self.grid()
        self.init_UI()

        self.is_stopped = False
        self.is_status_hidden = False
        self._update_chart_data = None

        self.v_strategy_cls = None
        self.v_executor = None
        self.v_exchange_api = None
        self.v_symbol = None

    def init_UI(self):
        self.master.title("АТС")
        self.master.geometry("745x540")

        # TOP MENU
        self.menubar = tk.Menu(self.master)

        # create a pulldown menu, and add it to the menu bar
        self.filemenu = tk.Menu(self.menubar, tearoff=0)
        self.filemenu.add_command(label="Открыть", command=self.open_strat_file)
        self.filemenu.add_command(label="Выход", command=self.master.quit)
        self.menubar.add_cascade(label="Файл", menu=self.filemenu)

        # create more pulldown menus
        self.execmenu = tk.Menu(self.menubar, tearoff=0)
        self.execmenu.add_command(label="Старт/Стоп", command=self.handle_btn_start)
        #execmenu.add_command(label="Пауза", command=self.say_hi)
        #self.execmenu.add_command(label="Стоп", command=self.say_hi)
        self.menubar.add_cascade(label="Выполнение", menu=self.execmenu)

        self.viewmenu = tk.Menu(self.menubar, tearoff=0)
        self.viewmenu.add_command(label="Скрыть строку состояния", command=self.handle_status_hide)
        self.menubar.add_cascade(label="Вид", menu=self.viewmenu)

        self.helpmenu = tk.Menu(self.menubar, tearoff=0)
        self.helpmenu.add_command(label="Документация", command=self.handle_show_docs)
        self.helpmenu.add_command(label="О программе", command=self.handle_show_about)
        self.menubar.add_cascade(label="Справка", menu=self.helpmenu)

        # display the menu
        self.master.config(menu=self.menubar)

        # menu left
        self.menu_left = tk.Frame(self.master, width=200, bg="#ababab")
        self.menu_left_upper = tk.Frame(self.menu_left, width=200)
        self.menu_left_lower = tk.Frame(self.menu_left, width=200, height=100)

        self.params_title = tk.Label(self.menu_left_upper, text="Параметры", font=("Verdana", 10), bg="#dfdfdf")
        self.params_title.pack(pady=(0, 10), fill=tk.X)

        self.menu_left_upper.pack(side="top", fill=tk.BOTH, expand=True, padx=(0, 3), pady=(0, 0), ipadx=3, ipady=3)
        self.menu_left_lower.pack(side="top", fill=tk.BOTH, expand=False, padx=(0, 3), pady=(3, 1), ipadx=3, ipady=3)

        # right area
        self.some_title_frame = tk.Frame(self.master, bg="#dfdfdf")
        self.info_frame = tk.Frame(self.master)

        self.strat_title = tk.Label(self.some_title_frame, text="Стратегия не выбрана", bg="#dfdfdf")
        self.strat_title.pack()

        self.chart_area = tk.Frame(self.info_frame, width=500, height=400, background="#ffffff")
        self.chart_area.pack()
        self.chart_img = None

        self.table_area = ttk.Treeview(self.info_frame)
        self.table_area.pack()

        # status bar
        self.status_frame = tk.Frame(self.master)
        self.status = tk.Label(self.status_frame, text="Ожидание запуска.")
        self.status.pack(fill="both", expand=True)

        self.menu_left.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.some_title_frame.grid(row=0, column=1, sticky="ew")
        self.info_frame.grid(row=1, column=1, sticky="nsew")
        self.status_frame.grid(row=2, column=0, columnspan=2, sticky="ew")

        self.master.grid_rowconfigure(1, weight=1)
        self.master.grid_columnconfigure(1, weight=1)

        # TreeView
        self.table_area["columns"] = ("one", "two", "three")
        self.table_area.column("#0", width=125, minwidth=125, stretch=tk.NO)
        self.table_area.column("one", width=90, minwidth=90, stretch=tk.NO)
        self.table_area.column("two", width=100, minwidth=60)
        self.table_area.column("three", width=100, minwidth=60)

        self.table_area.heading("#0", text="Время исполнения", anchor=tk.W)
        self.table_area.heading("one", text="Направление", anchor=tk.W)
        self.table_area.heading("two", text="Цена", anchor=tk.W)
        self.table_area.heading("three", text="Сумма", anchor=tk.W)

        self.table_area.pack(fill=tk.X)

        tk.Label(self.menu_left_lower, text="Биржа").grid(row=0, sticky=tk.W, padx=2)
        self.exchange_combobox = ttk.Combobox(self.menu_left_lower, state="readonly", values=get_available_exchanges())
        self.exchange_combobox.bind("<<ComboboxSelected>>", self.on_exchange_change)
        self.exchange_combobox.grid(row=0, column=1, sticky=tk.W, pady=(6, 3))
        tk.Label(self.menu_left_lower, text="Валютная пара").grid(row=1, sticky=tk.W, padx=2)
        self.symbol_entry = ttk.Combobox(self.menu_left_lower, state="readonly")
        self.symbol_entry.bind("<<ComboboxSelected>>", self.on_symbol_change)
        self.symbol_entry.state(["disabled"])
        self.symbol_entry.grid(row=1, column=1, sticky=tk.W, pady=3)
        self.btn_start = tk.Button(self.menu_left_lower, text="Старт", bg="#008CBA", fg="white", font=("Verdana", 9), command=self.handle_btn_start)
        self.btn_start.grid(row=2, column=1, pady=3, sticky=tk.W+tk.E)

    def on_exchange_change(self, event):
        exchange_api_name = self.exchange_combobox.get()
        exchange_api_class_name = exchange_api_name.capitalize()
        self.v_exchange_api = getattr(__import__(f"connectors.{exchange_api_name}.{exchange_api_name}", fromlist=[exchange_api_class_name]), exchange_api_class_name)()
        self.symbol_entry.config(values=self.v_exchange_api.fetch_markets())
        self.symbol_entry.state(["!disabled"])

    def on_symbol_change(self, event):
        self.v_symbol = self.symbol_entry.get()
        self.master.after(1, self.draw_chart, {"symbol": self.v_symbol, "candles": deque(self.v_exchange_api.fetch_last_candles(self.v_symbol, "5m", 288), 288), "indicators": {}})

    def loop_draw_chart(self):
        if not self.is_stopped:
            if self._update_chart_data:
                self.draw_chart(self._update_chart_data)
                self._update_chart_data = None
            self.master.after(1000, self.loop_draw_chart)

    def draw_chart(self, data):
        ohlc_data = [(dates.date2num(datetime.fromtimestamp(row[0]/1e3)), np.float64(row[1]), np.float64(row[2]), np.float64(row[3]), np.float64(row[4])) for row in data["candles"]]
        y_data = np.array(list(map(lambda x: x[0], ohlc_data)))
        figure = plt.Figure(figsize=(6, 4), dpi=100)
        ax = figure.add_subplot(111)
        candlestick_ohlc(ax, ohlc_data, width=0.5 / (24 * 60), colorup='g', colordown='r', alpha=0.8)
        for k, v in data["indicators"].items():
            if len(v) > 1:
                ax.plot(y_data[-len(v):], np.array(v), label=k)
        ax.xaxis.set_major_formatter(dates.DateFormatter('%H:%M'))
        ax.xaxis.set_major_locator(ticker.MaxNLocator(8))
        ax.set_title('Текущая котировка')
        ax.legend()
        plt.xticks(rotation=30)
        plt.grid()
        plt.xlabel('Date')
        plt.ylabel('Price')
        plt.title('Historical Data EURUSD')
        plt.tight_layout()
        if self.chart_img: self.chart_img.get_tk_widget().destroy()
        self.chart_img = FigureCanvasTkAgg(figure, self.chart_area)
        self.chart_img.get_tk_widget().pack()

    def api_call_handler(self, method_name, params, result):
        if method_name == "create_order":
            self.table_area.insert("", 0, text=time.strftime("%d.%m %H:%M:%S", time.localtime()), values=(params["side"], result["price"], params["amount"]))
            notification.notify(
                title="Создан ордер",
                message=f'Тип: {params["side"]} Цена: {result["price"]}',
                app_name='АТС',
                app_icon='notification.ico'
            )

    def say_hi(self):
        print("hi there, everyone!")

    def open_strat_file(self):
        filepath = askopenfilename()
        self.v_strategy_cls = __import__("strategies."+os.path.basename(filepath).rstrip(".py"), fromlist=["Strategy"]).Strategy
        self.strat_title.config(text=self.v_strategy_cls.VERBOSE_NAME)
        self.STRAT_PARAMS_ENTRY = {}
        last_row = 0
        for child in self.menu_left_upper.winfo_children()[1:]:
            child.destroy()
        for k, v in vars(self.v_strategy_cls).items():
            if isinstance(v, StrategyParameter):
                row_frame = tk.Frame(self.menu_left_upper)
                tk.Label(row_frame, text=v.verbose_name).pack(side="left")
                var = {"int": tk.IntVar, "string": tk.StringVar}[v.value_type]()
                tk.Entry(row_frame, textvariable=var, width=14).pack(side="right")
                var.set(v.default)
                self.STRAT_PARAMS_ENTRY[k] = var
                row_frame.pack(fill=tk.X, ipadx=3, ipady=3, padx=3)
                last_row += 1

    def handle_show_docs(self):
        img = ImageTk.PhotoImage(Image.open("docs.png"))

        window = tk.Toplevel(self.master)
        window.minsize(600, 500)
        window.wm_title("Документация")
        #window.wm_geometry("596x1000")
        window.resizable(0, 1)
        minimal_canvas_size = (600, 600)

        frame = ScrollableFrame(window, minimal_canvas_size)
        frame.pack(fill=tk.BOTH, expand=tk.YES)
        frame.canvas.create_image(0, 0, image=img, anchor=tk.NW)
        frame.canvas.image = img

    def handle_show_about(self):
        t = tk.Toplevel(self)
        t.wm_title("О программе")
        l = tk.Label(t, text="АТС - автоматизированная система торговли. Программа предназначена для запуска \nторговых стратегий на криптовалютных биржах.\n\nРазработана: Щебетовым А.А. в рамках учебного задания.")
        l.pack(side="top", fill="both", expand=True, padx=10, pady=50)

    def handle_status_hide(self):
        self.is_status_hidden = not self.is_status_hidden
        if self.is_status_hidden:
            self.status_frame.grid_remove()
            self.viewmenu.entryconfig(0, label="Показать строку состояния")
        else:
            self.status_frame.grid(row=2, column=0, columnspan=2, sticky="ew")
            self.viewmenu.entryconfig(0, label="Скрыть строку состояния")

    def handle_btn_start(self):
        if self.v_executor:
            self.is_stopped = True
            self.btn_start.config(text="Старт", bg="#008CBA")
            self.status.config(text="Стратегия остановлена.")
            self.filemenu.entryconfig("Открыть", state="normal")
            self.v_executor = None
        else:
            if not self.v_strategy_cls:
                tk.messagebox.showinfo("Ошибка", "Не выбран файл стратегии. (Файл -> Открыть)")
            elif not self.v_exchange_api:
                tk.messagebox.showinfo("Ошибка", "Не выбрана биржа.")
            elif not isinstance(self.v_symbol, str):
                tk.messagebox.showinfo("Ошибка", "Не выбрана валютная пара.")
            else:
                self.is_stopped = False
                self.btn_start.config(text="Стоп", bg="#ad281f")
                self.status.config(text="Стратегия запущена.")
                self.filemenu.entryconfig("Открыть", state="disabled")
                self.v_exchange_api.register_call_handler(self.api_call_handler)
                strategy = self.v_strategy_cls({k: v.get() for k, v in self.STRAT_PARAMS_ENTRY.items()})
                self.v_executor = Executor(self, strategy, self.v_exchange_api, self.v_symbol)
                self.v_executor.run()
                self.loop_draw_chart()


if __name__ == "__main__":
    Application(master=tk.Tk()).mainloop()
