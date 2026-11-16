from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.notifications_view import NotificationsView
from ...models.problem import Problem
from ...models.validation_problem import ValidationProblem
from ...types import UNSET, Unset
from typing import cast



def _get_kwargs(
    *,
    limit: int | Unset = 20,

) -> dict[str, Any]:
    

    

    params: dict[str, Any] = {}

    params["limit"] = limit


    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}


    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/notifications",
        "params": params,
    }


    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> NotificationsView | Problem | ValidationProblem:
    if response.status_code == 200:
        response_200 = NotificationsView.from_dict(response.json())



        return response_200

    if response.status_code == 422:
        response_422 = ValidationProblem.from_dict(response.json())



        return response_422

    response_default = Problem.from_dict(response.json())



    return response_default



def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[NotificationsView | Problem | ValidationProblem]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    limit: int | Unset = 20,

) -> Response[NotificationsView | Problem | ValidationProblem]:
    """ The latest notifications and their delivery

    Args:
        limit (int | Unset):  Default: 20.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[NotificationsView | Problem | ValidationProblem]
     """


    kwargs = _get_kwargs(
        limit=limit,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    *,
    client: AuthenticatedClient | Client,
    limit: int | Unset = 20,

) -> NotificationsView | Problem | ValidationProblem | None:
    """ The latest notifications and their delivery

    Args:
        limit (int | Unset):  Default: 20.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        NotificationsView | Problem | ValidationProblem
     """


    return sync_detailed(
        client=client,
limit=limit,

    ).parsed

async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    limit: int | Unset = 20,

) -> Response[NotificationsView | Problem | ValidationProblem]:
    """ The latest notifications and their delivery

    Args:
        limit (int | Unset):  Default: 20.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[NotificationsView | Problem | ValidationProblem]
     """


    kwargs = _get_kwargs(
        limit=limit,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    limit: int | Unset = 20,

) -> NotificationsView | Problem | ValidationProblem | None:
    """ The latest notifications and their delivery

    Args:
        limit (int | Unset):  Default: 20.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        NotificationsView | Problem | ValidationProblem
     """


    return (await asyncio_detailed(
        client=client,
limit=limit,

    )).parsed
