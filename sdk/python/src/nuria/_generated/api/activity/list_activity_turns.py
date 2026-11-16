from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.list_activity_turns_range import ListActivityTurnsRange
from ...models.problem import Problem
from ...models.turn_row import TurnRow
from ...models.validation_problem import ValidationProblem
from ...types import UNSET, Unset
from typing import cast
from uuid import UUID
import datetime



def _get_kwargs(
    *,
    range_: ListActivityTurnsRange | Unset = ListActivityTurnsRange.VALUE_1,
    agent: None | str | Unset = UNSET,
    include_tests: bool | Unset = False,
    status: None | str | Unset = UNSET,
    reason: None | str | Unset = UNSET,
    session_id: None | Unset | UUID = UNSET,
    before: datetime.datetime | None | Unset = UNSET,
    limit: int | Unset = 50,

) -> dict[str, Any]:
    

    

    params: dict[str, Any] = {}

    json_range_: str | Unset = UNSET
    if not isinstance(range_, Unset):
        json_range_ = range_.value

    params["range"] = json_range_

    json_agent: None | str | Unset
    if isinstance(agent, Unset):
        json_agent = UNSET
    else:
        json_agent = agent
    params["agent"] = json_agent

    params["include_tests"] = include_tests

    json_status: None | str | Unset
    if isinstance(status, Unset):
        json_status = UNSET
    else:
        json_status = status
    params["status"] = json_status

    json_reason: None | str | Unset
    if isinstance(reason, Unset):
        json_reason = UNSET
    else:
        json_reason = reason
    params["reason"] = json_reason

    json_session_id: None | str | Unset
    if isinstance(session_id, Unset):
        json_session_id = UNSET
    elif isinstance(session_id, UUID):
        json_session_id = str(session_id)
    else:
        json_session_id = session_id
    params["session_id"] = json_session_id

    json_before: None | str | Unset
    if isinstance(before, Unset):
        json_before = UNSET
    elif isinstance(before, datetime.datetime):
        json_before = before.isoformat()
    else:
        json_before = before
    params["before"] = json_before

    params["limit"] = limit


    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}


    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/activity/turns",
        "params": params,
    }


    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Problem | ValidationProblem | list[TurnRow]:
    if response.status_code == 200:
        response_200 = []
        _response_200 = response.json()
        for response_200_item_data in (_response_200):
            response_200_item = TurnRow.from_dict(response_200_item_data)



            response_200.append(response_200_item)

        return response_200

    if response.status_code == 422:
        response_422 = ValidationProblem.from_dict(response.json())



        return response_422

    response_default = Problem.from_dict(response.json())



    return response_default



def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[Problem | ValidationProblem | list[TurnRow]]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    range_: ListActivityTurnsRange | Unset = ListActivityTurnsRange.VALUE_1,
    agent: None | str | Unset = UNSET,
    include_tests: bool | Unset = False,
    status: None | str | Unset = UNSET,
    reason: None | str | Unset = UNSET,
    session_id: None | Unset | UUID = UNSET,
    before: datetime.datetime | None | Unset = UNSET,
    limit: int | Unset = 50,

) -> Response[Problem | ValidationProblem | list[TurnRow]]:
    """ Turns, newest first

    Args:
        range_ (ListActivityTurnsRange | Unset): 24h, 7d or 30d Default:
            ListActivityTurnsRange.VALUE_1.
        agent (None | str | Unset): One agent (its name); all by default
        include_tests (bool | Unset): Count test chats from the Studio too Default: False.
        status (None | str | Unset): e.g. failed
        reason (None | str | Unset): e.g. timeout
        session_id (None | Unset | UUID):
        before (datetime.datetime | None | Unset): Page: created_at <
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Problem | ValidationProblem | list[TurnRow]]
     """


    kwargs = _get_kwargs(
        range_=range_,
agent=agent,
include_tests=include_tests,
status=status,
reason=reason,
session_id=session_id,
before=before,
limit=limit,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    *,
    client: AuthenticatedClient | Client,
    range_: ListActivityTurnsRange | Unset = ListActivityTurnsRange.VALUE_1,
    agent: None | str | Unset = UNSET,
    include_tests: bool | Unset = False,
    status: None | str | Unset = UNSET,
    reason: None | str | Unset = UNSET,
    session_id: None | Unset | UUID = UNSET,
    before: datetime.datetime | None | Unset = UNSET,
    limit: int | Unset = 50,

) -> Problem | ValidationProblem | list[TurnRow] | None:
    """ Turns, newest first

    Args:
        range_ (ListActivityTurnsRange | Unset): 24h, 7d or 30d Default:
            ListActivityTurnsRange.VALUE_1.
        agent (None | str | Unset): One agent (its name); all by default
        include_tests (bool | Unset): Count test chats from the Studio too Default: False.
        status (None | str | Unset): e.g. failed
        reason (None | str | Unset): e.g. timeout
        session_id (None | Unset | UUID):
        before (datetime.datetime | None | Unset): Page: created_at <
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Problem | ValidationProblem | list[TurnRow]
     """


    return sync_detailed(
        client=client,
range_=range_,
agent=agent,
include_tests=include_tests,
status=status,
reason=reason,
session_id=session_id,
before=before,
limit=limit,

    ).parsed

async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    range_: ListActivityTurnsRange | Unset = ListActivityTurnsRange.VALUE_1,
    agent: None | str | Unset = UNSET,
    include_tests: bool | Unset = False,
    status: None | str | Unset = UNSET,
    reason: None | str | Unset = UNSET,
    session_id: None | Unset | UUID = UNSET,
    before: datetime.datetime | None | Unset = UNSET,
    limit: int | Unset = 50,

) -> Response[Problem | ValidationProblem | list[TurnRow]]:
    """ Turns, newest first

    Args:
        range_ (ListActivityTurnsRange | Unset): 24h, 7d or 30d Default:
            ListActivityTurnsRange.VALUE_1.
        agent (None | str | Unset): One agent (its name); all by default
        include_tests (bool | Unset): Count test chats from the Studio too Default: False.
        status (None | str | Unset): e.g. failed
        reason (None | str | Unset): e.g. timeout
        session_id (None | Unset | UUID):
        before (datetime.datetime | None | Unset): Page: created_at <
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Problem | ValidationProblem | list[TurnRow]]
     """


    kwargs = _get_kwargs(
        range_=range_,
agent=agent,
include_tests=include_tests,
status=status,
reason=reason,
session_id=session_id,
before=before,
limit=limit,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    range_: ListActivityTurnsRange | Unset = ListActivityTurnsRange.VALUE_1,
    agent: None | str | Unset = UNSET,
    include_tests: bool | Unset = False,
    status: None | str | Unset = UNSET,
    reason: None | str | Unset = UNSET,
    session_id: None | Unset | UUID = UNSET,
    before: datetime.datetime | None | Unset = UNSET,
    limit: int | Unset = 50,

) -> Problem | ValidationProblem | list[TurnRow] | None:
    """ Turns, newest first

    Args:
        range_ (ListActivityTurnsRange | Unset): 24h, 7d or 30d Default:
            ListActivityTurnsRange.VALUE_1.
        agent (None | str | Unset): One agent (its name); all by default
        include_tests (bool | Unset): Count test chats from the Studio too Default: False.
        status (None | str | Unset): e.g. failed
        reason (None | str | Unset): e.g. timeout
        session_id (None | Unset | UUID):
        before (datetime.datetime | None | Unset): Page: created_at <
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Problem | ValidationProblem | list[TurnRow]
     """


    return (await asyncio_detailed(
        client=client,
range_=range_,
agent=agent,
include_tests=include_tests,
status=status,
reason=reason,
session_id=session_id,
before=before,
limit=limit,

    )).parsed
