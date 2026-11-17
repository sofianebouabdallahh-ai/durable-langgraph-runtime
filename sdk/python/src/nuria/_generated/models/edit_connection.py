from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast

if TYPE_CHECKING:
  from ..models.edit_connection_prices_type_0 import EditConnectionPricesType0





T = TypeVar("T", bound="EditConnection")



@_attrs_define
class EditConnection:
    """ 
        Attributes:
            api_key (None | str | Unset): A new key replaces the saved one; omit to keep it
            base_url (None | str | Unset):
            context_tokens (int | None | Unset): Its models' context window in tokens; 0 goes back to the default
            display_name (None | str | Unset):
            models (list[str] | None | Unset):
            prices (EditConnectionPricesType0 | None | Unset): A price per model, USD per 1 million tokens; null removes
                one. It wins over MODEL_PRICES and Nuria's price list
     """

    api_key: None | str | Unset = UNSET
    base_url: None | str | Unset = UNSET
    context_tokens: int | None | Unset = UNSET
    display_name: None | str | Unset = UNSET
    models: list[str] | None | Unset = UNSET
    prices: EditConnectionPricesType0 | None | Unset = UNSET





    def to_dict(self) -> dict[str, Any]:
        from ..models.edit_connection_prices_type_0 import EditConnectionPricesType0 # noqa: PLC0415
        api_key: None | str | Unset
        if isinstance(self.api_key, Unset):
            api_key = UNSET
        else:
            api_key = self.api_key

        base_url: None | str | Unset
        if isinstance(self.base_url, Unset):
            base_url = UNSET
        else:
            base_url = self.base_url

        context_tokens: int | None | Unset
        if isinstance(self.context_tokens, Unset):
            context_tokens = UNSET
        else:
            context_tokens = self.context_tokens

        display_name: None | str | Unset
        if isinstance(self.display_name, Unset):
            display_name = UNSET
        else:
            display_name = self.display_name

        models: list[str] | None | Unset
        if isinstance(self.models, Unset):
            models = UNSET
        elif isinstance(self.models, list):
            models = self.models


        else:
            models = self.models

        prices: dict[str, Any] | None | Unset
        if isinstance(self.prices, Unset):
            prices = UNSET
        elif isinstance(self.prices, EditConnectionPricesType0):
            prices = self.prices.to_dict()
        else:
            prices = self.prices


        field_dict: dict[str, Any] = {}

        field_dict.update({
        })
        if api_key is not UNSET:
            field_dict["api_key"] = api_key
        if base_url is not UNSET:
            field_dict["base_url"] = base_url
        if context_tokens is not UNSET:
            field_dict["context_tokens"] = context_tokens
        if display_name is not UNSET:
            field_dict["display_name"] = display_name
        if models is not UNSET:
            field_dict["models"] = models
        if prices is not UNSET:
            field_dict["prices"] = prices

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.edit_connection_prices_type_0 import EditConnectionPricesType0 # noqa: PLC0415
        d = dict(src_dict)
        def _parse_api_key(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        api_key = _parse_api_key(d.pop("api_key", UNSET))


        def _parse_base_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        base_url = _parse_base_url(d.pop("base_url", UNSET))


        def _parse_context_tokens(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        context_tokens = _parse_context_tokens(d.pop("context_tokens", UNSET))


        def _parse_display_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        display_name = _parse_display_name(d.pop("display_name", UNSET))


        def _parse_models(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                models_type_0 = cast(list[str], data)

                return models_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        models = _parse_models(d.pop("models", UNSET))


        def _parse_prices(data: object) -> EditConnectionPricesType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                prices_type_0 = EditConnectionPricesType0.from_dict(data)



                return prices_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(EditConnectionPricesType0 | None | Unset, data)

        prices = _parse_prices(d.pop("prices", UNSET))


        edit_connection = cls(
            api_key=api_key,
            base_url=base_url,
            context_tokens=context_tokens,
            display_name=display_name,
            models=models,
            prices=prices,
        )

        return edit_connection

