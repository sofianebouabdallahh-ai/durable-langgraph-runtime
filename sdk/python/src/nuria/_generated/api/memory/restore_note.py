from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.note_view import NoteView
from ...models.problem import Problem
from ...models.validation_problem import ValidationProblem
from typing import cast



def _get_kwargs(
    name: str,
    note_id: str,

) -> dict[str, Any]:
    

    

    

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/agents/{name}/memory/{note_id}/restore".format(name=quote(str(name), safe=""),note_id=quote(str(note_id), safe=""),),
    }


    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> NoteView | Problem | ValidationProblem:
    if response.status_code == 200:
        response_200 = NoteView.from_dict(response.json())



        return response_200

    if response.status_code == 404:
        response_404 = Problem.from_dict(response.json())



        return response_404

    if response.status_code == 422:
        response_422 = ValidationProblem.from_dict(response.json())



        return response_422

    response_default = Problem.from_dict(response.json())



    return response_default



def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[NoteView | Problem | ValidationProblem]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    name: str,
    note_id: str,
    *,
    client: AuthenticatedClient | Client,

) -> Response[NoteView | Problem | ValidationProblem]:
    """ Bring back a forgotten note

    Args:
        name (str):
        note_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[NoteView | Problem | ValidationProblem]
     """


    kwargs = _get_kwargs(
        name=name,
note_id=note_id,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    name: str,
    note_id: str,
    *,
    client: AuthenticatedClient | Client,

) -> NoteView | Problem | ValidationProblem | None:
    """ Bring back a forgotten note

    Args:
        name (str):
        note_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        NoteView | Problem | ValidationProblem
     """


    return sync_detailed(
        name=name,
note_id=note_id,
client=client,

    ).parsed

async def asyncio_detailed(
    name: str,
    note_id: str,
    *,
    client: AuthenticatedClient | Client,

) -> Response[NoteView | Problem | ValidationProblem]:
    """ Bring back a forgotten note

    Args:
        name (str):
        note_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[NoteView | Problem | ValidationProblem]
     """


    kwargs = _get_kwargs(
        name=name,
note_id=note_id,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    name: str,
    note_id: str,
    *,
    client: AuthenticatedClient | Client,

) -> NoteView | Problem | ValidationProblem | None:
    """ Bring back a forgotten note

    Args:
        name (str):
        note_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        NoteView | Problem | ValidationProblem
     """


    return (await asyncio_detailed(
        name=name,
note_id=note_id,
client=client,

    )).parsed
