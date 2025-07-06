# strategyH.py
import backtrader as bt
import math
from datetime import timedelta

# ──────────────────────────────────────────────
# 1. ZigZag（Depth / Deviation / Backstep）を簡易実装
# ──────────────────────────────────────────────
class ZigZag(bt.Indicator):
    lines = ('zigzag',)
    params = (('depth', 24), ('deviation', 8), ('backstep', 6))

    def __init__(self):
        self.addminperiod(self.p.depth + 2)
        self.last_pivot = None        # (index, price)
        self.trend = 0                # 1 = up, -1 = down

    def next(self):
        idx = len(self.data) - 1
        high = self.data.high[0]
        low  = self.data.low[0]

        if self.last_pivot is None:
            self.last_pivot = (idx, self.data.close[0])
            return

        last_idx, last_price = self.last_pivot
        if self.trend >= 0:  # up-trend or undefined
            if (high - last_price) / last_price * 10000 >= self.p.deviation:
                self.trend = 1
                self.last_pivot = (idx, high)
                self.lines.zigzag[0] = high
        if self.trend <= 0:  # down-trend or undefined
            if (last_price - low) / last_price * 10000 >= self.p.deviation:
                self.trend = -1
                self.last_pivot = (idx, low)
                self.lines.zigzag[0] = low


# ──────────────────────────────────────────────
# 2. Strategy 定義
# ──────────────────────────────────────────────
class StrategyH(bt.Strategy):
    params = dict(
        spread = 0.2,             # pips
        rr_min = 1.0,             # RR比が 1:1 未満なら見送り
    )

    def __init__(self):

        # === データフィード ===
        # data0 : 15分足（メイン）
        # data1 : 60分足（resample で追加）
        self.data15 = self.datas[0]
        self.data60 = self.datas[1]

        # === インジケーター ===
        # 60分足 SMA
        self.sma60_24  = bt.ind.SMA(self.data60, period=24)
        self.sma60_96  = bt.ind.SMA(self.data60, period=96)

        # 15分足 SMA
        self.sma15_24  = bt.ind.SMA(self.data15, period=24)
        self.sma15_96  = bt.ind.SMA(self.data15, period=96)
        self.sma15_480 = bt.ind.SMA(self.data15, period=480)

        # ZigZag（60分足）
        self.zz60 = ZigZag(self.data60, depth=24, deviation=8, backstep=6)

        # トレードログ
        self.trades_log = []

    # ── ヘルパー：60分トレンド判定 ──
    def is_uptrend_hourly(self):
        cond1 = self.sma60_24[0] > self.sma60_96[0]
        cond2 = self.data60.close[0] > self.sma60_96[0]
        return cond1 and cond2

    def next(self):
        # --- 取引不可時間帯（雇用統計など）は簡略化のため未実装 ---

        # --- トレンド判定（60分足） ---
        trend_up = self.is_uptrend_hourly()
        trend_prev = self.is_uptrend_hourly(-1)

        # 上昇トレンド終了を検知（条件①②の崩れ）
        trend_ended = trend_prev and (not trend_up)

        # 60分 SMA96 を再上抜き→下抜き（条件③）
        cross_down = (
            self.data60.close[-1] > self.sma60_96[-1] and
            self.data60.close[0]  < self.sma60_96[0]
        )

        # 15分側の条件④⑤
        cond_15 = (
            self.data15.close[0] < self.sma15_480[0] and
            self.sma15_24[-1] > self.sma15_96[-1] and
            self.sma15_24[0]  < self.sma15_96[0]
        )

        # すべて満たせばショート候補
        if trend_ended and cross_down and cond_15 and not self.position:
            entry_price = self.data15.low[0] - 0.0005   # 5pips下
            sl_price    = self.data15.high[-1] + 0.0005 # 直前Swing High +5pips（簡易）
            tp_price    = entry_price - 0.0010          # +10pips

            # RR比でフィルタ
            rr = (entry_price - tp_price) / (sl_price - entry_price)
            if rr < self.p.rr_min:
                return

            size = 1.0   # ロット（適宜調整）
            self.sell(size=size, exectype=bt.Order.Market, price=entry_price)

            # ログ
            self.trades_log.append(dict(
                entry_dt  = self.data15.datetime.datetime(0),
                direction = "short",
                entry_price = entry_price,
                sl = sl_price,
                tp = tp_price
            ))

    # 約定通知でログに追記
    def notify_order(self, order):
        if order.status == order.Completed and order.issell():
            self.trades_log[-1].update(dict(
                exit_dt = self.data15.datetime.datetime(0),
                exit_price = order.executed.price,
                pips = (self.trades_log[-1]["entry_price"] - order.executed.price) * 10000
            ))
