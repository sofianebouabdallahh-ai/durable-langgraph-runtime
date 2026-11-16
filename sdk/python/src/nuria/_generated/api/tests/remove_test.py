from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.problem import Problem
from ...models.validation_problem import ValidationProblem
from typing import cast
from uuid import UUID



def _get_kwargs(
    agent_id: UUID,
    case_id: UUID,

) -> dict[str, Any]:
    

    

    

    _kwargs: dict[str, Any] = {
        "method": "delete",
        "url": "/studio/agents/{agent_id}/tests/{case_id}".format(agent_id=quote(str(agent_id), safe=""),case_id=quote(str(case_id), safe=""),),
    }


    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Any | Problem | ValidationProblem:
    if response.status_code == 204:
        response_204 = cast(Any, None)
        return response_204

    if response.status_code == 404:
        response_404 = Problem.from_dict(response.json())



        return response_404

    if response.status_code == 422:
        response_422 = ValidationProblem.from_dict(response.json())



        return response_422

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
    agent_id: UUID,
    case_id: UUID,
    *,
    client: AuthenticatedClient | Client,

) -> Response[Any | Problem | ValidationProblem]:
    """ Remove a test

    Args:
        agent_id (UUID):
        case_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | Problem | ValidationProblem]
     """


    kwargs = _get_kwargs(
        agent_id=agent_id,
case_id=case_id,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    agent_id: UUID,
    case_id: UUID,
    *,
    client: AuthenticatedClient | Client,

) -> Any | Problem | ValidationProblem | None:
    """ Remove a test

    Args:
        agent_id (UUID):
        case_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | Problem | ValidationProblem
     """


    return sync_detailed(
        agent_id=agent_id,
case_id=case_id,
client=client,

    ).parsed

async def asyncio_detailed(
    agent_id: UUID,
    case_id: UUID,
    *,
    client: AuthenticatedClient | Client,

) -> Response[Any | Problem | ValidationProblem]:
    """ Remove a test

    Args:
        agent_id (UUID):
        case_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | Problem | ValidationProblem]
     """


    kwargs = _get_kwargs(
        agent_id=agent_id,
case_id=case_id,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    agent_id: UUID,
    case_id: UUID,
    *,
    client: AuthenticatedClient | Client,

) -> Any | Problem | ValidationProblem | None:
    """ Remove a test

    Args:
        agent_id (UUID):
        case_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | Problem | ValidationProblem
     """


    return (await asyncio_detailed(
        agent_id=agent_id,
case_id=case_id,
client=client,

    )).parsed
