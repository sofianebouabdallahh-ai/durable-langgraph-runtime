from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.assist_started import AssistStarted
from ...models.describe_request import DescribeRequest
from ...models.problem import Problem
from ...models.validation_problem import ValidationProblem
from typing import cast



def _get_kwargs(
    *,
    body: DescribeRequest,

) -> dict[str, Any]:
    headers: dict[str, Any] = {}


    

    

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/studio/describe",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> AssistStarted | Problem | ValidationProblem:
    if response.status_code == 202:
        response_202 = AssistStarted.from_dict(response.json())



        return response_202

    if response.status_code == 409:
        response_409 = Problem.from_dict(response.json())



        return response_409

    if response.status_code == 422:
        response_422 = ValidationProblem.from_dict(response.json())



        return response_422

    if response.status_code == 429:
        response_429 = Problem.from_dict(response.json())



        return response_429

    if response.status_code == 503:
        response_503 = Problem.from_dict(response.json())



        return response_503

    response_default = Problem.from_dict(response.json())



    return response_default



def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[AssistStarted | Problem | ValidationProblem]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: DescribeRequest,

) -> Response[AssistStarted | Problem | ValidationProblem]:
    """ Draft an agent from a description (the builder agent)

    Args:
        body (DescribeRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AssistStarted | Problem | ValidationProblem]
     """


    kwargs = _get_kwargs(
        body=body,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    *,
    client: AuthenticatedClient | Client,
    body: DescribeRequest,

) -> AssistStarted | Problem | ValidationProblem | None:
    """ Draft an agent from a description (the builder agent)

    Args:
        body (DescribeRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AssistStarted | Problem | ValidationProblem
     """


    return sync_detailed(
        client=client,
body=body,

    ).parsed

async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: DescribeRequest,

) -> Response[AssistStarted | Problem | ValidationProblem]:
    """ Draft an agent from a description (the builder agent)

    Args:
        body (DescribeRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AssistStarted | Problem | ValidationProblem]
     """


    kwargs = _get_kwargs(
        body=body,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    body: DescribeRequest,

) -> AssistStarted | Problem | ValidationProblem | None:
    """ Draft an agent from a description (the builder agent)

    Args:
        body (DescribeRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AssistStarted | Problem | ValidationProblem
     """


    return (await asyncio_detailed(
        client=client,
body=body,

    )).parsed
