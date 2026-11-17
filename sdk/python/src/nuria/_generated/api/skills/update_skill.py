from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.edit_skill import EditSkill
from ...models.problem import Problem
from ...models.saved_view import SavedView
from ...models.validation_problem import ValidationProblem
from typing import cast
from uuid import UUID



def _get_kwargs(
    skill_id: UUID,
    *,
    body: EditSkill,

) -> dict[str, Any]:
    headers: dict[str, Any] = {}


    

    

    _kwargs: dict[str, Any] = {
        "method": "patch",
        "url": "/skills/{skill_id}".format(skill_id=quote(str(skill_id), safe=""),),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Problem | SavedView | ValidationProblem:
    if response.status_code == 200:
        response_200 = SavedView.from_dict(response.json())



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



def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[Problem | SavedView | ValidationProblem]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    skill_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: EditSkill,

) -> Response[Problem | SavedView | ValidationProblem]:
    """ Edit (saves a new version; the name stays)

    Args:
        skill_id (UUID):
        body (EditSkill):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Problem | SavedView | ValidationProblem]
     """


    kwargs = _get_kwargs(
        skill_id=skill_id,
body=body,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    skill_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: EditSkill,

) -> Problem | SavedView | ValidationProblem | None:
    """ Edit (saves a new version; the name stays)

    Args:
        skill_id (UUID):
        body (EditSkill):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Problem | SavedView | ValidationProblem
     """


    return sync_detailed(
        skill_id=skill_id,
client=client,
body=body,

    ).parsed

async def asyncio_detailed(
    skill_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: EditSkill,

) -> Response[Problem | SavedView | ValidationProblem]:
    """ Edit (saves a new version; the name stays)

    Args:
        skill_id (UUID):
        body (EditSkill):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Problem | SavedView | ValidationProblem]
     """


    kwargs = _get_kwargs(
        skill_id=skill_id,
body=body,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    skill_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: EditSkill,

) -> Problem | SavedView | ValidationProblem | None:
    """ Edit (saves a new version; the name stays)

    Args:
        skill_id (UUID):
        body (EditSkill):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Problem | SavedView | ValidationProblem
     """


    return (await asyncio_detailed(
        skill_id=skill_id,
client=client,
body=body,

    )).parsed
