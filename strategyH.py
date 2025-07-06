# strategyH.py
import backtrader as bt
import math
from datetime import timedelta

# ────────────────────────────────
# 1. ZigZag（Depth / Deviation / Backstep）
# ────────────────────────────────
class ZigZag(bt.Indicator):
    lines = ('zigzag',)
    params = (('depth', 24), ('deviation', 8), ('backstep', 6))

    def __init__(self):
        self.addminperiod(self.p.depth + 2)
        self.last_pivot = None
        self.trend = 0

    def next(self):
        idx = len(self.data) - 1
        high = self.data.high[0]
        low = self.data.low[0]

        if self.last_pivot is None:
            self.last_pivot = (idx, self.data.close[0])
            return

        last_idx, last_price = self.last_pivot
        if self.trend >= 0:
            if (high - last_price) / last_price * 10000 >= self.p.deviation:
                self.trend = 1
                self.last_pivot = (idx, high)
                self.lines.zigzag[0] = high
        if self.trend <= 0:
            if (last_price - low) / last_price * 10000 >= self.p.deviation:
                self.trend = -1
                self.last_pivot = (idx, low)
                self.lines.zigzag[0] = low

# ────────────────────────────────
# 2. Strategy 定義
# ────────────────────────────────
class StrategyH(bt.Strategy):
    params = dict(
        spread = 0.2,  # pips
        rr_min = 1.0,  # RR比
    )

    def __init__(self):
        # データフィード
        self.data15 = self.datas[0]
        self.data60 = self.datas[1]

        # インジケーター
        self.sma60_24 = bt.ind.SMA(self.data60, period=24)
        self.sma60_96 = bt.ind.SMA(self.data60, period=96)

        self.sma15_24 = bt.ind.SMA(self.data15, period=24)
        self.sma15_96 = bt.ind.SMA(self.data15, period=96)
        self.sma15_480 = bt.ind.SMA(self.data15, period=480)

        self.zz60 = ZigZag(self.data60, depth=24, deviation=8, backstep=6)

        # ログ
        self.trades_log = []

    # トレンド判定（shift対応版）
    def is_uptrend_hourly(self, shift=0):
        cond1 = self.sma60_24[shift] > self.sma60_96[shift]
        cond2 = self.data60.close[shift] > self.sma60_96[shift]
        return cond1 and cond2

    def next(self):
        # トレンド状態
        trend_up = self.is_uptrend_hourly()
        trend_prev = self.is_uptrend_hourly(-1)
        trend_ended = trend_prev and not trend_up

        # クロス（上抜き→下抜け）
        cross_down = (
            self.data60.close[-1] > self.sma60_96[-1] and
            self.data60.close[0] < self.sma60_96[0]
        )

        # 15分足条件
        cond_15 = (
            self.data15.close[0] < self.sma15_480[0] and
            self.sma15_24[-1] > self.sma15_96[-1] and
            self.sma15_24[0] < self.sma15_96[0]
        )

        # 条件成立でショート
        if trend_ended and cross_down and cond_15 and not self.position:
            entry_price = self.data15.low[0] - 0.0005
            sl_price = self.data15.high[-1] + 0.0005
            tp_price = entry_price - 0.0010

            rr = (entry_price - tp_price) / (sl_price - entry_price)
            if rr < self.p.rr_min:
                return

            self.sell(size=1.0, exectype=bt.Order.Market, price=entry_price)

            self.trades_log.append(dict(
                entry_dt = self.data15.datetime.datetime(0),
                direction = "short",
                entry_price = entry_price,
                sl = sl_price,
                tp = tp_price
            ))

    def notify_order(self, order):
        if order.status == order.Completed and order.issell():
            self.trades_log[-1].update(dict(
                exit_dt = self.data15.datetime.datetime(0),
                exit_price = order.executed.price,
                pips = (self.trades_log[-1]["entry_price"] - order.executed.price) * 10000
            ))
