from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.problem import Problem
from ...models.validation_problem import ValidationProblem
from ...types import UNSET, Unset
from typing import cast



def _get_kwargs(
    *,
    action: None | str | Unset = UNSET,
    target_type: None | str | Unset = UNSET,
    target_id: None | str | Unset = UNSET,

) -> dict[str, Any]:
    

    

    params: dict[str, Any] = {}

    json_action: None | str | Unset
    if isinstance(action, Unset):
        json_action = UNSET
    else:
        json_action = action
    params["action"] = json_action

    json_target_type: None | str | Unset
    if isinstance(target_type, Unset):
        json_target_type = UNSET
    else:
        json_target_type = target_type
    params["target_type"] = json_target_type

    json_target_id: None | str | Unset
    if isinstance(target_id, Unset):
        json_target_id = UNSET
    else:
        json_target_id = target_id
    params["target_id"] = json_target_id


    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}


    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/audit.csv",
        "params": params,
    }


    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Any | Problem | ValidationProblem:
    if response.status_code == 200:
        response_200 = cast(Any, None)
        return response_200

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
    *,
    client: AuthenticatedClient | Client,
    action: None | str | Unset = UNSET,
    target_type: None | str | Unset = UNSET,
    target_id: None | str | Unset = UNSET,

) -> Response[Any | Problem | ValidationProblem]:
    """ The trail as a CSV file

    Args:
        action (None | str | Unset): e.g. agent.published
        target_type (None | str | Unset): e.g. agent
        target_id (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | Problem | ValidationProblem]
     """


    kwargs = _get_kwargs(
        action=action,
target_type=target_type,
target_id=target_id,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    *,
    client: AuthenticatedClient | Client,
    action: None | str | Unset = UNSET,
    target_type: None | str | Unset = UNSET,
    target_id: None | str | Unset = UNSET,

) -> Any | Problem | ValidationProblem | None:
    """ The trail as a CSV file

    Args:
        action (None | str | Unset): e.g. agent.published
        target_type (None | str | Unset): e.g. agent
        target_id (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | Problem | ValidationProblem
     """


    return sync_detailed(
        client=client,
action=action,
target_type=target_type,
target_id=target_id,

    ).parsed

async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    action: None | str | Unset = UNSET,
    target_type: None | str | Unset = UNSET,
    target_id: None | str | Unset = UNSET,

) -> Response[Any | Problem | ValidationProblem]:
    """ The trail as a CSV file

    Args:
        action (None | str | Unset): e.g. agent.published
        target_type (None | str | Unset): e.g. agent
        target_id (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | Problem | ValidationProblem]
     """


    kwargs = _get_kwargs(
        action=action,
target_type=target_type,
target_id=target_id,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    action: None | str | Unset = UNSET,
    target_type: None | str | Unset = UNSET,
    target_id: None | str | Unset = UNSET,

) -> Any | Problem | ValidationProblem | None:
    """ The trail as a CSV file

    Args:
        action (None | str | Unset): e.g. agent.published
        target_type (None | str | Unset): e.g. agent
        target_id (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | Problem | ValidationProblem
     """


    return (await asyncio_detailed(
        client=client,
action=action,
target_type=target_type,
target_id=target_id,

    )).parsed
