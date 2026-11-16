from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.problem import Problem
from ...models.tests_view import TestsView
from ...models.validation_problem import ValidationProblem
from typing import cast
from uuid import UUID



def _get_kwargs(
    agent_id: UUID,

) -> dict[str, Any]:
    

    

    

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/studio/agents/{agent_id}/tests".format(agent_id=quote(str(agent_id), safe=""),),
    }


    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Problem | TestsView | ValidationProblem:
    if response.status_code == 200:
        response_200 = TestsView.from_dict(response.json())



        return response_200

    if response.status_code == 404:
        response_404 = Problem.from_dict(response.json())



        return response_404

    if response.status_code == 422:
        response_422 = ValidationProblem.from_dict(response.json())



        return response_422

    response_default = Problem.from_dict(response.json())



    return response_default



def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[Problem | TestsView | ValidationProblem]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    agent_id: UUID,
    *,
    client: AuthenticatedClient | Client,

) -> Response[Problem | TestsView | ValidationProblem]:
    """ Its tests, each with its latest result

    Args:
        agent_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Problem | TestsView | ValidationProblem]
     """


    kwargs = _get_kwargs(
        agent_id=agent_id,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    agent_id: UUID,
    *,
    client: AuthenticatedClient | Client,

) -> Problem | TestsView | ValidationProblem | None:
    """ Its tests, each with its latest result

    Args:
        agent_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Problem | TestsView | ValidationProblem
     """


    return sync_detailed(
        agent_id=agent_id,
client=client,

    ).parsed

async def asyncio_detailed(
    agent_id: UUID,
    *,
    client: AuthenticatedClient | Client,

) -> Response[Problem | TestsView | ValidationProblem]:
    """ Its tests, each with its latest result

    Args:
        agent_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Problem | TestsView | ValidationProblem]
     """


    kwargs = _get_kwargs(
        agent_id=agent_id,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    agent_id: UUID,
    *,
    client: AuthenticatedClient | Client,

) -> Problem | TestsView | ValidationProblem | None:
    """ Its tests, each with its latest result

    Args:
        agent_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Problem | TestsView | ValidationProblem
     """


    return (await asyncio_detailed(
        agent_id=agent_id,
client=client,

    )).parsed
