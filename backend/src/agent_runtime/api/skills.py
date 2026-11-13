"""The skill library (phase L3c, CR-006 R17.4): what the Skills page calls.

    GET  /skills · POST /skills                 the library · create from the form
    GET  /skills/{id} · PATCH · DELETE          one skill · edit (a new version) · archive
    POST /skills/upload?filename=               a new skill from a zip or SKILL.md (the body)
    POST /skills/{id}/upload?filename=          a new version of this skill from an upload
    POST /skills/{id}/approve                   "I've read this": the current version (H10)
    GET  /skills/{id}/export                    the standard's folder, zipped
    GET  /skills/{id}/files/{path}              one file (always as a download)

Every save is checked against the Agent Skills standard and scanned; the response
carries the scan report and any warnings. A secret refuses the save (422) without
echoing it. Every response says whether a person has read the current version
(`approved`): until then an Always-use skill reaches the model as data, not as text.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from agent_runtime.skills.service import Saved, SkillService
from agent_runtime.skills.spec import MAX_BYTES, SkillRejected, estimate_tokens
from agent_runtime.skills.store import Skill, SkillVersion

skills_router = APIRouter(prefix="/skills", tags=["skills"])

MAX_TEXT_FILE = 200_000  # a reference file typed or pasted in the form


def _service(request: Request) -> SkillService:
    service: SkillService = request.app.state.skills
    return service


ServiceDep = Annotated[SkillService, Depends(_service)]


class Finding(BaseModel):
    check: str
    severity: Literal["block", "review"]
    message: str
    where: str | None


class ScanView(BaseModel):
    status: Literal["clean", "review", "blocked"]
    findings: list[Finding]


class FileView(BaseModel):
    path: str
    size: int
    kind: Literal["reference", "asset", "script", "other"]


class SkillView(BaseModel):
    id: uuid.UUID
    name: str
    description: str = Field(description="What it does and when to use it")
    trust: Literal["private", "built_in"]
    origin: Literal["created", "uploaded", "imported", "built_in"]
    version: str = Field(description="The current version's content hash")
    files: list[FileView]
    allowed_tools: list[str] = Field(description="What it asks for; never granted by it")
    meta: dict[str, Any]
    tokens: int = Field(description="About how long its instructions are")
    scan: ScanView
    approved: bool = Field(
        description="A person has read exactly this version. With a clean scan, an "
        "Always-use skill is then plain text in the prompt; until then it's data"
    )
    used_by: list[str] = Field(description="Agents whose draft or published version use it")
    updated_at: datetime

    @classmethod
    def of(cls, skill: Skill, v: SkillVersion, used_by: list[str]) -> SkillView:
        return cls(
            id=skill.id,
            name=skill.name,
            description=v.description,
            trust=skill.trust,
            origin=skill.origin,
            version=v.hash,
            files=[FileView(path=f["path"], size=f["size"], kind=f["kind"]) for f in v.files],
            allowed_tools=str(v.meta.get("allowed-tools") or "").split(),
            meta={k: val for k, val in v.meta.items() if k != "allowed-tools"},
            tokens=estimate_tokens(v.instructions),
            scan=ScanView.model_validate(v.scan),
            approved=v.approved,
            used_by=used_by,
            updated_at=skill.updated_at,
        )


class SkillDetail(SkillView):
    instructions: str

    @classmethod
    def detail(cls, skill: Skill, v: SkillVersion, used_by: list[str]) -> SkillDetail:
        return cls(**SkillView.of(skill, v, used_by).model_dump(), instructions=v.instructions)


class Warning(BaseModel):
    field: str
    message: str


class SavedView(BaseModel):
    skill: SkillDetail
    warnings: list[Warning]

    @classmethod
    def of(cls, saved: Saved, used_by: list[str]) -> SavedView:
        return cls(
            skill=SkillDetail.detail(saved.skill, saved.version, used_by),
            warnings=[Warning(field=w.field, message=w.message) for w in saved.warnings],
        )


TextFile = Annotated[str, Field(max_length=MAX_TEXT_FILE)]


class NewSkill(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=64)]
    description: Annotated[str, Field(max_length=2000)]
    instructions: Annotated[str, Field(max_length=60_000)]
    files: Annotated[dict[str, TextFile], Field(max_length=20)] = Field(
        default_factory=dict, description="Reference files typed in the form: path → text"
    )


class EditSkill(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: Annotated[str, Field(max_length=2000)] | None = None
    instructions: Annotated[str, Field(max_length=60_000)] | None = None
    files: Annotated[dict[str, TextFile | None], Field(max_length=20)] = Field(
        default_factory=dict, description="path → new text, or null to remove the file"
    )


async def _body(request: Request) -> bytes:
    data = bytearray()
    async for chunk in request.stream():  # bounded: never buffer more than the limit
        data += chunk
        if len(data) > MAX_BYTES:
            raise SkillRejected(f"The file is larger than {MAX_BYTES // 1_000_000} MB.")
    return bytes(data)


@skills_router.get("", response_model=list[SkillView], summary="The skill library")
async def library(service: ServiceDep) -> list[SkillView]:
    used = await service.used_by()
    return [SkillView.of(s, v, used.get(s.name, [])) for s, v in await service.all()]


@skills_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=SavedView,
    summary="Create a skill from the form",
)
async def create(body: NewSkill, service: ServiceDep) -> SavedView:
    saved = await service.create(
        name=body.name,
        description=body.description,
        instructions=body.instructions,
        files={p: t.encode("utf-8") for p, t in body.files.items()},
    )
    return SavedView.of(saved, [])


@skills_router.post(
    "/upload",
    status_code=status.HTTP_201_CREATED,
    response_model=SavedView,
    summary="Upload a skill (a zip of its folder, or a SKILL.md) as the body",
)
async def upload(
    request: Request,
    service: ServiceDep,
    filename: Annotated[str, Query(min_length=1, max_length=200)],
) -> SavedView:
    return SavedView.of(await service.upload(filename, await _body(request)), [])


@skills_router.get("/{skill_id}", response_model=SkillDetail, summary="One skill")
async def get(skill_id: uuid.UUID, service: ServiceDep) -> SkillDetail:
    skill, version = await service.get(skill_id)
    return SkillDetail.detail(skill, version, (await service.used_by()).get(skill.name, []))


@skills_router.patch(
    "/{skill_id}", response_model=SavedView, summary="Edit (saves a new version; the name stays)"
)
async def edit(skill_id: uuid.UUID, body: EditSkill, service: ServiceDep) -> SavedView:
    saved = await service.edit(
        skill_id,
        description=body.description,
        instructions=body.instructions,
        files={p: (t.encode("utf-8") if t is not None else None) for p, t in body.files.items()},
    )
    return SavedView.of(saved, (await service.used_by()).get(saved.skill.name, []))


@skills_router.post(
    "/{skill_id}/upload",
    response_model=SavedView,
    summary="A new version of this skill from an upload (same name)",
)
async def replace(
    skill_id: uuid.UUID,
    request: Request,
    service: ServiceDep,
    filename: Annotated[str, Query(min_length=1, max_length=200)],
) -> SavedView:
    saved = await service.replace(skill_id, filename, await _body(request))
    return SavedView.of(saved, (await service.used_by()).get(saved.skill.name, []))


@skills_router.post(
    "/{skill_id}/approve",
    response_model=SkillDetail,
    summary="I've read this version: it may be plain text in prompts (idempotent)",
)
async def approve(skill_id: uuid.UUID, service: ServiceDep) -> SkillDetail:
    skill, version = await service.approve(skill_id)
    return SkillDetail.detail(skill, version, (await service.used_by()).get(skill.name, []))


@skills_router.delete(
    "/{skill_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Archive (published agents keep the version they use)",
)
async def archive(skill_id: uuid.UUID, service: ServiceDep) -> Response:
    await service.archive(skill_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@skills_router.get(
    "/{skill_id}/export",
    summary="Download the skill's folder (zip)",
    responses={200: {"content": {"application/zip": {}}}},
)
async def export(skill_id: uuid.UUID, service: ServiceDep) -> Response:
    filename, data = await service.export(skill_id)
    return Response(
        data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@skills_router.get(
    "/{skill_id}/files/{path:path}",
    summary="Download one of its files",
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def file(skill_id: uuid.UUID, path: str, service: ServiceDep) -> Response:
    entry, data = await service.file(skill_id, path)
    name = entry["path"].rsplit("/", 1)[-1].replace('"', "")
    # Always a download, never rendered: an uploaded .html or .svg must not run here.
    return Response(
        data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
