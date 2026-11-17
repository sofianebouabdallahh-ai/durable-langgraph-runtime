from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.problem import Problem
from ...models.validation_problem import ValidationProblem
from ...types import UNSET, Unset
from typing import cast
from uuid import UUID



def _get_kwargs(
    run_id: UUID,
    *,
    after_seq: int | None | Unset = UNSET,
    last_event_id: None | str | Unset = UNSET,

) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    if not isinstance(last_event_id, Unset):
        headers["last-event-id"] = last_event_id



    

    params: dict[str, Any] = {}

    json_after_seq: int | None | Unset
    if isinstance(after_seq, Unset):
        json_after_seq = UNSET
    else:
        json_after_seq = after_seq
    params["after_seq"] = json_after_seq


    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}


    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/runs/{run_id}/stream".format(run_id=quote(str(run_id), safe=""),),
        "params": params,
    }


    _kwargs["headers"] = headers
    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Any | Problem | ValidationProblem:
    if response.status_code == 200:
        response_200 = cast(Any, None)
        return response_200

    if response.status_code == 404:
        response_404 = Problem.from_dict(response.json())



        return response_404

    if response.status_code == 422:
        response_422 = ValidationProblem.from_dict(response.json())



        return response_422

    if response.status_code == 503:
        response_503 = Problem.from_dict(response.json())



        return response_503

    response_default = Problem.from_dict(response.json())



    return response_default



def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[Any | Problem | ValidationProblem]:
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
    after_seq: int | None | Unset = UNSET,
    last_event_id: None | str | Unset = UNSET,

) -> Response[Any | Problem | ValidationProblem]:
    """ Live event stream (SSE)

     Replays persisted events after `Last-Event-ID` (or `after_seq`), then streams live ones from any
    replica (R2.5). Persisted events carry `id: <seq>`. A `: ping` comment is sent when idle; the stream
    closes after the run's terminal event; on replica shutdown an `event: reconnect` tells the client to
    reconnect with its Last-Event-ID.

    Args:
        run_id (UUID):
        after_seq (int | None | Unset):
        last_event_id (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | Problem | ValidationProblem]
     """


    kwargs = _get_kwargs(
        run_id=run_id,
after_seq=after_seq,
last_event_id=last_event_id,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    run_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    after_seq: int | None | Unset = UNSET,
    last_event_id: None | str | Unset = UNSET,

) -> Any | Problem | ValidationProblem | None:
    """ Live event stream (SSE)

     Replays persisted events after `Last-Event-ID` (or `after_seq`), then streams live ones from any
    replica (R2.5). Persisted events carry `id: <seq>`. A `: ping` comment is sent when idle; the stream
    closes after the run's terminal event; on replica shutdown an `event: reconnect` tells the client to
    reconnect with its Last-Event-ID.

    Args:
        run_id (UUID):
        after_seq (int | None | Unset):
        last_event_id (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | Problem | ValidationProblem
     """


    return sync_detailed(
        run_id=run_id,
client=client,
after_seq=after_seq,
last_event_id=last_event_id,

    ).parsed

async def asyncio_detailed(
    run_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    after_seq: int | None | Unset = UNSET,
    last_event_id: None | str | Unset = UNSET,

) -> Response[Any | Problem | ValidationProblem]:
    """ Live event stream (SSE)

     Replays persisted events after `Last-Event-ID` (or `after_seq`), then streams live ones from any
    replica (R2.5). Persisted events carry `id: <seq>`. A `: ping` comment is sent when idle; the stream
    closes after the run's terminal event; on replica shutdown an `event: reconnect` tells the client to
    reconnect with its Last-Event-ID.

    Args:
        run_id (UUID):
        after_seq (int | None | Unset):
        last_event_id (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | Problem | ValidationProblem]
     """


    kwargs = _get_kwargs(
        run_id=run_id,
after_seq=after_seq,
last_event_id=last_event_id,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    run_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    after_seq: int | None | Unset = UNSET,
    last_event_id: None | str | Unset = UNSET,

) -> Any | Problem | ValidationProblem | None:
    """ Live event stream (SSE)

     Replays persisted events after `Last-Event-ID` (or `after_seq`), then streams live ones from any
    replica (R2.5). Persisted events carry `id: <seq>`. A `: ping` comment is sent when idle; the stream
    closes after the run's terminal event; on replica shutdown an `event: reconnect` tells the client to
    reconnect with its Last-Event-ID.

    Args:
        run_id (UUID):
        after_seq (int | None | Unset):
        last_event_id (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | Problem | ValidationProblem
     """


    return (await asyncio_detailed(
        run_id=run_id,
client=client,
after_seq=after_seq,
last_event_id=last_event_id,

    )).parsed
