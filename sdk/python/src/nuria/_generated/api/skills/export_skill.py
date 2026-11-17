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
    skill_id: UUID,

) -> dict[str, Any]:
    

    

    

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/skills/{skill_id}/export".format(skill_id=quote(str(skill_id), safe=""),),
    }


    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Any | Problem | ValidationProblem:
    if response.status_code == 200:
        response_200 = response.json()
        return response_200

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
    skill_id: UUID,
    *,
    client: AuthenticatedClient | Client,

) -> Response[Any | Problem | ValidationProblem]:
    """ Download the skill's folder (zip)

    Args:
        skill_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | Problem | ValidationProblem]
     """


    kwargs = _get_kwargs(
        skill_id=skill_id,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    skill_id: UUID,
    *,
    client: AuthenticatedClient | Client,

) -> Any | Problem | ValidationProblem | None:
    """ Download the skill's folder (zip)

    Args:
        skill_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | Problem | ValidationProblem
     """


    return sync_detailed(
        skill_id=skill_id,
client=client,

    ).parsed

async def asyncio_detailed(
    skill_id: UUID,
    *,
    client: AuthenticatedClient | Client,

) -> Response[Any | Problem | ValidationProblem]:
    """ Download the skill's folder (zip)

    Args:
        skill_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | Problem | ValidationProblem]
     """


    kwargs = _get_kwargs(
        skill_id=skill_id,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    skill_id: UUID,
    *,
    client: AuthenticatedClient | Client,

) -> Any | Problem | ValidationProblem | None:
    """ Download the skill's folder (zip)

    Args:
        skill_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | Problem | ValidationProblem
     """


    return (await asyncio_detailed(
        skill_id=skill_id,
client=client,

    )).parsed
