from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.activity_view import ActivityView
from ...models.get_activity_range import GetActivityRange
from ...models.problem import Problem
from ...models.validation_problem import ValidationProblem
from ...types import UNSET, Unset
from typing import cast



def _get_kwargs(
    *,
    range_: GetActivityRange | Unset = GetActivityRange.VALUE_1,
    agent: None | str | Unset = UNSET,
    include_tests: bool | Unset = False,

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


    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}


    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/activity",
        "params": params,
    }


    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> ActivityView | Problem | ValidationProblem:
    if response.status_code == 200:
        response_200 = ActivityView.from_dict(response.json())



        return response_200

    if response.status_code == 422:
        response_422 = ValidationProblem.from_dict(response.json())



        return response_422

    response_default = Problem.from_dict(response.json())



    return response_default



def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[ActivityView | Problem | ValidationProblem]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    range_: GetActivityRange | Unset = GetActivityRange.VALUE_1,
    agent: None | str | Unset = UNSET,
    include_tests: bool | Unset = False,

) -> Response[ActivityView | Problem | ValidationProblem]:
    """ What all agents have been doing

    Args:
        range_ (GetActivityRange | Unset): 24h, 7d or 30d Default: GetActivityRange.VALUE_1.
        agent (None | str | Unset): One agent (its name); all by default
        include_tests (bool | Unset): Count test chats from the Studio too Default: False.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ActivityView | Problem | ValidationProblem]
     """


    kwargs = _get_kwargs(
        range_=range_,
agent=agent,
include_tests=include_tests,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    *,
    client: AuthenticatedClient | Client,
    range_: GetActivityRange | Unset = GetActivityRange.VALUE_1,
    agent: None | str | Unset = UNSET,
    include_tests: bool | Unset = False,

) -> ActivityView | Problem | ValidationProblem | None:
    """ What all agents have been doing

    Args:
        range_ (GetActivityRange | Unset): 24h, 7d or 30d Default: GetActivityRange.VALUE_1.
        agent (None | str | Unset): One agent (its name); all by default
        include_tests (bool | Unset): Count test chats from the Studio too Default: False.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ActivityView | Problem | ValidationProblem
     """


    return sync_detailed(
        client=client,
range_=range_,
agent=agent,
include_tests=include_tests,

    ).parsed

async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    range_: GetActivityRange | Unset = GetActivityRange.VALUE_1,
    agent: None | str | Unset = UNSET,
    include_tests: bool | Unset = False,

) -> Response[ActivityView | Problem | ValidationProblem]:
    """ What all agents have been doing

    Args:
        range_ (GetActivityRange | Unset): 24h, 7d or 30d Default: GetActivityRange.VALUE_1.
        agent (None | str | Unset): One agent (its name); all by default
        include_tests (bool | Unset): Count test chats from the Studio too Default: False.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ActivityView | Problem | ValidationProblem]
     """


    kwargs = _get_kwargs(
        range_=range_,
agent=agent,
include_tests=include_tests,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    range_: GetActivityRange | Unset = GetActivityRange.VALUE_1,
    agent: None | str | Unset = UNSET,
    include_tests: bool | Unset = False,

) -> ActivityView | Problem | ValidationProblem | None:
    """ What all agents have been doing

    Args:
        range_ (GetActivityRange | Unset): 24h, 7d or 30d Default: GetActivityRange.VALUE_1.
        agent (None | str | Unset): One agent (its name); all by default
        include_tests (bool | Unset): Count test chats from the Studio too Default: False.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ActivityView | Problem | ValidationProblem
     """


    return (await asyncio_detailed(
        client=client,
range_=range_,
agent=agent,
include_tests=include_tests,

    )).parsed
