from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.problem import Problem
from ...models.saved_view import SavedView
from ...models.validation_problem import ValidationProblem
from typing import cast
from uuid import UUID



def _get_kwargs(
    skill_id: UUID,
    *,
    filename: str,

) -> dict[str, Any]:
    

    

    params: dict[str, Any] = {}

    params["filename"] = filename


    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}


    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/skills/{skill_id}/upload".format(skill_id=quote(str(skill_id), safe=""),),
        "params": params,
    }


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
    filename: str,

) -> Response[Problem | SavedView | ValidationProblem]:
    """ A new version of this skill from an upload (same name)

    Args:
        skill_id (UUID):
        filename (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Problem | SavedView | ValidationProblem]
     """


    kwargs = _get_kwargs(
        skill_id=skill_id,
filename=filename,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    skill_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    filename: str,

) -> Problem | SavedView | ValidationProblem | None:
    """ A new version of this skill from an upload (same name)

    Args:
        skill_id (UUID):
        filename (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Problem | SavedView | ValidationProblem
     """


    return sync_detailed(
        skill_id=skill_id,
client=client,
filename=filename,

    ).parsed

async def asyncio_detailed(
    skill_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    filename: str,

) -> Response[Problem | SavedView | ValidationProblem]:
    """ A new version of this skill from an upload (same name)

    Args:
        skill_id (UUID):
        filename (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Problem | SavedView | ValidationProblem]
     """


    kwargs = _get_kwargs(
        skill_id=skill_id,
filename=filename,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    skill_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    filename: str,

) -> Problem | SavedView | ValidationProblem | None:
    """ A new version of this skill from an upload (same name)

    Args:
        skill_id (UUID):
        filename (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Problem | SavedView | ValidationProblem
     """


    return (await asyncio_detailed(
        skill_id=skill_id,
client=client,
filename=filename,

    )).parsed
