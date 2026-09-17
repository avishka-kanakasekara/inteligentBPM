"""Agent 1 — Process Discovery and Execution Planning service."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from uuid import UUID

from app.agents.discovery.models import (
    ChatAgentOutput,
    DiscoveryMessage,
    DiscoveryChatSession,
    MissingInformation,
    PlanAgentOutput,
    PlanSourceReference,
    ProcessIntent,
    ProcessPlan,
    ProcessStep,
    ActionType,
    RiskLevel,
    plan_to_snapshot,
)
from app.agents.discovery.validation import ensure_stable_step_ids, validate_process_plan
from app.audit import AuditService
from app.contracts.common import utcnow
from app.database.memory import (
    DiscoveryMessageRecord,
    DiscoverySessionRecord,
    get_memory_store,
    new_id,
)
from app.llm.client import FakeGeminiClient, GeminiClient, create_gemini_client
from app.llm.prompt_registry import PromptRegistry
from app.llm.structured import StructuredGenerationService
from app.llm.types import AgentExecutionContext, AgentKind, EvidenceRef
from app.repositories.memory_repos import ProcessRepository
from app.services.documents.injection import Citation, assemble_agent_context, scan_for_injection
from app.services.documents.pipeline import DocumentSearchService
from app.security.errors import ConflictError, ValidationAppError
import structlog

logger = structlog.get_logger()


class DiscoveryService:
    """Chat, draft plans, revisions, confirmation — no external side effects."""

    def __init__(
        self,
        organization_id: UUID,
        *,
        client: GeminiClient | None = None,
        structured: StructuredGenerationService | None = None,
    ) -> None:
        self.organization_id = organization_id
        self.store = get_memory_store()
        self.processes = ProcessRepository(organization_id)
        self.client = client or create_gemini_client()
        self.structured = structured or StructuredGenerationService(client=self.client)
        self.prompts = PromptRegistry()
        self.audit = AuditService()

    # ------------------------------------------------------------------
    # Sessions / messages
    # ------------------------------------------------------------------

    def get_or_create_session(
        self,
        process_id: UUID,
        *,
        user_id: UUID | None,
        document_ids: list[UUID] | None = None,
    ) -> DiscoverySessionRecord:
        self.processes.get(process_id)
        for session in self.store.discovery_sessions.values():
            if (
                session.organization_id == self.organization_id
                and session.process_id == process_id
                and session.status == "active"
            ):
                if document_ids:
                    merged = list({*session.document_ids, *document_ids})
                    session.document_ids = merged
                    session.updated_at = utcnow()
                    from app.config import get_settings
                    from app.database.postgres_persistence import persist_mutation

                    if get_settings().persistence_mode == "postgres":
                        persist_mutation(self.store, "discovery_sessions", session.id)
                return session
        now = utcnow()
        session = DiscoverySessionRecord(
            id=new_id(),
            organization_id=self.organization_id,
            process_id=process_id,
            status="active",
            created_by_user_id=user_id,
            document_ids=list(document_ids or []),
            created_at=now,
            updated_at=now,
        )
        self.store.discovery_sessions[session.id] = session
        return session

    def list_messages(self, process_id: UUID) -> list[DiscoveryMessageRecord]:
        self.processes.get(process_id)
        messages = [
            m
            for m in self.store.discovery_messages.values()
            if m.organization_id == self.organization_id and m.process_id == process_id
        ]
        messages.sort(key=lambda m: m.created_at)
        return messages

    def _append_message(
        self,
        *,
        process_id: UUID,
        session_id: UUID,
        role: str,
        content: str,
        user_id: UUID | None,
        document_ids: list[UUID] | None = None,
        clarifying_questions: list[str] | None = None,
        intent: dict[str, Any] | None = None,
        plan_draft: dict[str, Any] | None = None,
        source_refs: list[dict[str, Any]] | None = None,
        suspicious_flags: list[str] | None = None,
    ) -> DiscoveryMessageRecord:
        record = DiscoveryMessageRecord(
            id=new_id(),
            organization_id=self.organization_id,
            process_id=process_id,
            session_id=session_id,
            role=role,
            content=content,
            document_ids=list(document_ids or []),
            clarifying_questions=list(clarifying_questions or []),
            intent=intent,
            plan_draft=plan_draft,
            source_refs=list(source_refs or []),
            suspicious_flags=list(suspicious_flags or []),
            created_by_user_id=user_id,
            created_at=utcnow(),
        )
        self.store.discovery_messages[record.id] = record
        self._emit(
            process_id,
            {
                "type": "chat.message",
                "message_id": str(record.id),
                "role": role,
                "content": content,
            },
        )
        return record

    # ------------------------------------------------------------------
    # Document context (untrusted)
    # ------------------------------------------------------------------

    def _document_context(
        self,
        *,
        query: str,
        document_ids: list[UUID],
        user_id: UUID | None,
    ) -> tuple[str, list[PlanSourceReference], list[str]]:
        if not document_ids and not query.strip():
            return "", [], []
        search = DocumentSearchService(self.organization_id)
        hits = search.search(
            query=query or "process plan",
            mode="hybrid",
            limit=6,
            similarity_threshold=0.05,
            user_id=user_id,
            can_read_restricted=True,
        )
        if document_ids:
            allowed = set(document_ids)
            hits = [h for h in hits if h.document_id in allowed]
        citations = [
            Citation(
                document_id=h.citation.document_id,
                chunk_id=h.citation.chunk_id,
                file_name=h.citation.file_name,
                page_number=h.citation.page_number,
                section_heading=h.citation.section_heading,
                excerpt=h.citation.excerpt,
            )
            for h in hits
        ]
        context = assemble_agent_context(citations=citations) if citations else ""
        refs = [
            PlanSourceReference(
                type="chunk",
                id=c.chunk_id,
                label=c.file_name,
                page_number=c.page_number,
                section_heading=c.section_heading,
                excerpt=c.excerpt,
            )
            for c in citations
        ]
        flags: list[str] = []
        for c in citations:
            scan = scan_for_injection(c.excerpt)
            if scan.suspicious:
                flags.extend(scan.flags)
        return context, refs, sorted(set(flags))

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    def chat(
        self,
        process_id: UUID,
        *,
        message: str,
        user_id: UUID,
        correlation_id: str | None,
        document_ids: list[UUID] | None = None,
        permissions: frozenset[str],
    ) -> DiscoveryMessage:
        if not message.strip():
            raise ValidationAppError("message is required")

        injection = scan_for_injection(message)
        session = self.get_or_create_session(
            process_id, user_id=user_id, document_ids=document_ids
        )
        self._append_message(
            process_id=process_id,
            session_id=session.id,
            role="user",
            content=message,
            user_id=user_id,
            document_ids=document_ids,
            suspicious_flags=list(injection.flags),
        )

        doc_context, source_refs, doc_flags = self._document_context(
            query=message,
            document_ids=list(document_ids or session.document_ids),
            user_id=user_id,
        )
        history = self.list_messages(process_id)[-12:]
        history_text = "\n".join(f"{m.role}: {m.content}" for m in history)

        system, user_prompt = self.prompts.render(
            AgentKind.PLANNER,
            "discover_plan",
            goal=message,
            context=f"{history_text}\n\n{doc_context}",
        )
        # Strengthen Agent 1 constraints in system prompt
        system = (
            system
            + " Ask concise clarification questions. Never invent company data. "
            "Never execute a plan. Never claim a process is safe. Never bypass Agent 3. "
            "Distinguish facts, assumptions, and recommendations. Cite sources."
        )

        ctx = AgentExecutionContext(
            organization_id=self.organization_id,
            process_id=process_id,
            correlation_id=correlation_id,
            trace_id=correlation_id,
            actor_user_id=user_id,
            agent=AgentKind.PLANNER,
            permissions=permissions,
        )

        try:
            result = self.structured.generate(
                context=ctx,
                output_model=ChatAgentOutput,
                system_instruction=system,
                user_prompt=user_prompt,
                evidence_refs=[
                    EvidenceRef(type=r.type, id=r.id, label=r.label) for r in source_refs
                ],
            )
            output: ChatAgentOutput = result.data
        except Exception as exc:
            logger.warning("discovery.chat_llm_failed", error=str(exc))
            # Deterministic fallback for empty fake queues / provider failures in local mode
            output = self._heuristic_chat(message, source_refs)

        if output.claims_process_safe or output.bypasses_risk_agent or output.executes_side_effects:
            raise ValidationAppError(
                "Agent 1 response violated safety constraints "
                "(cannot claim safe / bypass Agent 3 / execute side effects)"
            )

        flags = sorted(set(list(injection.flags) + list(doc_flags)))
        merged_refs = list(output.source_refs) + source_refs
        assistant = self._append_message(
            process_id=process_id,
            session_id=session.id,
            role="assistant",
            content=output.reply,
            user_id=None,
            clarifying_questions=output.clarifying_questions,
            intent=output.intent.model_dump(mode="json") if output.intent else None,
            source_refs=[r.model_dump(mode="json") for r in merged_refs],
            suspicious_flags=flags,
        )
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=user_id,
            action="discovery.chat",
            resource_type="process",
            resource_id=process_id,
            correlation_id=correlation_id,
            payload={"message_id": str(assistant.id), "suspicious_flags": flags},
        )
        return DiscoveryMessage(
            id=assistant.id,
            organization_id=assistant.organization_id,
            process_id=assistant.process_id,
            session_id=assistant.session_id,
            role="assistant",  # type: ignore[arg-type]
            content=assistant.content,
            document_ids=assistant.document_ids,
            clarifying_questions=assistant.clarifying_questions,
            intent=ProcessIntent.model_validate(assistant.intent) if assistant.intent else None,
            plan_draft=(
                ProcessPlan.model_validate(assistant.plan_draft) if assistant.plan_draft else None
            ),
            source_refs=[PlanSourceReference.model_validate(r) for r in assistant.source_refs],
            suspicious_flags=assistant.suspicious_flags,
            created_by_user_id=assistant.created_by_user_id,
            created_at=assistant.created_at,
        )

    def _heuristic_chat(
        self, message: str, source_refs: list[PlanSourceReference]
    ) -> ChatAgentOutput:
        questions: list[str] = []
        missing: list[MissingInformation] = []
        lower = message.lower()
        if "budget" not in lower:
            questions.append("What is the approved budget or spending limit?")
            missing.append(
                MissingInformation(
                    id="miss_budget",
                    field="budget",
                    question="What is the approved budget or spending limit?",
                    blocking=True,
                )
            )
        if "approver" not in lower and "manager" not in lower:
            questions.append("Who is the required approver for this process?")
            missing.append(
                MissingInformation(
                    id="miss_approver",
                    field="approver",
                    question="Who is the required approver for this process?",
                    blocking=True,
                )
            )
        intent = ProcessIntent(
            goal=message.strip()[:500],
            clarifying_questions=questions,
            facts=[],
            assumptions=["Organization policies apply unless otherwise stated."],
            recommendations=["Draft a plan after clarifying missing information."],
            source_refs=source_refs,
        )
        reply = (
            "I captured your process intent. "
            + (" ".join(questions) if questions else "I have enough to draft a plan when you are ready.")
            + " I will not execute anything or claim the process is safe — Agent 3 must review risk."
        )
        return ChatAgentOutput(
            reply=reply,
            clarifying_questions=questions,
            intent=intent,
            missing_information=missing,
            facts=intent.facts,
            assumptions=intent.assumptions,
            recommendations=intent.recommendations,
            reasoning_summary="Heuristic discovery reply (no side effects).",
            source_refs=source_refs,
        )

    # ------------------------------------------------------------------
    # Draft / revise plan
    # ------------------------------------------------------------------

    def draft_plan(
        self,
        process_id: UUID,
        *,
        user_id: UUID,
        correlation_id: str | None,
        permissions: frozenset[str],
        revision_of_version_id: UUID | None = None,
        document_ids: list[UUID] | None = None,
        instructions: str | None = None,
    ) -> dict[str, Any]:
        process = self.processes.get(process_id)
        previous_plan: ProcessPlan | None = None
        parent_version_id: UUID | None = None
        if revision_of_version_id is not None:
            parent = self.processes.get_version(process_id, revision_of_version_id)
            parent_version_id = parent.id
            previous_plan = ProcessPlan.model_validate(parent.plan_snapshot)

        messages = self.list_messages(process_id)
        transcript = "\n".join(f"{m.role}: {m.content}" for m in messages[-20:])
        goal = process.description or process.name
        if messages:
            # Prefer latest user goal statement
            for msg in reversed(messages):
                if msg.role == "user":
                    goal = msg.content
                    break

        doc_context, source_refs, _flags = self._document_context(
            query=goal,
            document_ids=list(document_ids or []),
            user_id=user_id,
        )
        revision_note = ""
        if previous_plan is not None:
            revision_note = (
                f"\nRevise this existing plan JSON:\n{previous_plan.model_dump_json()}\n"
                f"Instructions: {instructions or 'Improve clarity and fill gaps.'}"
            )

        system, user_prompt = self.prompts.render(
            AgentKind.PLANNER,
            "discover_plan",
            goal=goal,
            context=f"{transcript}\n{doc_context}\n{revision_note}",
        )
        system += (
            " Emit a complete ProcessPlan JSON. Every step needs stable step_id, action_type, "
            "description, dependencies, required_resources, risk_level, allowed_tools, "
            "approval_requirements, success_criteria, retry_behavior, failure_behavior, "
            "source_refs. Never invent employees. Never execute. Never claim safe. Never bypass Agent 3."
        )

        ctx = AgentExecutionContext(
            organization_id=self.organization_id,
            process_id=process_id,
            correlation_id=correlation_id,
            trace_id=correlation_id,
            actor_user_id=user_id,
            agent=AgentKind.PLANNER,
            permissions=permissions,
        )

        self._emit(process_id, {"type": "plan.drafting", "process_id": str(process_id)})

        try:
            # Prefer PlanAgentOutput from LLM
            if isinstance(self.client, FakeGeminiClient) and not self.client.structured_queue:
                plan = self._heuristic_plan(goal, source_refs, previous_plan)
            else:
                result = self.structured.generate(
                    context=ctx,
                    output_model=PlanAgentOutput,
                    system_instruction=system,
                    user_prompt=user_prompt,
                    evidence_refs=[
                        EvidenceRef(type=r.type, id=r.id, label=r.label) for r in source_refs
                    ],
                )
                plan = ProcessPlan.model_validate(result.data.model_dump())
        except Exception as exc:
            logger.warning("discovery.draft_plan_llm_failed", error=str(exc))
            plan = self._heuristic_plan(goal, source_refs, previous_plan)

        plan = ensure_stable_step_ids(plan, previous_plan)
        if source_refs:
            plan.source_refs = list(plan.source_refs) + source_refs

        # Sanitize LLM output before strict validation
        plan = self._sanitize_plan(plan)

        try:
            plan = validate_process_plan(plan)
        except Exception as val_exc:
            val_details = getattr(val_exc, "details", None)
            logger.warning(
                "discovery.plan_validation_failed_falling_back",
                error=str(val_exc),
                details=val_details,
                process_id=str(process_id),
            )
            plan = self._heuristic_plan(goal, source_refs, previous_plan)
            plan = self._sanitize_plan(plan)

        version = self.processes.create_version(
            process_id,
            plan_snapshot=plan_to_snapshot(plan),
            parent_version_id=parent_version_id,
            status="draft",
        )
        self._emit(
            process_id,
            {
                "type": "plan.drafted",
                "version_id": str(version.id),
                "version_number": version.version_number,
                "step_count": len(plan.steps),
                "missing_information": [m.model_dump() for m in plan.missing_information],
            },
        )
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=user_id,
            action="discovery.plan_drafted",
            resource_type="process_version",
            resource_id=version.id,
            correlation_id=correlation_id,
            payload={
                "process_id": str(process_id),
                "version_number": version.version_number,
                "missing_count": len(plan.missing_information),
            },
        )
        try:
            from app.agents.risk.service import RiskAnalysisService

            RiskAnalysisService(self.organization_id).invalidate_for_process(
                process_id,
                reason="Plan changes invalidate the risk result",
            )
        except Exception:
            pass
        return {
            "version_id": version.id,
            "version_number": version.version_number,
            "status": version.status,
            "plan": plan,
            "plan_snapshot_hash": version.plan_snapshot_hash,
        }

    # ------------------------------------------------------------------
    # Sanitize LLM-generated plan before validation
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize_plan(plan: ProcessPlan) -> ProcessPlan:
        """Fix common LLM output issues so strict validation doesn't reject valid plans."""
        # Ensure LLM hasn't tripped safety flags
        plan.claims_process_safe = False
        plan.bypasses_risk_agent = False
        plan.executes_side_effects = False

        known_ids = {s.step_id for s in plan.steps}

        # Deduplicate step IDs (keep first occurrence)
        seen: set[str] = set()
        unique_steps = []
        for step in plan.steps:
            if step.step_id not in seen:
                seen.add(step.step_id)
                unique_steps.append(step)
            else:
                # Rename duplicate
                suffix = 1
                new_id_candidate = f"{step.step_id}_{suffix}"
                while new_id_candidate in seen:
                    suffix += 1
                    new_id_candidate = f"{step.step_id}_{suffix}"
                step.step_id = new_id_candidate
                seen.add(new_id_candidate)
                unique_steps.append(step)
        plan.steps = unique_steps
        known_ids = {s.step_id for s in plan.steps}

        forbidden_tools = {
            "execute_sql",
            "shell",
            "run_code",
            "http_request",
            "bash",
            "python",
            "terminal",
            "eval",
        }

        for step in plan.steps:
            # Filter dependencies to only known step IDs
            step.dependencies = [d for d in step.dependencies if d in known_ids and d != step.step_id]

            # Ensure success_criteria is never empty
            if not step.success_criteria:
                step.success_criteria = [f"Step {step.step_id} completed successfully."]

            # Ensure description is not blank
            if not step.description.strip():
                step.description = step.title or f"Execute {step.step_id}"

            # Filter forbidden tools
            step.allowed_tools = [
                t for t in step.allowed_tools if t.lower() not in forbidden_tools
            ]

        # Prune edges that reference unknown steps or are self-referential
        plan.edges = [
            e
            for e in plan.edges
            if e.from_step_id in known_ids
            and e.to_step_id in known_ids
            and e.from_step_id != e.to_step_id
        ]

        return plan

    def _heuristic_plan(
        self,
        goal: str,
        source_refs: list[PlanSourceReference],
        previous: ProcessPlan | None,
    ) -> ProcessPlan:
        if previous is not None:
            # Revision: keep step IDs, append a clarification step if missing info remains
            steps = list(previous.steps)
            missing = list(previous.missing_information)
            if missing and not any(s.step_id == "step_clarify" for s in steps):
                steps.insert(
                    0,
                    ProcessStep(
                        step_id="step_clarify",
                        action_type=ActionType.COLLECT_INFO,
                        title="Collect missing information",
                        description="Gather blocking missing information before proceeding.",
                        dependencies=[],
                        required_resources=["requester"],
                        risk_level=RiskLevel.LOW,
                        allowed_tools=[],
                        approval_requirements=[],
                        success_criteria=["All blocking missing information resolved"],
                        retry_behavior="ask_again",
                        failure_behavior="block_and_escalate",
                        source_refs=source_refs,
                    ),
                )
                for step in steps[1:]:
                    if "step_clarify" not in step.dependencies:
                        step.dependencies = ["step_clarify", *step.dependencies]
            return ProcessPlan(
                goal=previous.goal,
                intent=previous.intent,
                assumptions=previous.assumptions,
                missing_information=missing,
                clarifying_questions=previous.clarifying_questions,
                steps=steps,
                edges=previous.edges,
                confidence=min(previous.confidence + 0.05, 0.95),
                reasoning_summary="Revised draft plan (Agent 1). Risk review still required by Agent 3.",
                source_refs=list(previous.source_refs) + source_refs,
            )

        missing = [
            MissingInformation(
                id="miss_budget",
                field="budget",
                question="What budget is approved for this process?",
                blocking=True,
                related_step_ids=["step_approve"],
            )
        ]
        steps = [
            ProcessStep(
                step_id="step_intake",
                action_type=ActionType.COLLECT_INFO,
                title="Capture request",
                description=f"Capture the process request details for: {goal}",
                dependencies=[],
                required_resources=["requester"],
                risk_level=RiskLevel.LOW,
                allowed_tools=[],
                approval_requirements=[],
                success_criteria=["Request recorded with goal and constraints"],
                retry_behavior="none",
                failure_behavior="block_and_escalate",
                source_refs=source_refs,
            ),
            ProcessStep(
                step_id="step_allocate",
                action_type=ActionType.HUMAN_TASK,
                title="Allocate resources",
                description="Assign people, departments, and suppliers using org directory (Agent 2).",
                dependencies=["step_intake"],
                required_resources=["manager", "department"],
                risk_level=RiskLevel.MEDIUM,
                allowed_tools=[],
                approval_requirements=[],
                success_criteria=["Resources bound without inventing company data"],
                retry_behavior="retry_once",
                failure_behavior="block_and_escalate",
                source_refs=source_refs,
            ),
            ProcessStep(
                step_id="step_risk",
                action_type=ActionType.REVIEW,
                title="Risk and policy review",
                description="Agent 3 must evaluate policy fit and residual risk. Agent 1 does not bypass this.",
                dependencies=["step_allocate"],
                required_resources=["compliance"],
                risk_level=RiskLevel.HIGH,
                allowed_tools=[],
                approval_requirements=["compliance"],
                success_criteria=["Risk result recorded; blocking issues surfaced"],
                retry_behavior="none",
                failure_behavior="block_and_escalate",
                source_refs=source_refs,
                is_decision_point=True,
            ),
            ProcessStep(
                step_id="step_approve",
                action_type=ActionType.APPROVAL,
                title="Human approval",
                description="Obtain human approval for the frozen snapshot before any execution.",
                dependencies=["step_risk"],
                required_resources=["approver"],
                risk_level=RiskLevel.HIGH,
                allowed_tools=[],
                approval_requirements=["manager"],
                success_criteria=["Approval granted for immutable snapshot"],
                retry_behavior="none",
                failure_behavior="cancel_process",
                source_refs=source_refs,
                is_decision_point=True,
                sla="2 business days",
            ),
        ]
        intent = ProcessIntent(
            goal=goal,
            actors=["requester", "manager", "approver"],
            systems=["bpm_platform"],
            inputs=["request description", "supporting documents"],
            outputs=["approved process snapshot"],
            decision_points=["risk gate", "human approval"],
            dependencies=["directory data", "policies"],
            slas=["2 business days for approval"],
            exception_paths=["Reject and return to requester"],
            clarifying_questions=[m.question for m in missing],
            source_refs=source_refs,
        )
        return ProcessPlan(
            goal=goal,
            intent=intent,
            missing_information=missing,
            clarifying_questions=[m.question for m in missing],
            steps=steps,
            edges=[],
            confidence=0.55,
            reasoning_summary=(
                "Draft plan generated by Agent 1 for discovery only. "
                "Does not execute side effects and does not claim safety."
            ),
            source_refs=source_refs,
        )

    # ------------------------------------------------------------------
    # Confirm
    # ------------------------------------------------------------------

    def confirm_version(
        self,
        process_id: UUID,
        version_id: UUID,
        *,
        user_id: UUID,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        version = self.processes.get_version(process_id, version_id)
        plan = ProcessPlan.model_validate(version.plan_snapshot)
        plan = self._sanitize_plan(plan)
        plan = validate_process_plan(plan)
        if version.status == "confirmed":
            raise ConflictError("Plan version already confirmed", code="ALREADY_CONFIRMED")
        updated = self.processes.confirm_version(
            process_id,
            version_id,
            confirmed_by_user_id=user_id,
        )
        # Advance the process status so it becomes visible on Active Runs.
        # Without this, the process stays "draft" forever after plan confirmation.
        self.processes.set_status(process_id, "plan_ready")
        self._emit(
            process_id,
            {
                "type": "plan.confirmed",
                "version_id": str(updated.id),
                "version_number": updated.version_number,
            },
        )
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=user_id,
            action="discovery.plan_confirmed",
            resource_type="process_version",
            resource_id=updated.id,
            correlation_id=correlation_id,
            payload={"process_id": str(process_id), "missing_count": len(plan.missing_information)},
        )
        return {
            "version_id": updated.id,
            "version_number": updated.version_number,
            "status": updated.status,
            "confirmed_at": updated.confirmed_at,
            "plan": plan,
        }

    # ------------------------------------------------------------------
    # SSE
    # ------------------------------------------------------------------

    def _emit(self, process_id: UUID, event: dict[str, Any]) -> None:
        self.store.discovery_events.setdefault(process_id, []).append(
            {**event, "at": utcnow().isoformat()}
        )

    def drain_events(self, process_id: UUID) -> list[dict[str, Any]]:
        events = list(self.store.discovery_events.get(process_id, []))
        self.store.discovery_events[process_id] = []
        return events

    def iter_sse(self, process_id: UUID) -> Iterator[str]:
        self.processes.get(process_id)
        # Snapshot existing chat as initial events, then drain buffer
        for msg in self.list_messages(process_id):
            payload = {
                "type": "chat.message",
                "message_id": str(msg.id),
                "role": msg.role,
                "content": msg.content,
            }
            yield f"event: chat.message\ndata: {json.dumps(payload)}\n\n"
        for event in self.drain_events(process_id):
            etype = event.get("type", "message")
            yield f"event: {etype}\ndata: {json.dumps(event)}\n\n"
        yield "event: done\ndata: {\"ok\": true}\n\n"


def session_to_model(record: DiscoverySessionRecord) -> DiscoveryChatSession:
    return DiscoveryChatSession.model_validate(record, from_attributes=True)
