from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.connection_view_kind import ConnectionViewKind
from ..models.connection_view_test_status import ConnectionViewTestStatus
from typing import cast
from uuid import UUID
import datetime

if TYPE_CHECKING:
  from ..models.connection_view_prices import ConnectionViewPrices





T = TypeVar("T", bound="ConnectionView")



@_attrs_define
class ConnectionView:
    """ 
        Attributes:
            base_url (str):
            context_tokens (int): How many tokens its models take in one request (phase H5): what a chat is fitted and
                compacted to
            context_tokens_set (bool): Set on this connection, not the default
            display_name (str):
            has_key (bool): A key is saved. The key itself is never returned
            id (UUID):
            key_fingerprint (None | str): Tells keys apart without revealing them
            kind (ConnectionViewKind):
            models (list[str]):
            name (str): What agents say: `<name>:<model>`
            prices (ConnectionViewPrices): What a call to each model costs, and where that price comes from (phase H2):
                budgets in USD use it
            test_detail (None | str):
            test_status (ConnectionViewTestStatus):
            tested_at (datetime.datetime | None):
            tested_model (None | str):
     """

    base_url: str
    context_tokens: int
    context_tokens_set: bool
    display_name: str
    has_key: bool
    id: UUID
    key_fingerprint: None | str
    kind: ConnectionViewKind
    models: list[str]
    name: str
    prices: ConnectionViewPrices
    test_detail: None | str
    test_status: ConnectionViewTestStatus
    tested_at: datetime.datetime | None
    tested_model: None | str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.connection_view_prices import ConnectionViewPrices # noqa: PLC0415
        base_url = self.base_url

        context_tokens = self.context_tokens

        context_tokens_set = self.context_tokens_set

        display_name = self.display_name

        has_key = self.has_key

        id = str(self.id)

        key_fingerprint: None | str
        key_fingerprint = self.key_fingerprint

        kind = self.kind.value

        models = self.models



        name = self.name

        prices = self.prices.to_dict()

        test_detail: None | str
        test_detail = self.test_detail

        test_status = self.test_status.value

        tested_at: None | str
        if isinstance(self.tested_at, datetime.datetime):
            tested_at = self.tested_at.isoformat()
        else:
            tested_at = self.tested_at

        tested_model: None | str
        tested_model = self.tested_model


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "base_url": base_url,
            "context_tokens": context_tokens,
            "context_tokens_set": context_tokens_set,
            "display_name": display_name,
            "has_key": has_key,
            "id": id,
            "key_fingerprint": key_fingerprint,
            "kind": kind,
            "models": models,
            "name": name,
            "prices": prices,
            "test_detail": test_detail,
            "test_status": test_status,
            "tested_at": tested_at,
            "tested_model": tested_model,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.connection_view_prices import ConnectionViewPrices # noqa: PLC0415
        d = dict(src_dict)
        base_url = d.pop("base_url")

        context_tokens = d.pop("context_tokens")

        context_tokens_set = d.pop("context_tokens_set")

        display_name = d.pop("display_name")

        has_key = d.pop("has_key")

        id = UUID(d.pop("id"))




        def _parse_key_fingerprint(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        key_fingerprint = _parse_key_fingerprint(d.pop("key_fingerprint"))


        kind = ConnectionViewKind(d.pop("kind"))




        models = cast(list[str], d.pop("models"))


        name = d.pop("name")

        prices = ConnectionViewPrices.from_dict(d.pop("prices"))




        def _parse_test_detail(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        test_detail = _parse_test_detail(d.pop("test_detail"))


        test_status = ConnectionViewTestStatus(d.pop("test_status"))




        def _parse_tested_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                tested_at_type_0 = datetime.datetime.fromisoformat(data)



                return tested_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        tested_at = _parse_tested_at(d.pop("tested_at"))


        def _parse_tested_model(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        tested_model = _parse_tested_model(d.pop("tested_model"))


        connection_view = cls(
            base_url=base_url,
            context_tokens=context_tokens,
            context_tokens_set=context_tokens_set,
            display_name=display_name,
            has_key=has_key,
            id=id,
            key_fingerprint=key_fingerprint,
            kind=kind,
            models=models,
            name=name,
            prices=prices,
            test_detail=test_detail,
            test_status=test_status,
            tested_at=tested_at,
            tested_model=tested_model,
        )


        connection_view.additional_properties = d
        return connection_view

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
