from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.run_status import RunStatus
from ..types import UNSET, Unset
from typing import cast
from uuid import UUID
import datetime

if TYPE_CHECKING:
  from ..models.run_view_interrupt_payload_type_0 import RunViewInterruptPayloadType0
  from ..models.run_view_limits import RunViewLimits
  from ..models.subagent_view import SubagentView





T = TypeVar("T", bound="RunView")



@_attrs_define
class RunView:
    """ 
        Attributes:
            cancel_requested (bool):
            child_done (int): Children that have ended
            child_key (None | str):
            child_total (int): Children spawned so far
            created_at (datetime.datetime):
            depth (int): 0 for a root run, parent's + 1 for a child (R14.6)
            epoch (int):
            finished_at (datetime.datetime | None):
            graph (str):
            id (UUID):
            interrupt_payload (None | RunViewInterruptPayloadType0): The next approval a waiting_approval run waits on
                (R1.4): its `approval_id`, `tool`, `args` (secrets redacted), `hidden` (how many values that redaction took out
                of `args`, H10), `call_id` and `reason`. Several can be pending; once this one is decided, the next one shows
                here.
            kind (str):
            lease_expires_at (datetime.datetime | None):
            limits (RunViewLimits):
            owner (None | str): Worker (pod) holding the lease, if any
            parent_run_id (None | UUID): Set for child runs (R2.8)
            reason (None | str):
            reclaims (int): Times taken over after a worker died (R2.4)
            releases (int): Graceful hand-offs on worker shutdown (R10.7)
            root_run_id (None | UUID):
            started_at (datetime.datetime | None):
            status (RunStatus):
            steps (int):
            details_pruned_at (datetime.datetime | None | Unset): When retention removed its events and tool calls (H10):
                the timeline is empty because it was pruned, not because nothing happened. RETENTION_DAYS.
            infra_retries (int | Unset): Releases because Postgres or Redis failed (H4), bounded Default: 0.
            redrives (int | Unset): Times a person tried it again (H4) Default: 0.
            subagents (list[SubagentView] | Unset): Sub-agent invocations of this run (CR-005 R16.10)
            trace_id (None | str | Unset): The OpenTelemetry trace this run belongs to (R7.1)
     """

    cancel_requested: bool
    child_done: int
    child_key: None | str
    child_total: int
    created_at: datetime.datetime
    depth: int
    epoch: int
    finished_at: datetime.datetime | None
    graph: str
    id: UUID
    interrupt_payload: None | RunViewInterruptPayloadType0
    kind: str
    lease_expires_at: datetime.datetime | None
    limits: RunViewLimits
    owner: None | str
    parent_run_id: None | UUID
    reason: None | str
    reclaims: int
    releases: int
    root_run_id: None | UUID
    started_at: datetime.datetime | None
    status: RunStatus
    steps: int
    details_pruned_at: datetime.datetime | None | Unset = UNSET
    infra_retries: int | Unset = 0
    redrives: int | Unset = 0
    subagents: list[SubagentView] | Unset = UNSET
    trace_id: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.run_view_interrupt_payload_type_0 import RunViewInterruptPayloadType0 # noqa: PLC0415
        from ..models.run_view_limits import RunViewLimits # noqa: PLC0415
        from ..models.subagent_view import SubagentView # noqa: PLC0415
        cancel_requested = self.cancel_requested

        child_done = self.child_done

        child_key: None | str
        child_key = self.child_key

        child_total = self.child_total

        created_at = self.created_at.isoformat()

        depth = self.depth

        epoch = self.epoch

        finished_at: None | str
        if isinstance(self.finished_at, datetime.datetime):
            finished_at = self.finished_at.isoformat()
        else:
            finished_at = self.finished_at

        graph = self.graph

        id = str(self.id)

        interrupt_payload: dict[str, Any] | None
        if isinstance(self.interrupt_payload, RunViewInterruptPayloadType0):
            interrupt_payload = self.interrupt_payload.to_dict()
        else:
            interrupt_payload = self.interrupt_payload

        kind = self.kind

        lease_expires_at: None | str
        if isinstance(self.lease_expires_at, datetime.datetime):
            lease_expires_at = self.lease_expires_at.isoformat()
        else:
            lease_expires_at = self.lease_expires_at

        limits = self.limits.to_dict()

        owner: None | str
        owner = self.owner

        parent_run_id: None | str
        if isinstance(self.parent_run_id, UUID):
            parent_run_id = str(self.parent_run_id)
        else:
            parent_run_id = self.parent_run_id

        reason: None | str
        reason = self.reason

        reclaims = self.reclaims

        releases = self.releases

        root_run_id: None | str
        if isinstance(self.root_run_id, UUID):
            root_run_id = str(self.root_run_id)
        else:
            root_run_id = self.root_run_id

        started_at: None | str
        if isinstance(self.started_at, datetime.datetime):
            started_at = self.started_at.isoformat()
        else:
            started_at = self.started_at

        status = self.status.value

        steps = self.steps

        details_pruned_at: None | str | Unset
        if isinstance(self.details_pruned_at, Unset):
            details_pruned_at = UNSET
        elif isinstance(self.details_pruned_at, datetime.datetime):
            details_pruned_at = self.details_pruned_at.isoformat()
        else:
            details_pruned_at = self.details_pruned_at

        infra_retries = self.infra_retries

        redrives = self.redrives

        subagents: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.subagents, Unset):
            subagents = []
            for subagents_item_data in self.subagents:
                subagents_item = subagents_item_data.to_dict()
                subagents.append(subagents_item)



        trace_id: None | str | Unset
        if isinstance(self.trace_id, Unset):
            trace_id = UNSET
        else:
            trace_id = self.trace_id


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "cancel_requested": cancel_requested,
            "child_done": child_done,
            "child_key": child_key,
            "child_total": child_total,
            "created_at": created_at,
            "depth": depth,
            "epoch": epoch,
            "finished_at": finished_at,
            "graph": graph,
            "id": id,
            "interrupt_payload": interrupt_payload,
            "kind": kind,
            "lease_expires_at": lease_expires_at,
            "limits": limits,
            "owner": owner,
            "parent_run_id": parent_run_id,
            "reason": reason,
            "reclaims": reclaims,
            "releases": releases,
            "root_run_id": root_run_id,
            "started_at": started_at,
            "status": status,
            "steps": steps,
        })
        if details_pruned_at is not UNSET:
            field_dict["details_pruned_at"] = details_pruned_at
        if infra_retries is not UNSET:
            field_dict["infra_retries"] = infra_retries
        if redrives is not UNSET:
            field_dict["redrives"] = redrives
        if subagents is not UNSET:
            field_dict["subagents"] = subagents
        if trace_id is not UNSET:
            field_dict["trace_id"] = trace_id

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.run_view_interrupt_payload_type_0 import RunViewInterruptPayloadType0 # noqa: PLC0415
        from ..models.run_view_limits import RunViewLimits # noqa: PLC0415
        from ..models.subagent_view import SubagentView # noqa: PLC0415
        d = dict(src_dict)
        cancel_requested = d.pop("cancel_requested")

        child_done = d.pop("child_done")

        def _parse_child_key(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        child_key = _parse_child_key(d.pop("child_key"))


        child_total = d.pop("child_total")

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))




        depth = d.pop("depth")

        epoch = d.pop("epoch")

        def _parse_finished_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                finished_at_type_0 = datetime.datetime.fromisoformat(data)



                return finished_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        finished_at = _parse_finished_at(d.pop("finished_at"))


        graph = d.pop("graph")

        id = UUID(d.pop("id"))




        def _parse_interrupt_payload(data: object) -> None | RunViewInterruptPayloadType0:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                interrupt_payload_type_0 = RunViewInterruptPayloadType0.from_dict(data)



                return interrupt_payload_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | RunViewInterruptPayloadType0, data)

        interrupt_payload = _parse_interrupt_payload(d.pop("interrupt_payload"))


        kind = d.pop("kind")

        def _parse_lease_expires_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                lease_expires_at_type_0 = datetime.datetime.fromisoformat(data)



                return lease_expires_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        lease_expires_at = _parse_lease_expires_at(d.pop("lease_expires_at"))


        limits = RunViewLimits.from_dict(d.pop("limits"))




        def _parse_owner(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        owner = _parse_owner(d.pop("owner"))


        def _parse_parent_run_id(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                parent_run_id_type_0 = UUID(data)



                return parent_run_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        parent_run_id = _parse_parent_run_id(d.pop("parent_run_id"))


        def _parse_reason(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        reason = _parse_reason(d.pop("reason"))


        reclaims = d.pop("reclaims")

        releases = d.pop("releases")

        def _parse_root_run_id(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                root_run_id_type_0 = UUID(data)



                return root_run_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        root_run_id = _parse_root_run_id(d.pop("root_run_id"))


        def _parse_started_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                started_at_type_0 = datetime.datetime.fromisoformat(data)



                return started_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        started_at = _parse_started_at(d.pop("started_at"))


        status = RunStatus(d.pop("status"))




        steps = d.pop("steps")

        def _parse_details_pruned_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                details_pruned_at_type_0 = datetime.datetime.fromisoformat(data)



                return details_pruned_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        details_pruned_at = _parse_details_pruned_at(d.pop("details_pruned_at", UNSET))


        infra_retries = d.pop("infra_retries", UNSET)

        redrives = d.pop("redrives", UNSET)

        _subagents = d.pop("subagents", UNSET)
        subagents: list[SubagentView] | Unset = UNSET
        if _subagents is not UNSET:
            subagents = []
            for subagents_item_data in _subagents:
                subagents_item = SubagentView.from_dict(subagents_item_data)



                subagents.append(subagents_item)


        def _parse_trace_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        trace_id = _parse_trace_id(d.pop("trace_id", UNSET))


        run_view = cls(
            cancel_requested=cancel_requested,
            child_done=child_done,
            child_key=child_key,
            child_total=child_total,
            created_at=created_at,
            depth=depth,
            epoch=epoch,
            finished_at=finished_at,
            graph=graph,
            id=id,
            interrupt_payload=interrupt_payload,
            kind=kind,
            lease_expires_at=lease_expires_at,
            limits=limits,
            owner=owner,
            parent_run_id=parent_run_id,
            reason=reason,
            reclaims=reclaims,
            releases=releases,
            root_run_id=root_run_id,
            started_at=started_at,
            status=status,
            steps=steps,
            details_pruned_at=details_pruned_at,
            infra_retries=infra_retries,
            redrives=redrives,
            subagents=subagents,
            trace_id=trace_id,
        )


        run_view.additional_properties = d
        return run_view

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
