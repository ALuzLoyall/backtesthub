#! /usr/bin/env python3

from os import pipe
import pandas as pd
from numbers import Number
from uuid import uuid3, NAMESPACE_DNS
from collections import OrderedDict
from datetime import date, datetime
from typing import (
    Dict,
    List,
    Sequence,
    Union,
)

from .broker import Broker
from .pipeline import Pipeline
from .strategy import Strategy
from .calendar import Calendar

from .utils.bases import Line, Base, Asset
from .utils.math import fill_OHLC

from .utils.config import (
    _DEFAULT_BUFFER,
    _DEFAULT_HEDGE,
    _DEFAULT_SIZING,
    _DEFAULT_THRESH,
    _DEFAULT_VPARAM,
    _DEFAULT_MAX_LOSS,
    _DEFAULT_VOLATILITY,
    _DEFAULT_CARRY,
    _DEFAULT_PAIRS,
    _DEFAULT_ECHO,
    _DEFAULT_MARKET,
)


class Backtest:

    """
    `Backtest Class`

    Instances of this class are responsible for orchestrating all
    related objects (Strategy, Broker, Position, ...) in order to
    properly run the simulation.

    It is also responsible for manipulating the global index and
    guaranteeing that all Data/Lines/Broker/Strategy are 
    synchronized.

    Lots of features such as intraday operations, multi-calendar
    runs, live trading, etc. are still pending development.

    Some settings may be changed through environment variables
    configuration. Refer to .utils.config to get more info.
    """

    def __init__(
        self,
        strategy: Strategy,
        pipeline: Pipeline,
        calendar: Calendar,
        **config: str,
    ):
        if not issubclass(strategy, Strategy):
            msg = "Arg `strategy` must be a `Strategy` subclass!"
            raise TypeError(msg)
        if not issubclass(pipeline, Pipeline):
            msg = "Arg `pipeline` must be a `Pipeline` subclass!"
            raise TypeError(msg)
        if not isinstance(calendar, Calendar):
            msg = "Arg `calendar` must be a `Calendar` instance!"
            raise TypeError(msg)

        self.__index: Sequence[date] = calendar.index
        self.__firstdate: date = self.__index[0]
        self.__lastdate: date = self.__index[-1]

        self.__factor: str = config.get("factor")
        self.__market: str = config.get("market")
        self.__asset: str = config.get("asset")
        self.__hedge: str = config.get("hedge")
        self.__base: str = config.get("base")
        self.__hbase: str = config.get("hbase")
        self.__vertices: List[int] = config.get("vertices")

        self.__main: Line = Line(self.__index)
        self.__bases: Dict[str, Base] = OrderedDict()
        self.__assets: Dict[str, Asset] = OrderedDict()
        self.__hedges: Dict[str, Asset] = OrderedDict()

        self.__broker: Broker = Broker(
            index=self.__index,
            echo=_DEFAULT_ECHO,
        )

        self.__pipeline: Pipeline = pipeline(
            main=self.__main,
            holidays=calendar.holidays,
            broker=self.__broker,
            assets=self.__assets,
        )

        self.__strategy: Strategy = strategy(
            broker=self.__broker,
            pipeline=self.__pipeline,
            bases=self.__bases,
            assets=self.__assets,
        )

    def config_hedge(
        self,
        pipeline: Pipeline,
        strategy: Strategy,
    ):
        """
        `Configure Hedge Method`

        Works similarly to the strategy configuration
        but this is specifically designed for hedging.

        To properly define a strategy, one needs to build 
        both pipeline and strategy rules, consistent with
        the asset class and hedge properties desired.

        """

        if not issubclass(strategy, Strategy):
            msg = "Arg `strategy` must be a `Strategy` subclass!"
            raise TypeError(msg)
        if not issubclass(pipeline, Pipeline):
            msg = "Arg `pipeline` must be a `Pipeline` subclass!"
            raise TypeError(msg)

        self.__hpipeline: Pipeline = pipeline(
            main=self.__main,
            broker=self.__broker,
            assets=self.__hedges,
        )

        self.__hstrategy: Strategy = strategy(
            broker=self.__broker,
            pipeline=self.__hpipeline,
            bases=self.__bases,
            assets=self.__hedges,
        )

    def add_base(
        self,
        ticker: str,
        data: pd.DataFrame,
    ):
        """
        `Add Base Method`

        - Main base is assumed to be added first.
        - Main hbase is assumed to be added last.

        Bases that can be classified either as
        1) Currency Pairs, 2) Carry (i.e. "risk
        free" cost of carry), 3) Market (i.e.
        market index that can be used to make
        beta regressions), will be assigned
        to broker so that it may use for 
        important calculations.

        Reminder: Bases are data structures fed for
        any purpose that is not trading. You may want
        to define a base for things such as signal
        generation, currency conversion, volatility
        estimation. 
        
        More info @ backtesthub/utils/bases.py  
        """

        base = Base(
            ticker=ticker,
            data=data,
            index=self.index,
        )

        self.__bases.update(
            {ticker: base},
        )

        if ticker.upper() in _DEFAULT_PAIRS:
            self.__broker.add_curr(base)
        if ticker.upper() == _DEFAULT_CARRY:
            self.__broker.add_carry(base)
        if ticker.upper() == _DEFAULT_MARKET:
            self.__broker.add_market(base)

    def add_asset(
        self,
        ticker: str,
        data: pd.DataFrame,
        **commkwargs: Union[str, Number],
    ):
        """
        `Add Asset Method`

        Add data structures that will be used for
        trading purposes. This does not mean that
        they cannot be used for same purposes of
        'bases', but you need to be aware of the
        drawbacks.

        `fill_OHLC` is applied to `data`, in order
        to guarantee that broker gets an appropriate
        schema for tradeable assets.
        
        More info @ backtesthub/utils/bases.py. 
        """

        asset = Asset(
            data=fill_OHLC(data),
            ticker=ticker,
            index=self.index,
            **commkwargs,
        )

        self.__assets.update(
            {ticker: asset},
        )

    def add_hedge(
        self,
        ticker: str,
        data: pd.DataFrame,
        **commkwargs: Union[str, Number],
    ):
        hedge = Asset(
            data=fill_OHLC(data),
            ticker=ticker,
            index=self.index,
            **commkwargs,
        )

        self.__hedges.update(
            {ticker: hedge},
        )

    def run(self) -> Dict[str, pd.DataFrame]:
        if not self.__assets:
            return

        self.config_backtest()

        self.__pipeline.init()
        self.__strategy.init()

        if self.__hedges:
            self.__hpipeline.init()
            self.__hstrategy.init()

        while self.dt < self.__lastdate:
            self.__advance_buffers()
            self.__broker.beg_of_period()
            self.__pipeline.next()
            self.__strategy.next()
            if self.__hedges:
                self.__hpipeline.next()
                self.__hstrategy.next()
            self.__broker.end_of_period()

            if self.__broker.cum_return < _DEFAULT_MAX_LOSS:
                break

        return {
            "meta": self.__properties,
            "quotas": self.__broker.df,
            "records": self.__broker.rec,
            "broker": self.__broker,
        }

    def __advance_buffers(self):
        self.__main.next()
        self.__broker.next()
        for data in self.datas.values():
            data.next()

    def __repr__(self) -> str:
        if not hasattr(self, "__hash"):
            self.config_backtest()
        return self.__hash

    @property
    def dt(self) -> date:
        return self.__main[0]

    @property
    def bookname(self) -> str:
        """
        `Bookname Property`

        Defines the official 
        book name formula.
        """

        book = f"{self.__factor}-{self.__market}-{self.__asset}"
        mapper = dict(
            EXPO="/",
            BETA="#",
        )
        if self.__hedge:
            book += f"{mapper[_DEFAULT_HEDGE]}{self.__hedge}"

        return book

    @property
    def index(self) -> Sequence[date]:
        return self.__index

    @property
    def strategy(self) -> Strategy:
        return self.__strategy

    @property
    def base(self) -> Base:
        return tuple(self.__bases.values())[0]

    @property
    def hbase(self) -> Base:
        return tuple(self.__bases.values())[-1]

    @property
    def bases(self) -> Dict[str, Base]:
        return self.__bases

    @property
    def datas(self) -> Dict[str, Union[Base, Asset]]:
        return {**self.__bases, **self.__assets, **self.__hedges}

    def config_backtest(self):
        """
        `Configure Backtest UID`

        Defines the official 
        uid for backtest given
        input data.
        """

        self.__hash = {
            "factor": self.__factor,
            "market": self.__market,
            "asset": self.__asset,
            "hedge": self.__hedge,
            "base": self.__base,
            "hbase": self.__hbase,
            "vertices": self.__vertices,
            "pipeline": self.__pipeline.__class__.__name__,
            "model": self.__strategy.__class__.__name__,
            "params": dict(self.__strategy.get_params()),
            "budget": _DEFAULT_VOLATILITY,
            "buffer": _DEFAULT_BUFFER,
        }

        self.__uid = uuid3(
            NAMESPACE_DNS,
            str(self.__hash),
        )

        self.__properties = pd.DataFrame.from_records(
            [
                {
                    **self.__hash,
                    "uid": self.__uid.hex,
                    "sdate": self.__firstdate.isoformat(),
                    "edate": self.__lastdate.isoformat(),
                    "updtime": datetime.now().isoformat(),
                    "sizing": _DEFAULT_SIZING,
                    "thresh": _DEFAULT_THRESH,
                    "vparam": _DEFAULT_VPARAM,
                    "bookname": self.bookname,
                }
            ]
        )
