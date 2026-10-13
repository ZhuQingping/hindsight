"""Bank and operation policy shared by REST, MCP and already accepted worker jobs.

Scopes are enforced at engine hooks, not just by hiding MCP tools. Internal jobs
do not reauthenticate a revoked customer Key, but they must still match the
registered bank/schema. Only lifecycle calls carry a purpose that permits Bank
creation/deletion; being an internal worker is not blanket management authority.
"""

from hindsight_api.extensions.operation_validator import (
    BankListScope,
    BankReadContext,
    BankReadOperation,
    BankWriteContext,
    BankWriteOperation,
    ConsolidateContext,
    CreateBankContext,
    MentalModelGetContext,
    MentalModelRefreshContext,
    OperationValidatorExtension,
    PrecheckContext,
    PrecheckOperation,
    RecallContext,
    ReflectContext,
    RetainContext,
    ValidationResult,
)
from hindsight_api.models import RequestContext

from .config import Settings, repository_for
from .models import Scope, ServiceError

_KNOWLEDGE_READS = frozenset(
    {
        BankReadOperation.GET_KNOWLEDGE_BASE_TREE,
        BankReadOperation.GET_KNOWLEDGE_PAGE,
        BankReadOperation.SEARCH_KNOWLEDGE_BASE,
        BankReadOperation.EXPORT_KNOWLEDGE_BASE,
    }
)
_MEMORY_WRITES = frozenset(
    {
        BankWriteOperation.UPDATE_MEMORY_UNIT,
        BankWriteOperation.UPDATE_DOCUMENT,
        BankWriteOperation.DELETE_DOCUMENT,
        BankWriteOperation.REPROCESS_DOCUMENT,
        BankWriteOperation.CREATE_MENTAL_MODEL,
        BankWriteOperation.UPDATE_MENTAL_MODEL,
        BankWriteOperation.DELETE_MENTAL_MODEL,
        BankWriteOperation.CREATE_DIRECTIVE,
        BankWriteOperation.UPDATE_DIRECTIVE,
        BankWriteOperation.DELETE_DIRECTIVE,
        BankWriteOperation.CREATE_KNOWLEDGE_FOLDER,
        BankWriteOperation.CREATE_KNOWLEDGE_PAGE,
        BankWriteOperation.UPDATE_KNOWLEDGE_PAGE,
        BankWriteOperation.RENAME_KNOWLEDGE_NODE,
        BankWriteOperation.MOVE_KNOWLEDGE_NODE,
        BankWriteOperation.DELETE_KNOWLEDGE_NODE,
        # Native successful retains/edits enqueue these using the original caller
        # context. Refusing them silently disables the background half of memory.
        BankWriteOperation.SUBMIT_ASYNC_CONSOLIDATION,
        BankWriteOperation.SUBMIT_ASYNC_GRAPH_MAINTENANCE,
        BankWriteOperation.SUBMIT_ASYNC_VECTOR_INDEX_MAINTENANCE,
    }
)


class ContextDBOperationValidator(OperationValidatorExtension):
    def __init__(self, config: dict[str, str]) -> None:
        super().__init__(config)
        self.settings = Settings.from_environment()

    async def _authorize(
        self,
        context: RequestContext,
        bank_id: str,
        scope: Scope | None,
        *,
        lifecycle_purpose: str | None = None,
    ) -> ValidationResult:
        # Resolve lazily: importing the engine eagerly while its extension slots
        # are being constructed would create a circular import.
        from hindsight_api.engine.memory_engine import get_current_bank_id, get_current_schema

        repository = await repository_for(self.context.get_memory_engine(), self.settings)
        try:
            if context.internal:
                workspace = await repository.internal_workspace(bank_id, get_current_schema())
                purpose = context.extra_headers.get("ctxdb-internal-purpose")
                if lifecycle_purpose and purpose != lifecycle_purpose:
                    return ValidationResult.reject("Bank management requires a purpose-limited lifecycle context")
                if purpose is not None and (
                    purpose not in {"create_workspace", "delete_workspace"}
                    or not await repository.operation_is_owned(
                        context.extra_headers.get("ctxdb-operation-id", ""),
                        context.extra_headers.get("ctxdb-lease-token", ""),
                        purpose,
                        bank_id,
                    )
                ):
                    return ValidationResult.reject("Workspace operation lease was lost", status_code=409)
                if workspace.state in {"creating", "failed"} and purpose is None:
                    return ValidationResult.reject("Workspace is not ready for background memory operations")
                if (
                    workspace.state in {"frozen", "deleting"}
                    and scope == Scope.MEMORY_WRITE
                    and not context.api_key_id
                    and not context.user_initiated
                    and purpose is None
                    and get_current_bank_id() != bank_id
                ):
                    return ValidationResult.reject("Periodic work cannot enqueue new jobs into an inactive workspace")
                return ValidationResult.accept()
            if lifecycle_purpose:
                return ValidationResult.reject("Business Keys cannot manage Banks")
            principal = await repository.authenticate(context.api_key)
            if bank_id != principal.workspace_id:
                return ValidationResult.reject("Key cannot access another workspace Bank")
            # Tenant resolution must precede every hook. Rechecking this binding
            # also rejects MCP/static-token and cross-schema adapter mistakes.
            if get_current_schema() != principal.schema_name:
                return ValidationResult.reject("Authenticated schema does not match this Key")
            if scope and scope not in principal.scopes:
                return ValidationResult.reject("Key lacks the required operation scope")
            from .admission import mark_engine_started

            mark_engine_started()
            return ValidationResult.accept()
        except ServiceError as error:
            return ValidationResult.reject(error.message, status_code=error.status)

    async def precheck(self, ctx: PrecheckContext) -> ValidationResult:
        scope = {
            PrecheckOperation.RECALL: Scope.MEMORY_READ,
            PrecheckOperation.REFLECT: Scope.REFLECT,
        }.get(ctx.operation, Scope.MEMORY_WRITE)
        return await self._authorize(ctx.request_context, ctx.bank_id, scope)

    async def validate_retain(self, ctx: RetainContext) -> ValidationResult:
        return await self._authorize(ctx.request_context, ctx.bank_id, Scope.MEMORY_WRITE)

    async def validate_recall(self, ctx: RecallContext) -> ValidationResult:
        return await self._authorize(ctx.request_context, ctx.bank_id, Scope.MEMORY_READ)

    async def validate_reflect(self, ctx: ReflectContext) -> ValidationResult:
        return await self._authorize(ctx.request_context, ctx.bank_id, Scope.REFLECT)

    async def validate_consolidate(self, ctx: ConsolidateContext) -> ValidationResult:
        return await self._authorize(ctx.request_context, ctx.bank_id, Scope.MEMORY_WRITE)

    async def validate_bank_read(self, ctx: BankReadContext) -> ValidationResult:
        scope = Scope.KNOWLEDGE_READ if ctx.operation in _KNOWLEDGE_READS else Scope.MEMORY_READ
        # Profile reads also authorize audit/LLM trace/archive routes in core.
        # Knowledge reads have their own gates and must not inherit that access.
        return await self._authorize(ctx.request_context, ctx.bank_id, scope)

    async def validate_bank_write(self, ctx: BankWriteContext) -> ValidationResult:
        if ctx.operation == BankWriteOperation.DELETE_BANK:
            return await self._authorize(ctx.request_context, ctx.bank_id, None, lifecycle_purpose="delete_workspace")
        if ctx.request_context.internal:
            scope = (
                Scope.MEMORY_WRITE
                if ctx.operation
                in {
                    BankWriteOperation.SUBMIT_ASYNC_CONSOLIDATION,
                    BankWriteOperation.SUBMIT_ASYNC_GRAPH_MAINTENANCE,
                    BankWriteOperation.SUBMIT_ASYNC_VECTOR_INDEX_MAINTENANCE,
                }
                else None
            )
            return await self._authorize(ctx.request_context, ctx.bank_id, scope)
        if ctx.operation not in _MEMORY_WRITES:
            return ValidationResult.reject("Business Keys cannot perform this management operation")
        return await self._authorize(ctx.request_context, ctx.bank_id, Scope.MEMORY_WRITE)

    async def validate_create_bank(self, ctx: CreateBankContext) -> ValidationResult:
        return await self._authorize(ctx.request_context, ctx.bank_id, None, lifecycle_purpose="create_workspace")

    async def validate_mental_model_get(self, ctx: MentalModelGetContext) -> ValidationResult:
        scope = Scope.KNOWLEDGE_READ if ctx.read_origin == "knowledge_page" else Scope.MEMORY_READ
        return await self._authorize(ctx.request_context, ctx.bank_id, scope)

    async def validate_mental_model_refresh(self, ctx: MentalModelRefreshContext) -> ValidationResult:
        return await self._authorize(ctx.request_context, ctx.bank_id, Scope.MEMORY_WRITE)

    async def bank_list_scope(self, request_context: RequestContext) -> BankListScope:
        repository = await repository_for(self.context.get_memory_engine(), self.settings)
        if request_context.internal:
            from hindsight_api.engine.memory_engine import get_current_schema

            # Maintenance may enumerate banks without a customer credential.
            # Frozen/deleting workspaces drain queued jobs, but get no new sweep.
            workspace = await repository.maintenance_workspace(get_current_schema())
            return BankListScope(bank_ids=[workspace.workspace_id] if workspace else [])
        principal = await repository.authenticate(request_context.api_key)
        return BankListScope(bank_ids=[principal.workspace_id] if Scope.MEMORY_READ in principal.scopes else [])

    async def filter_mcp_tools(
        self,
        bank_id: str,
        request_context: RequestContext,
        tools: frozenset[str],
    ) -> frozenset[str]:
        repository = await repository_for(self.context.get_memory_engine(), self.settings)
        try:
            principal = await repository.authenticate(request_context.api_key)
        except ServiceError:
            return frozenset()
        allowed: set[str] = set()
        if Scope.MEMORY_READ in principal.scopes:
            allowed.update(
                {
                    "recall",
                    "list_banks",
                    "get_bank_profile",
                    "list_memories",
                    "get_memory",
                    "list_documents",
                    "get_document",
                    "list_mental_models",
                    "get_mental_model",
                }
            )
        if Scope.MEMORY_WRITE in principal.scopes:
            allowed.update(
                {
                    "retain",
                    "create_mental_model",
                    "refresh_mental_model",
                    "create_knowledge_folder",
                    "create_knowledge_page",
                    "update_knowledge_node",
                    "delete_knowledge_node",
                }
            )
        if Scope.REFLECT in principal.scopes:
            allowed.add("reflect")
        if Scope.KNOWLEDGE_READ in principal.scopes:
            allowed.update({"get_knowledge_base_tree", "search_knowledge_base", "get_knowledge_page"})
        return tools & frozenset(allowed)
