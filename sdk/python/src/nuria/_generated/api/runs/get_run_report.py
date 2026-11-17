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
    include_chat: bool | Unset = False,

) -> dict[str, Any]:
    

    

    params: dict[str, Any] = {}

    params["include_chat"] = include_chat


    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}


    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/runs/{run_id}/report".format(run_id=quote(str(run_id), safe=""),),
        "params": params,
    }


    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Problem | ValidationProblem:
    if response.status_code == 404:
        response_404 = Problem.from_dict(response.json())



        return response_404

    if response.status_code == 422:
        response_422 = ValidationProblem.from_dict(response.json())



        return response_422

    response_default = Problem.from_dict(response.json())



    return response_default



def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[Problem | ValidationProblem]:
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
    include_chat: bool | Unset = False,

) -> Response[Problem | ValidationProblem]:
    """ A zip to attach to a bug report (phase L5)

     README, the timeline (structural fields only unless `include_chat`), the agent's definition when
    it's one you made, and the chat only if `include_chat`. Nothing is uploaded anywhere: the person
    downloads it.

    Args:
        run_id (UUID):
        include_chat (bool | Unset):  Default: False.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Problem | ValidationProblem]
     """


    kwargs = _get_kwargs(
        run_id=run_id,
include_chat=include_chat,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    run_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    include_chat: bool | Unset = False,

) -> Problem | ValidationProblem | None:
    """ A zip to attach to a bug report (phase L5)

     README, the timeline (structural fields only unless `include_chat`), the agent's definition when
    it's one you made, and the chat only if `include_chat`. Nothing is uploaded anywhere: the person
    downloads it.

    Args:
        run_id (UUID):
        include_chat (bool | Unset):  Default: False.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Problem | ValidationProblem
     """


    return sync_detailed(
        run_id=run_id,
client=client,
include_chat=include_chat,

    ).parsed

async def asyncio_detailed(
    run_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    include_chat: bool | Unset = False,

) -> Response[Problem | ValidationProblem]:
    """ A zip to attach to a bug report (phase L5)

     README, the timeline (structural fields only unless `include_chat`), the agent's definition when
    it's one you made, and the chat only if `include_chat`. Nothing is uploaded anywhere: the person
    downloads it.

    Args:
        run_id (UUID):
        include_chat (bool | Unset):  Default: False.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Problem | ValidationProblem]
     """


    kwargs = _get_kwargs(
        run_id=run_id,
include_chat=include_chat,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    run_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    include_chat: bool | Unset = False,

) -> Problem | ValidationProblem | None:
    """ A zip to attach to a bug report (phase L5)

     README, the timeline (structural fields only unless `include_chat`), the agent's definition when
    it's one you made, and the chat only if `include_chat`. Nothing is uploaded anywhere: the person
    downloads it.

    Args:
        run_id (UUID):
        include_chat (bool | Unset):  Default: False.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Problem | ValidationProblem
     """


    return (await asyncio_detailed(
        run_id=run_id,
client=client,
include_chat=include_chat,

    )).parsed
