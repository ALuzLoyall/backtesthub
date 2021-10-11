#! /usr/bin/env python3
import os, sys
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.engine.url import URL
from dotenv import load_dotenv

load_dotenv()

sys.path.append(
    os.path.dirname(
        os.path.dirname(__file__),
    )
)

from backtesthub.indicators.indicator import (
    Buy_n_Hold,
    Sell_n_Hold,
)
from backtesthub.pipelines.pipeline import (
    Rolling,
    Single,
)
from backtesthub.strategy import Strategy
from backtesthub.backtest import Backtest
from backtesthub.calendar import Calendar
from backtesthub.utils.bases import Line
from backtesthub.utils.math import adjust_stocks
from backtesthub.utils.config import (
    _DEFAULT_SDATE,
    _DEFAULT_EDATE,
    _DEFAULT_URL,
)

pd.options.mode.chained_assignment = None

######################### CONFIG #########################

base, hbase = "XAU", "USDBRL"
asset, hedge = "BIAU39", "DOL"
obases = ["CARRY"]
factor = "RISKPAR"
market = "COMMODITIES"
ohlc = ["open", "high", "low", "close"]
ohlcr = ["open", "high", "low", "close", "returns"]

config = {
    "factor": factor,
    "market": market,
    "asset": asset,
    "hedge": hedge,
    "base": base,
    "hbase": hbase,
}

##########################################################
##################### STRATEGY SETUP #####################

class Riskpar_BuyNHold(Strategy):
    params = {}

    def init(self):
        signal = self.I(
            data=self.base,
            func=Buy_n_Hold,
            **self.params,
        )

        volatility = self.V(
            data=self.base,
        )

        self.base.add_line(
            name="signal",
            line=Line(array=signal),
        )
        
        self.base.add_line(
            name="volatility",
            line=Line(array=volatility),
        )

        self.broadcast(
            base=self.base,
            assets=self.assets,
            lines=["signal", "volatility"],
        )

    def next(self):
        univ = self.get_universe()

        for asset in univ:
            self.order_target(
                data=asset,
                target=self.sizing(
                    data=asset,
                ),
            )


class Hedge_Expo(Strategy):
    params = {}

    def init(self):

        signal = self.I(
            data=self.hbase,
            func=Sell_n_Hold,
            **self.params,
        )

        volatility = self.V(
            data=self.hbase,
        )

        self.hbase.add_line(
            name="signal",
            line=signal,
        )
        
        self.hbase.add_line(
            name="volatility",
            line=volatility,
        )

        self.broadcast(
            base=self.hbase,
            assets=self.assets,
            lines=["signal", "volatility"],
        )

    def next(self):
        univ = self.get_universe()
        expo = self.get_texpo()
        texpo = expo / len(univ)

        for hedge in univ:
            self.order(
                data=hedge,
                size=self.sizing(
                    data=hedge,
                    texpo=texpo,
                    method="EXPO",
                ),
            )


##########################################################
##################  DATABASE OPERATIONS ##################

engine = create_engine(
    URL.create(**_DEFAULT_URL),
    pool_pre_ping=True,
    echo=False,
)

base_sql = (
    "SELECT date, ticker, open, high, low, close FROM quant.IndexesHistory "
    f"WHERE ticker = '{base}' AND date between "
    f"'{_DEFAULT_SDATE}' AND '{_DEFAULT_EDATE}'"
)

carry_sql = (
    "SELECT date, open, high, low, close FROM quant.IndexesHistory "
    f"WHERE ticker = 'CARRY' AND date between "
    f"'{_DEFAULT_SDATE}' AND '{_DEFAULT_EDATE}'"
)

price_sql = (
    "SELECT ticker, date, open, high, low, close, returns/100 as returns "
    "FROM quant.ReceiptsHistory s "
    f"WHERE s.ticker = '{asset}' AND "
    f"date between '{_DEFAULT_SDATE}' AND '{_DEFAULT_EDATE}'"
)

hbase_sql = (
    "SELECT date, ticker, open, high, low, close FROM quant.IndexesHistory "
    f"WHERE ticker = '{hbase}' AND date between "
    f"'{_DEFAULT_SDATE}' AND '{_DEFAULT_EDATE}'"
)

hmeta_sql = (
    "SELECT f.ticker as ticker, c.currency as curr, c.multiplier as mult, "
    "f.endDate as mat FROM quant.Commodities c "
    "INNER JOIN quant.Futures f ON c.ticker = f.commodity "
    f"WHERE c.ticker IN ('{hedge}') AND f.endDate > '{_DEFAULT_SDATE}' "
    "ORDER BY mat"
)

hprice_sql = (
    "SELECT ticker, date, open, high, low, close "
    "FROM quant.FuturesHistory f "
    f"WHERE f.commodity = '{hedge}' AND "
    f"date between '{_DEFAULT_SDATE}' AND '{_DEFAULT_EDATE}'"
)

price = pd.read_sql(price_sql, engine)
bprice = pd.read_sql(base_sql, engine)
carry = pd.read_sql(carry_sql, engine)

price.set_index("date", inplace=True)
bprice.set_index("date", inplace=True)
carry.set_index("date", inplace=True)

hmeta = pd.read_sql(hmeta_sql, engine)
hprice = pd.read_sql(hprice_sql, engine)
hbprice = pd.read_sql(hbase_sql, engine)

hmeta.set_index("ticker", inplace=True)
hprice.set_index("date", inplace=True)
hbprice.set_index("date", inplace=True)

carry = carry.pct_change()

##########################################################
####################  MAIN OPERATIONS ####################

calendar = Calendar(
    start=_DEFAULT_SDATE,
    end=min(
        _DEFAULT_EDATE,
        max(price.index),
    ),
    country="BR",
)

backtest = Backtest(
    strategy=Riskpar_BuyNHold,
    pipeline=Single,
    calendar=calendar,
    **config,
)

backtest.config_hedge(
    pipeline=Rolling,
    strategy=Hedge_Expo,
)

backtest.add_base(
    ticker=base,
    data=bprice[ohlc],
)

backtest.add_base(
    ticker="carry",
    data=carry[ohlc],
)

backtest.add_base(
    ticker=hbase,
    data=hbprice[ohlc],
)


backtest.add_asset(
    ticker=asset,
    data=adjust_stocks(
        price[ohlcr],
    ),
)

for hticker, hprop in hmeta.iterrows():
    mask = hprice.ticker == hticker
    data = hprice[mask]

    commkwargs = dict(
        multiplier=hprop.mult,
        currency=hprop.curr,
        maturity=hprop.mat,
    )

    backtest.add_hedge(
        ticker=hticker,
        data=data[ohlc],
        **commkwargs,
    )

res = backtest.run()

##########################################################
################### RESULTS MANAGEMENT ###################

strat, strat_meta = res["meta"], res["meta"].iloc[0, :]
df, rec = res["quotas"], res["records"]

strat.set_index("uid", inplace=True)
df.set_index("date", inplace=True)
rec.set_index("date", inplace=True)

##########################################################
##################### RESULTS OUTPUT #####################

with engine.connect().execution_options(autocommit=True) as conn:
    conn.execute(f"DELETE FROM quant._Strategies WHERE uid IN ('{strat_meta['uid']}') ")
    conn.execute(f"DELETE FROM quant._Quotas WHERE uid IN ('{strat_meta['uid']}')")
    conn.execute(f"DELETE FROM quant._Positions WHERE uid IN ('{strat_meta['uid']}')")

strat.to_sql(
    "_Strategies",
    con=engine,
    if_exists="append",
)

df.to_sql(
    "_Quotas",
    con=engine,
    if_exists="append",
)

rec.to_sql(
    "_Positions",
    con=engine,
    if_exists="append",
)