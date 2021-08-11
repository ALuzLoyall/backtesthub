#! /usr/bin/env python3

import pandas as pd
from abc import ABCMeta, abstractmethod
from typing import List, Dict, Callable, Union

from .order import Order
from .broker import Broker
from .utils.types import *
from .position import Position


class Strategy(metaclass=ABCMeta):
    def __init__(
        self,
        broker: Broker,
        datas: Dict[str, pd.DataFrame] = {},
    ):

        self.__datas = datas
        self.__broker = broker

        self.indicators = {}

    @abstractmethod
    def init(self):
        """
        * To initialize the strategy, override this method.

        * Declare indicators (with `backtesting.backtesting.Strategy.I`).

        * Precompute what needs to be precomputed or can be precomputed
          in a vectorized fashion before the strategy starts.

        * If you extend composable strategies from `backtesting.lib`,

        * make sure to call `super().init()`
        """

    @abstractmethod
    def next(self):
        """
        * Main strategy runtime method, called as each new
          `backtesting.backtesting.Strategy.data` instance
          (row; full candlestick bar) becomes available.

        * This is the main method where strategy decisions
          upon data precomputed in `backtesting.backtesting.
          Strategy.init` take place.

        * If you extend composable strategies from `backtesting.lib`,

        * make sure to call `super().next()`!
        """

    def I(self, data: Union[Base, Asset, Hedge], f: Callable, **params):

        """
        Declare indicator.

        * An indicator is just a line of values,but one that is revealed
          gradually in `backtesting.backtesting.Strategy.next` much like
          `backtesting.backtesting.Strategy.data` is.

        * `func` is a function that returns the indicator array(s) of
          same length as `backtesting.backtesting.Strategy.data`.

        * Additional `*args` and `**kwargs` are passed to `func` and can
          be used for parameters.

        * For example, using simple moving average function from TA-Lib:
            def init():
                self.sma = self.I(ta.SMA, self.data.Close, self.n_sma)
        """

        assert type(data) == Asset

        name = params.pop("name", None)

        if name is None:
            name = f"{f.__name__}{tuple(params.items())}"

        try:
            ind = f(**params)

        except Exception as e:
            raise Exception(e)

        if isinstance(ind, pd.DataFrame):
            ind = ind.values.T

        self.indicators[name] = Line(array=ind, index=data.index)

    def buy(self, ticker: str, size: float, price: float):
        return self.__broker.order(ticker, abs(size), price)

    def sell(self, ticker: str, size: float, price: float):
        return self.__broker.order(ticker, -abs(size), price)

    @property
    def equity(self) -> float:

        """
        Current account equity
        """

        return self.__broker.equity
