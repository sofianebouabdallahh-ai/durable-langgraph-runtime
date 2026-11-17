from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.draft_proposal import DraftProposal
from ...models.problem import Problem
from ...models.studio_agent_view import StudioAgentView
from ...models.validation_problem import ValidationProblem
from ...types import UNSET, Unset
from typing import cast



def _get_kwargs(
    *,
    body: DraftProposal,
    guide: bool | Unset = False,

) -> dict[str, Any]:
    headers: dict[str, Any] = {}


    

    params: dict[str, Any] = {}

    params["guide"] = guide


    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}


    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/studio/agents/from-proposal",
        "params": params,
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Problem | StudioAgentView | ValidationProblem:
    if response.status_code == 201:
        response_201 = StudioAgentView.from_dict(response.json())



        return response_201

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
    *,
    client: AuthenticatedClient | Client,
    body: DraftProposal,
    guide: bool | Unset = False,

) -> Response[Problem | StudioAgentView | ValidationProblem]:
    """ A new agent from a proposal

    Args:
        guide (bool | Unset): Built in Getting started: the guide's agent Default: False.
        body (DraftProposal):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Problem | StudioAgentView | ValidationProblem]
     """


    kwargs = _get_kwargs(
        body=body,
guide=guide,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    *,
    client: AuthenticatedClient | Client,
    body: DraftProposal,
    guide: bool | Unset = False,

) -> Problem | StudioAgentView | ValidationProblem | None:
    """ A new agent from a proposal

    Args:
        guide (bool | Unset): Built in Getting started: the guide's agent Default: False.
        body (DraftProposal):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Problem | StudioAgentView | ValidationProblem
     """


    return sync_detailed(
        client=client,
body=body,
guide=guide,

    ).parsed

async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: DraftProposal,
    guide: bool | Unset = False,

) -> Response[Problem | StudioAgentView | ValidationProblem]:
    """ A new agent from a proposal

    Args:
        guide (bool | Unset): Built in Getting started: the guide's agent Default: False.
        body (DraftProposal):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Problem | StudioAgentView | ValidationProblem]
     """


    kwargs = _get_kwargs(
        body=body,
guide=guide,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    body: DraftProposal,
    guide: bool | Unset = False,

) -> Problem | StudioAgentView | ValidationProblem | None:
    """ A new agent from a proposal

    Args:
        guide (bool | Unset): Built in Getting started: the guide's agent Default: False.
        body (DraftProposal):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Problem | StudioAgentView | ValidationProblem
     """


    return (await asyncio_detailed(
        client=client,
body=body,
guide=guide,

    )).parsed
