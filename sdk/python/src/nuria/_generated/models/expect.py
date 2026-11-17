from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.expect_status import ExpectStatus
from ..types import UNSET, Unset
from typing import cast

if TYPE_CHECKING:
  from ..models.expect_answer_schema_type_0 import ExpectAnswerSchemaType0





T = TypeVar("T", bound="Expect")



@_attrs_define
class Expect:
    """ What the turn must do. Every field set is one check; none set: it completed.

        Attributes:
            answer_contains (list[str] | Unset): case-insensitive
            answer_matches (None | str | Unset): a regular expression the answer matches (search)
            answer_not_contains (list[str] | Unset):
            answer_schema (ExpectAnswerSchemaType0 | None | Unset): the answer is JSON, valid against this JSON Schema
            approvals (list[str] | Unset): it asked before calling each of these
            judge (None | str | Unset): a rubric the agent's own model grades the answer against
            max_tool_calls (int | None | Unset):
            not_tools (list[str] | Unset): none of these was
            status (ExpectStatus | Unset):  Default: ExpectStatus.COMPLETED.
            tools (list[str] | Unset): all of these were called
     """

    answer_contains: list[str] | Unset = UNSET
    answer_matches: None | str | Unset = UNSET
    answer_not_contains: list[str] | Unset = UNSET
    answer_schema: ExpectAnswerSchemaType0 | None | Unset = UNSET
    approvals: list[str] | Unset = UNSET
    judge: None | str | Unset = UNSET
    max_tool_calls: int | None | Unset = UNSET
    not_tools: list[str] | Unset = UNSET
    status: ExpectStatus | Unset = ExpectStatus.COMPLETED
    tools: list[str] | Unset = UNSET





    def to_dict(self) -> dict[str, Any]:
        from ..models.expect_answer_schema_type_0 import ExpectAnswerSchemaType0 # noqa: PLC0415
        answer_contains: list[str] | Unset = UNSET
        if not isinstance(self.answer_contains, Unset):
            answer_contains = self.answer_contains



        answer_matches: None | str | Unset
        if isinstance(self.answer_matches, Unset):
            answer_matches = UNSET
        else:
            answer_matches = self.answer_matches

        answer_not_contains: list[str] | Unset = UNSET
        if not isinstance(self.answer_not_contains, Unset):
            answer_not_contains = self.answer_not_contains



        answer_schema: dict[str, Any] | None | Unset
        if isinstance(self.answer_schema, Unset):
            answer_schema = UNSET
        elif isinstance(self.answer_schema, ExpectAnswerSchemaType0):
            answer_schema = self.answer_schema.to_dict()
        else:
            answer_schema = self.answer_schema

        approvals: list[str] | Unset = UNSET
        if not isinstance(self.approvals, Unset):
            approvals = self.approvals



        judge: None | str | Unset
        if isinstance(self.judge, Unset):
            judge = UNSET
        else:
            judge = self.judge

        max_tool_calls: int | None | Unset
        if isinstance(self.max_tool_calls, Unset):
            max_tool_calls = UNSET
        else:
            max_tool_calls = self.max_tool_calls

        not_tools: list[str] | Unset = UNSET
        if not isinstance(self.not_tools, Unset):
            not_tools = self.not_tools



        status: str | Unset = UNSET
        if not isinstance(self.status, Unset):
            status = self.status.value


        tools: list[str] | Unset = UNSET
        if not isinstance(self.tools, Unset):
            tools = self.tools




        field_dict: dict[str, Any] = {}

        field_dict.update({
        })
        if answer_contains is not UNSET:
            field_dict["answer_contains"] = answer_contains
        if answer_matches is not UNSET:
            field_dict["answer_matches"] = answer_matches
        if answer_not_contains is not UNSET:
            field_dict["answer_not_contains"] = answer_not_contains
        if answer_schema is not UNSET:
            field_dict["answer_schema"] = answer_schema
        if approvals is not UNSET:
            field_dict["approvals"] = approvals
        if judge is not UNSET:
            field_dict["judge"] = judge
        if max_tool_calls is not UNSET:
            field_dict["max_tool_calls"] = max_tool_calls
        if not_tools is not UNSET:
            field_dict["not_tools"] = not_tools
        if status is not UNSET:
            field_dict["status"] = status
        if tools is not UNSET:
            field_dict["tools"] = tools

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.expect_answer_schema_type_0 import ExpectAnswerSchemaType0 # noqa: PLC0415
        d = dict(src_dict)
        answer_contains = cast(list[str], d.pop("answer_contains", UNSET))


        def _parse_answer_matches(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        answer_matches = _parse_answer_matches(d.pop("answer_matches", UNSET))


        answer_not_contains = cast(list[str], d.pop("answer_not_contains", UNSET))


        def _parse_answer_schema(data: object) -> ExpectAnswerSchemaType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                answer_schema_type_0 = ExpectAnswerSchemaType0.from_dict(data)



                return answer_schema_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ExpectAnswerSchemaType0 | None | Unset, data)

        answer_schema = _parse_answer_schema(d.pop("answer_schema", UNSET))


        approvals = cast(list[str], d.pop("approvals", UNSET))


        def _parse_judge(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        judge = _parse_judge(d.pop("judge", UNSET))


        def _parse_max_tool_calls(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        max_tool_calls = _parse_max_tool_calls(d.pop("max_tool_calls", UNSET))


        not_tools = cast(list[str], d.pop("not_tools", UNSET))


        _status = d.pop("status", UNSET)
        status: ExpectStatus | Unset
        if isinstance(_status,  Unset):
            status = UNSET
        else:
            status = ExpectStatus(_status)




        tools = cast(list[str], d.pop("tools", UNSET))


        expect = cls(
            answer_contains=answer_contains,
            answer_matches=answer_matches,
            answer_not_contains=answer_not_contains,
            answer_schema=answer_schema,
            approvals=approvals,
            judge=judge,
            max_tool_calls=max_tool_calls,
            not_tools=not_tools,
            status=status,
            tools=tools,
        )

        return expect

