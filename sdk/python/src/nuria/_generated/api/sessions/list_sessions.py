from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.list_sessions_status_type_0 import ListSessionsStatusType0
from ...models.problem import Problem
from ...models.session_view import SessionView
from ...models.validation_problem import ValidationProblem
from ...types import UNSET, Unset
from typing import cast
import datetime



def _get_kwargs(
    *,
    status: ListSessionsStatusType0 | None | Unset = UNSET,
    limit: int | Unset = 20,
    before: datetime.datetime | None | Unset = UNSET,

) -> dict[str, Any]:
    

    

    params: dict[str, Any] = {}

    json_status: None | str | Unset
    if isinstance(status, Unset):
        json_status = UNSET
    elif isinstance(status, ListSessionsStatusType0):
        json_status = status.value
    else:
        json_status = status
    params["status"] = json_status

    params["limit"] = limit

    json_before: None | str | Unset
    if isinstance(before, Unset):
        json_before = UNSET
    elif isinstance(before, datetime.datetime):
        json_before = before.isoformat()
    else:
        json_before = before
    params["before"] = json_before


    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}


    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/sessions",
        "params": params,
    }


    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Problem | ValidationProblem | list[SessionView]:
    if response.status_code == 200:
        response_200 = []
        _response_200 = response.json()
        for response_200_item_data in (_response_200):
            response_200_item = SessionView.from_dict(response_200_item_data)



            response_200.append(response_200_item)

        return response_200

    if response.status_code == 422:
        response_422 = ValidationProblem.from_dict(response.json())



        return response_422

    response_default = Problem.from_dict(response.json())



    return response_default



def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[Problem | ValidationProblem | list[SessionView]]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    status: ListSessionsStatusType0 | None | Unset = UNSET,
    limit: int | Unset = 20,
    before: datetime.datetime | None | Unset = UNSET,

) -> Response[Problem | ValidationProblem | list[SessionView]]:
    """ List sessions, newest activity first

    Args:
        status (ListSessionsStatusType0 | None | Unset):
        limit (int | Unset):  Default: 20.
        before (datetime.datetime | None | Unset): Page: last_activity_at <

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Problem | ValidationProblem | list[SessionView]]
     """


    kwargs = _get_kwargs(
        status=status,
limit=limit,
before=before,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    *,
    client: AuthenticatedClient | Client,
    status: ListSessionsStatusType0 | None | Unset = UNSET,
    limit: int | Unset = 20,
    before: datetime.datetime | None | Unset = UNSET,

) -> Problem | ValidationProblem | list[SessionView] | None:
    """ List sessions, newest activity first

    Args:
        status (ListSessionsStatusType0 | None | Unset):
        limit (int | Unset):  Default: 20.
        before (datetime.datetime | None | Unset): Page: last_activity_at <

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Problem | ValidationProblem | list[SessionView]
     """


    return sync_detailed(
        client=client,
status=status,
limit=limit,
before=before,

    ).parsed

async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    status: ListSessionsStatusType0 | None | Unset = UNSET,
    limit: int | Unset = 20,
    before: datetime.datetime | None | Unset = UNSET,

) -> Response[Problem | ValidationProblem | list[SessionView]]:
    """ List sessions, newest activity first

    Args:
        status (ListSessionsStatusType0 | None | Unset):
        limit (int | Unset):  Default: 20.
        before (datetime.datetime | None | Unset): Page: last_activity_at <

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Problem | ValidationProblem | list[SessionView]]
     """


    kwargs = _get_kwargs(
        status=status,
limit=limit,
before=before,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    status: ListSessionsStatusType0 | None | Unset = UNSET,
    limit: int | Unset = 20,
    before: datetime.datetime | None | Unset = UNSET,

) -> Problem | ValidationProblem | list[SessionView] | None:
    """ List sessions, newest activity first

    Args:
        status (ListSessionsStatusType0 | None | Unset):
        limit (int | Unset):  Default: 20.
        before (datetime.datetime | None | Unset): Page: last_activity_at <

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Problem | ValidationProblem | list[SessionView]
     """


    return (await asyncio_detailed(
        client=client,
status=status,
limit=limit,
before=before,

    )).parsed
