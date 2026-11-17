from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.events_page import EventsPage
from ...models.problem import Problem
from ...models.validation_problem import ValidationProblem
from ...types import UNSET, Unset
from typing import cast
from uuid import UUID



def _get_kwargs(
    run_id: UUID,
    *,
    after_seq: int | Unset = 0,
    limit: int | Unset = 100,

) -> dict[str, Any]:
    

    

    params: dict[str, Any] = {}

    params["after_seq"] = after_seq

    params["limit"] = limit


    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}


    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/runs/{run_id}/events".format(run_id=quote(str(run_id), safe=""),),
        "params": params,
    }


    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> EventsPage | Problem | ValidationProblem:
    if response.status_code == 200:
        response_200 = EventsPage.from_dict(response.json())



        return response_200

    if response.status_code == 404:
        response_404 = Problem.from_dict(response.json())



        return response_404

    if response.status_code == 422:
        response_422 = ValidationProblem.from_dict(response.json())



        return response_422

    response_default = Problem.from_dict(response.json())



    return response_default



def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[EventsPage | Problem | ValidationProblem]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    run_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    after_seq: int | Unset = 0,
    limit: int | Unset = 100,

) -> Response[EventsPage | Problem | ValidationProblem]:
    """ Replay persisted events

    Args:
        run_id (UUID):
        after_seq (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 100.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EventsPage | Problem | ValidationProblem]
     """


    kwargs = _get_kwargs(
        run_id=run_id,
after_seq=after_seq,
limit=limit,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    run_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    after_seq: int | Unset = 0,
    limit: int | Unset = 100,

) -> EventsPage | Problem | ValidationProblem | None:
    """ Replay persisted events

    Args:
        run_id (UUID):
        after_seq (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 100.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EventsPage | Problem | ValidationProblem
     """


    return sync_detailed(
        run_id=run_id,
client=client,
after_seq=after_seq,
limit=limit,

    ).parsed

async def asyncio_detailed(
    run_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    after_seq: int | Unset = 0,
    limit: int | Unset = 100,

) -> Response[EventsPage | Problem | ValidationProblem]:
    """ Replay persisted events

    Args:
        run_id (UUID):
        after_seq (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 100.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EventsPage | Problem | ValidationProblem]
     """


    kwargs = _get_kwargs(
        run_id=run_id,
after_seq=after_seq,
limit=limit,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    run_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    after_seq: int | Unset = 0,
    limit: int | Unset = 100,

) -> EventsPage | Problem | ValidationProblem | None:
    """ Replay persisted events

    Args:
        run_id (UUID):
        after_seq (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 100.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EventsPage | Problem | ValidationProblem
     """


    return (await asyncio_detailed(
        run_id=run_id,
client=client,
after_seq=after_seq,
limit=limit,

    )).parsed
