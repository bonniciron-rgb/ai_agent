"""Pydantic models for Trading 212 API responses."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class CashInfo(BaseModel):
    free: Decimal
    total: Decimal
    ppl: Decimal = Decimal(0)  # unrealised P&L on open positions
    result: Decimal = Decimal(0)  # realised P&L (session)
    invested: Decimal = Decimal(0)
    pie_cash: Decimal = Field(default=Decimal(0), alias="pieCash")

    model_config = {"populate_by_name": True}


class OpenPosition(BaseModel):
    ticker: str
    quantity: Decimal
    average_price: Decimal = Field(alias="averagePrice")
    current_price: Decimal = Field(alias="currentPrice")
    ppl: Decimal = Decimal(0)
    fx_ppl: Decimal = Field(default=Decimal(0), alias="fxPpl")
    initial_fill_date: str | None = Field(default=None, alias="initialFillDate")
    frontend: str | None = None

    model_config = {"populate_by_name": True}


class LimitOrderRequest(BaseModel):
    """Body for POST /api/v0/equity/orders/limit."""

    ticker: str
    quantity: Decimal
    limit_price: Decimal = Field(serialization_alias="limitPrice")
    time_validity: str = Field(default="GTC", serialization_alias="timeValidity")

    model_config = {"populate_by_name": True}


class StopLimitOrderRequest(BaseModel):
    """Body for POST /api/v0/equity/orders/stop-limit."""

    ticker: str
    quantity: Decimal
    limit_price: Decimal = Field(serialization_alias="limitPrice")
    stop_price: Decimal = Field(serialization_alias="stopPrice")
    time_validity: str = Field(default="GTC", serialization_alias="timeValidity")

    model_config = {"populate_by_name": True}


class OrderResponse(BaseModel):
    id: int
    ticker: str
    quantity: Decimal
    status: str
    type: str
    limit_price: Decimal | None = Field(default=None, alias="limitPrice")
    stop_price: Decimal | None = Field(default=None, alias="stopPrice")
    filled_quantity: Decimal = Field(default=Decimal(0), alias="filledQuantity")
    fill_price: Decimal | None = Field(default=None, alias="fillPrice")
    time_validity: str | None = Field(default=None, alias="timeValidity")
    creation_time: str | None = Field(default=None, alias="creationTime")

    model_config = {"populate_by_name": True}
