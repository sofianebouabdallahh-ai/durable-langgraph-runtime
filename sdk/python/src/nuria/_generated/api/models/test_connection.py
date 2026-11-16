from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.problem import Problem
from ...models.test_request import TestRequest
from ...models.test_view import TestView
from ...models.validation_problem import ValidationProblem
from typing import cast
from uuid import UUID



def _get_kwargs(
    connection_id: UUID,
    *,
    body: TestRequest,

) -> dict[str, Any]:
    headers: dict[str, Any] = {}


    

    

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/models/connections/{connection_id}/test".format(connection_id=quote(str(connection_id), safe=""),),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Problem | TestView | ValidationProblem:
    if response.status_code == 200:
        response_200 = TestView.from_dict(response.json())



        return response_200

    if response.status_code == 404:
        response_404 = Problem.from_dict(response.json())



        return response_404

    if response.status_code == 422:
        response_422 = ValidationProblem.from_dict(response.json())



        return response_422

    response_default = Problem.from_dict(response.json())



    return response_default



def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[Problem | TestView | ValidationProblem]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    connection_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: TestRequest,

) -> Response[Problem | TestView | ValidationProblem]:
    """ Check it answers and uses tools

    Args:
        connection_id (UUID):
        body (TestRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Problem | TestView | ValidationProblem]
     """


    kwargs = _get_kwargs(
        connection_id=connection_id,
body=body,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    connection_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: TestRequest,

) -> Problem | TestView | ValidationProblem | None:
    """ Check it answers and uses tools

    Args:
        connection_id (UUID):
        body (TestRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Problem | TestView | ValidationProblem
     """


    return sync_detailed(
        connection_id=connection_id,
client=client,
body=body,

    ).parsed

async def asyncio_detailed(
    connection_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: TestRequest,

) -> Response[Problem | TestView | ValidationProblem]:
    """ Check it answers and uses tools

    Args:
        connection_id (UUID):
        body (TestRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Problem | TestView | ValidationProblem]
     """


    kwargs = _get_kwargs(
        connection_id=connection_id,
body=body,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    connection_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: TestRequest,

) -> Problem | TestView | ValidationProblem | None:
    """ Check it answers and uses tools

    Args:
        connection_id (UUID):
        body (TestRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Problem | TestView | ValidationProblem
     """


    return (await asyncio_detailed(
        connection_id=connection_id,
client=client,
body=body,

    )).parsed
