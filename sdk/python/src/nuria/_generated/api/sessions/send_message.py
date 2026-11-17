from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.problem import Problem
from ...models.send_message_request import SendMessageRequest
from ...models.turn_accepted import TurnAccepted
from ...models.validation_problem import ValidationProblem
from ...types import UNSET, Unset
from typing import cast
from uuid import UUID



def _get_kwargs(
    session_id: UUID,
    *,
    body: SendMessageRequest,
    idempotency_key: None | str | Unset = UNSET,

) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    if not isinstance(idempotency_key, Unset):
        headers["idempotency-key"] = idempotency_key



    

    

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/sessions/{session_id}/messages".format(session_id=quote(str(session_id), safe=""),),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Problem | TurnAccepted | ValidationProblem:
    if response.status_code == 202:
        response_202 = TurnAccepted.from_dict(response.json())



        return response_202

    if response.status_code == 404:
        response_404 = Problem.from_dict(response.json())



        return response_404

    if response.status_code == 409:
        response_409 = Problem.from_dict(response.json())



        return response_409

    if response.status_code == 422:
        response_422 = ValidationProblem.from_dict(response.json())



        return response_422

    if response.status_code == 429:
        response_429 = Problem.from_dict(response.json())



        return response_429

    if response.status_code == 503:
        response_503 = Problem.from_dict(response.json())



        return response_503

    response_default = Problem.from_dict(response.json())



    return response_default



def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[Problem | TurnAccepted | ValidationProblem]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    session_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: SendMessageRequest,
    idempotency_key: None | str | Unset = UNSET,

) -> Response[Problem | TurnAccepted | ValidationProblem]:
    """ Send a message: starts a turn

    Args:
        session_id (UUID):
        idempotency_key (None | str | Unset): Retry-safe sends: the same key returns the same turn
        body (SendMessageRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Problem | TurnAccepted | ValidationProblem]
     """


    kwargs = _get_kwargs(
        session_id=session_id,
body=body,
idempotency_key=idempotency_key,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    session_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: SendMessageRequest,
    idempotency_key: None | str | Unset = UNSET,

) -> Problem | TurnAccepted | ValidationProblem | None:
    """ Send a message: starts a turn

    Args:
        session_id (UUID):
        idempotency_key (None | str | Unset): Retry-safe sends: the same key returns the same turn
        body (SendMessageRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Problem | TurnAccepted | ValidationProblem
     """


    return sync_detailed(
        session_id=session_id,
client=client,
body=body,
idempotency_key=idempotency_key,

    ).parsed

async def asyncio_detailed(
    session_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: SendMessageRequest,
    idempotency_key: None | str | Unset = UNSET,

) -> Response[Problem | TurnAccepted | ValidationProblem]:
    """ Send a message: starts a turn

    Args:
        session_id (UUID):
        idempotency_key (None | str | Unset): Retry-safe sends: the same key returns the same turn
        body (SendMessageRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Problem | TurnAccepted | ValidationProblem]
     """


    kwargs = _get_kwargs(
        session_id=session_id,
body=body,
idempotency_key=idempotency_key,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    session_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: SendMessageRequest,
    idempotency_key: None | str | Unset = UNSET,

) -> Problem | TurnAccepted | ValidationProblem | None:
    """ Send a message: starts a turn

    Args:
        session_id (UUID):
        idempotency_key (None | str | Unset): Retry-safe sends: the same key returns the same turn
        body (SendMessageRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Problem | TurnAccepted | ValidationProblem
     """


    return (await asyncio_detailed(
        session_id=session_id,
client=client,
body=body,
idempotency_key=idempotency_key,

    )).parsed
