import pandas as pd
import numpy as np

from typing import Union
from ..utils.bases import (
    Base,
    Asset,
)


def Buy_n_Hold(
    data: Union[Base, Asset],
    *args,
) -> pd.Series:
    """
    Simple Buy-n-Hold Long Strategy
    """
    return np.ones(len(data))

def Sell_n_Hold(
    data: Union[Base, Asset],
    *args,
) -> pd.Series:
    """
    Simple Buy-n-Hold Long Strategy
    """
    return -np.ones(len(data))


def SMACross(
    data: Union[Base, Asset],
    p1: int,
    p2: int,
    *args,
) -> pd.Series:
    """
    `Simple Moving Average (SMA) Cross`
    """

    sma1 = pd.Series(data.close).rolling(p1).mean()
    sma2 = pd.Series(data.close).rolling(p2).mean()

    return np.sign(sma1 - sma2)

def SMARatio(
    data: Union[Base, Asset],
    p1: int,
    p2: int,
    *args,
) -> pd.Series:
    """
    `Simple Moving Average (SMA) Cross`
    """

    sma1 = pd.Series(data.close).rolling(p1).mean()
    sma2 = pd.Series(data.close).rolling(p2).mean()

    return np.divide(sma1, sma2) - 1

def RevSMACross(
    data: Union[Base, Asset],
    p1: int,
    p2: int,
    *args,
) -> pd.Series:
    """
    `Reversed Simple Moving Average (SMA) Cross`
    """

    sma1 = pd.Series(data.close).rolling(p1).mean()
    sma2 = pd.Series(data.close).rolling(p2).mean()

    return np.sign(sma2 - sma1)


def EMACross(
    data: Union[Base, Asset],
    p1: int,
    p2: int,
    *args,
) -> pd.Series:
    """
    `Exponential Moving Average (EMA) Cross`
    """
    
    ema1 = pd.Series(data.close).ewm(span=p1).mean()
    ema2 = pd.Series(data.close).ewm(span=p2).mean()

    return np.sign(ema1 - ema2)