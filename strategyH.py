# strategyH.py  ── 2025-07-06 修正版
import backtrader as bt

# ────────────────────────────────
# 1. ZigZag（Depth / Deviation / Backstep）
# ────────────────────────────────
class ZigZag(bt.Indicator):
    lines = ('zigzag',)
    params = (('depth', 24), ('deviation', 8), ('backstep', 6))

    def __init__(self):
        self.addminperiod(self.p.depth + 2)
        self.last_pivot = None
        self.trend = 0  # 1=up, -1=down, 0=undefined

    def next(self):
        idx = len(self.data) - 1
        hi, lo = self.data.high[0], self.data.low[0]

        # 初回
        if self.last_pivot is None:
            self.last_pivot = (idx, self.data.close[0])
            return

        last_idx, last_price = self.last_pivot

        # 上昇トレンド中
        if self.trend >= 0 and (hi - last_price) / last_price * 10000 >= self.p.deviation:
            self.trend = 1
            self.last_pivot = (idx, hi)
            self.lines.zigzag[0] = hi

        # 下降トレンド中
        if self.trend <= 0 and (last_price - lo) / last_price * 10000 >= self.p.deviation:
            self.trend = -1
            self.last_pivot = (idx, lo)
            self.lines.zigzag[0] = lo

# ────────────────────────────────
# 2. Strategy 定義
# ────────────────────────────────
class StrategyH(bt.Strategy):
    params = dict(
        spread=0.2,   # pips
        rr_min=1.0,   # RRフィルター
    )

    def __init__(self):
        # データフィード
        self.data15 = self.datas[0]              # 15分足
        self.data60 = self.datas[1]              # 60分足

        # 60分足SMA
        self.sma60_24 = bt.ind.SMA(self.data60, period=24)
        self.sma60_96 = bt.ind.SMA(self.data60, period=96)

        # 15分足SMA
        self.sma15_24  = bt.ind.SMA(self.data15, period=24)
        self.sma15_96  = bt.ind.SMA(self.data15, period=96)
        self.sma15_480 = bt.ind.SMA(self.data15, period=480)

        # ZigZag（60分）
        self.zz60 = ZigZag(self.data60, depth=24, deviation=8, backstep=6)

        # トレードログ
        self.trades_log = []

    # ── 60分足のトレンド判定 ──
    def is_uptrend_hourly(self, shift=0):
        cond1 = self.sma60_24[shift] > self.sma60_96[shift]
        cond2 = self.data60.close[shift] > self.sma60_96[shift]
        return cond1 and cond2

    def next(self):
        # 60分足トレンド状態
        trend_now   = self.is_uptrend_hourly(0)
        trend_prev  = self.is_uptrend_hourly(-1)
        trend_ended = trend_prev and not trend_now  # 上昇トレンドが途切れた瞬間

        # SMA96 を再上抜→下抜（60分足）
        cross_down = (
            self.data60.close[-1] > self.sma60_96[-1] and
            self.data60.close[0]  < self.sma60_96[0]
        )

        # 15分足の条件
        cond_15 = (
            self.data15.close[0] < self.sma15_480[0] and
            self.sma15_24[-1] > self.sma15_96[-1] and  # デッドクロス直前
            self.sma15_24[0]  < self.sma15_96[0]
        )

        # すべて成立 → ショートエントリー
        if trend_ended and cross_down and cond_15 and not self.position:
            entry_price = self.data15.low[0] - 0.0005    # 5pips下
            sl_price    = self.data15.high[-1] + 0.0005  # 直前Swing High +5pips
            tp_price    = entry_price - 0.0010           # +10pips

            rr = (entry_price - tp_price) / (sl_price - entry_price)
            if rr < self.p.rr_min:
                return  # RRフィルター

            self.sell(size=1.0)

            # ログ追加
            self.trades_log.append(dict(
                entry_dt     = self.data15.datetime.datetime(0),
                direction    = "short",
                entry_price  = entry_price,
                sl           = sl_price,
                tp           = tp_price
            ))

    # ── 約定通知でログ追記 ──
    def notify_order(self, order):
        if order.status == order.Completed and order.issell():
            self.trades_log[-1].update(dict(
                exit_dt    = self.data15.datetime.datetime(0),
                exit_price = order.executed.price,
                pips       = (self.trades_log[-1]["entry_price"] - order.executed.price) * 10000
            ))
