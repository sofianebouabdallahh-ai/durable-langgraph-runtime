from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.problem import Problem
from ...models.publish_request import PublishRequest
from ...models.studio_agent_view import StudioAgentView
from ...models.validation_problem import ValidationProblem
from typing import cast
from uuid import UUID



def _get_kwargs(
    agent_id: UUID,
    *,
    body: PublishRequest,

) -> dict[str, Any]:
    headers: dict[str, Any] = {}


    

    

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/studio/agents/{agent_id}/publish".format(agent_id=quote(str(agent_id), safe=""),),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Problem | StudioAgentView | ValidationProblem:
    if response.status_code == 200:
        response_200 = StudioAgentView.from_dict(response.json())



        return response_200

    if response.status_code == 404:
        response_404 = Problem.from_dict(response.json())



        return response_404

    if response.status_code == 409:
        response_409 = Problem.from_dict(response.json())



        return response_409

    if response.status_code == 422:
        response_422 = ValidationProblem.from_dict(response.json())



        return response_422

    response_default = Problem.from_dict(response.json())



    return response_default



def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[Problem | StudioAgentView | ValidationProblem]:
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
    body: PublishRequest,

) -> Response[Problem | StudioAgentView | ValidationProblem]:
    """ Publish the draft as an immutable version (needs a test)

    Args:
        agent_id (UUID):
        body (PublishRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Problem | StudioAgentView | ValidationProblem]
     """


    kwargs = _get_kwargs(
        agent_id=agent_id,
body=body,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    agent_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: PublishRequest,

) -> Problem | StudioAgentView | ValidationProblem | None:
    """ Publish the draft as an immutable version (needs a test)

    Args:
        agent_id (UUID):
        body (PublishRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Problem | StudioAgentView | ValidationProblem
     """


    return sync_detailed(
        agent_id=agent_id,
client=client,
body=body,

    ).parsed

async def asyncio_detailed(
    agent_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: PublishRequest,

) -> Response[Problem | StudioAgentView | ValidationProblem]:
    """ Publish the draft as an immutable version (needs a test)

    Args:
        agent_id (UUID):
        body (PublishRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Problem | StudioAgentView | ValidationProblem]
     """


    kwargs = _get_kwargs(
        agent_id=agent_id,
body=body,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    agent_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: PublishRequest,

) -> Problem | StudioAgentView | ValidationProblem | None:
    """ Publish the draft as an immutable version (needs a test)

    Args:
        agent_id (UUID):
        body (PublishRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Problem | StudioAgentView | ValidationProblem
     """


    return (await asyncio_detailed(
        agent_id=agent_id,
client=client,
body=body,

    )).parsed
