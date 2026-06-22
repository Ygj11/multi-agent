from __future__ import annotations

"""工具注册表。"""

import inspect
from typing import Any

from app.schemas.agent_card import AgentCard
from app.mcp.schemas import MCPToolCapability
from app.auth.authorization_service import AuthorizationService
from app.auth.principal import Principal
from app.tools.base import ToolCallable, ToolDefinition
from app.tools.contracts import ToolContractCatalog
from app.tools.result_schemas import RESULT_SCHEMA_REGISTRY


class ToolRegistry:
    """Registers public tools and agent-private tools.

    The old `register/get/list_tools` methods remain for compatibility with
    existing tests and adapters.
    """

    def __init__(self, contract_catalog: ToolContractCatalog | None = None) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._private_tools_by_agent: dict[str, set[str]] = {}
        self._public_tools: set[str] = set()
        self._mcp_tools: set[str] = set()
        self.contract_catalog = contract_catalog or ToolContractCatalog.load()

    def register(self, name: str, tool: ToolCallable) -> None:
        """Compatibility API: register a public tool."""
        self.register_public(name=name, tool=tool)

    def register_public(
        self,
        name: str,
        tool: ToolCallable,
        description: str = "",
        is_write: bool = False,
        parameters: dict[str, Any] | None = None,
        required_scopes: list[str] | None = None,
        resource_type: str | None = None,
        resource_id_arg: str | None = None,
        operation: str = "read",
        data_domains: list[str] | None = None,
        risk_level: str = "low",
        precondition_id: str | None = None,
        idempotency_required: bool = False,
    ) -> None:
        """Register a tool available to agents that allow public tools."""
        self._tools[name] = self._with_contract(ToolDefinition(
            name=name,
            callable=tool,
            description=description,
            scope="public",
            source="local",
            is_write=is_write,
            parameters=normalize_tool_parameters(parameters) if parameters is not None else {},
            required_scopes=required_scopes or [],
            resource_type=resource_type,
            resource_id_arg=resource_id_arg,
            operation=operation,  # type: ignore[arg-type]
            data_domains=data_domains or [],
            risk_level=risk_level,  # type: ignore[arg-type]
            precondition_id=precondition_id,
            idempotency_required=idempotency_required,
        ))
        self._public_tools.add(name)

    def register_public_tool(
        self,
        name: str,
        tool: ToolCallable,
        description: str = "",
        is_write: bool = False,
        parameters: dict[str, Any] | None = None,
        required_scopes: list[str] | None = None,
        resource_type: str | None = None,
        resource_id_arg: str | None = None,
        operation: str = "read",
        data_domains: list[str] | None = None,
        risk_level: str = "low",
        precondition_id: str | None = None,
        idempotency_required: bool = False,
    ) -> None:
        """New API alias for registering a public tool."""
        self.register_public(
            name=name,
            tool=tool,
            description=description,
            is_write=is_write,
            parameters=parameters,
            required_scopes=required_scopes,
            resource_type=resource_type,
            resource_id_arg=resource_id_arg,
            operation=operation,
            data_domains=data_domains,
            risk_level=risk_level,
            precondition_id=precondition_id,
            idempotency_required=idempotency_required,
        )

    def register_private(
        self,
        *,
        agent_name: str,
        name: str,
        tool: ToolCallable,
        description: str = "",
        is_write: bool = False,
        parameters: dict[str, Any] | None = None,
        required_scopes: list[str] | None = None,
        resource_type: str | None = None,
        resource_id_arg: str | None = None,
        operation: str = "read",
        data_domains: list[str] | None = None,
        risk_level: str = "low",
        precondition_id: str | None = None,
        idempotency_required: bool = False,
    ) -> None:
        """Register a tool bound to one sub agent."""
        self._tools[name] = self._with_contract(ToolDefinition(
            name=name,
            callable=tool,
            description=description,
            scope="private",
            source="local",
            agent_name=agent_name,
            is_write=is_write,
            parameters=normalize_tool_parameters(parameters) if parameters is not None else {},
            required_scopes=required_scopes or [],
            resource_type=resource_type,
            resource_id_arg=resource_id_arg,
            operation=operation,  # type: ignore[arg-type]
            data_domains=data_domains or [],
            risk_level=risk_level,  # type: ignore[arg-type]
            precondition_id=precondition_id,
            idempotency_required=idempotency_required,
        ))
        self._private_tools_by_agent.setdefault(agent_name, set()).add(name)

    def register_agent_tool(
        self,
        agent_name: str,
        tool_name: str,
        tool: ToolCallable,
        description: str = "",
        is_write: bool = False,
        parameters: dict[str, Any] | None = None,
        required_scopes: list[str] | None = None,
        resource_type: str | None = None,
        resource_id_arg: str | None = None,
        operation: str = "read",
        data_domains: list[str] | None = None,
        risk_level: str = "low",
        precondition_id: str | None = None,
        idempotency_required: bool = False,
    ) -> None:
        """New API alias for registering an agent-private tool."""
        self.register_private(
            agent_name=agent_name,
            name=tool_name,
            tool=tool,
            description=description,
            is_write=is_write,
            parameters=parameters,
            required_scopes=required_scopes,
            resource_type=resource_type,
            resource_id_arg=resource_id_arg,
            operation=operation,
            data_domains=data_domains,
            risk_level=risk_level,
            precondition_id=precondition_id,
            idempotency_required=idempotency_required,
        )

    def get(self, name: str) -> ToolCallable | None:
        """Compatibility API: return the callable only."""
        definition = self._tools.get(name)
        return definition.callable if definition else None

    def get_definition(self, name: str) -> ToolDefinition | None:
        """Return full tool metadata."""
        return self._tools.get(name)

    def register_mcp_tools(self, mcp_tools: list[MCPToolCapability]) -> None:
        """Register MCP tools discovered at startup or refresh."""
        for capability in mcp_tools:
            self._tools[capability.registered_tool_name] = self._with_contract(ToolDefinition(
                name=capability.registered_tool_name,
                callable=_mcp_placeholder,
                description=capability.description,
                scope="mcp",
                source="mcp",
                server_name=capability.server_name,
                original_name=capability.original_tool_name,
                parameters=normalize_tool_parameters(capability.input_schema),
                enabled=capability.enabled,
                metadata={
                    "server_name": capability.server_name,
                    "original_tool_name": capability.original_tool_name,
                    "raw_schema": capability.raw_schema,
                },
                operation="execute",
                risk_level="medium",
            ))
            self._mcp_tools.add(capability.registered_tool_name)

    def list_mcp_tools(self) -> list[str]:
        return sorted(name for name in self._mcp_tools if name in self._tools)

    def get_mcp_tool(self, registered_tool_name: str) -> ToolDefinition | None:
        definition = self._tools.get(registered_tool_name)
        return definition if definition and definition.source == "mcp" else None

    def get_tool(self, tool_name: str) -> ToolCallable | None:
        """Return a tool callable by name."""
        return self.get(tool_name)

    def list_tools(self) -> list[str]:
        """List all registered tool names."""
        return sorted(self._tools)

    def list_public_tools(self) -> list[str]:
        """List public tool names."""
        return sorted(self._public_tools)

    def list_agent_private_tools(self, agent_name: str) -> list[str]:
        """List private tool names for one agent."""
        return sorted(self._private_tools_by_agent.get(agent_name, set()))

    def list_private_tools(self, agent_name: str) -> list[str]:
        """New API alias for listing agent-private tools."""
        return self.list_agent_private_tools(agent_name)

    def list_available_tools_for_agent(
        self,
        agent_name: str,
        card: AgentCard | None = None,
        principal: Principal | dict[str, Any] | None = None,
        authorization_service: AuthorizationService | None = None,
    ) -> list[str]:
        """Return tools allowed by AgentCard.private_tools/public_tools_allowed."""
        private_names = set(card.private_tools if card else self._private_tools_by_agent.get(agent_name, set()))
        tools = {name for name in private_names if name in self._tools}
        if card and card.public_tools_allowed:
            tools.update(self._public_tools)
        elif card is None:
            tools.update(self._public_tools)
        if card:
            tools.update(name for name in card.mcp_tools if self._is_enabled_mcp_tool(name))
            for scope in card.mcp_tool_scopes:
                tools.update(name for name in self._mcp_tools if name.startswith(scope) and self._is_enabled_mcp_tool(name))
        visible = sorted(name for name in tools if self._tools.get(name, None) is not None and self._tools[name].enabled)
        if authorization_service is None:
            return visible
        principal_obj = self._coerce_principal(principal)
        allowed: list[str] = []
        for name in visible:
            decision = authorization_service.check_tool_access(principal=principal_obj, tool_definition=self._tools[name])
            if decision.allowed:
                allowed.append(name)
        return allowed

    def list_tool_names_for_agent(self, agent_card: AgentCard) -> list[str]:
        """Return visible tool names for an AgentCard."""
        return self.list_available_tools_for_agent(agent_card.agent_name, agent_card)

    def list_tools_for_agent(
        self,
        agent_card: AgentCard,
        principal: Principal | dict[str, Any] | None = None,
        authorization_service: AuthorizationService | None = None,
    ) -> list[dict[str, Any]]:
        """Return OpenAI-compatible tool schemas visible to one AgentCard."""
        schemas: list[dict[str, Any]] = []
        for name in self.list_available_tools_for_agent(
            agent_card.agent_name,
            agent_card,
            principal=principal,
            authorization_service=authorization_service,
        ):
            schema = self.get_tool_schema(name)
            if schema is not None:
                schemas.append(schema)
        return schemas

    def get_tool_schema(self, tool_name: str) -> dict[str, Any] | None:
        """Return one tool schema usable by LLM function calling."""
        definition = self._tools.get(tool_name)
        if definition is None:
            return None
        parameters = (
            normalize_tool_parameters(definition.parameters)
            if definition.parameters
            else self._parameters_from_signature(definition)
        )
        return {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": definition.description or f"Execute {tool_name}.",
                "parameters": parameters,
            },
        }

    def _parameters_from_signature(self, definition: ToolDefinition) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        required: list[str] = []
        try:
            signature = inspect.signature(definition.callable)
        except (TypeError, ValueError):
            signature = None
        if signature:
            for name, parameter in signature.parameters.items():
                if name == "kwargs" or parameter.kind in {parameter.VAR_KEYWORD, parameter.VAR_POSITIONAL}:
                    continue
                properties[name] = {"type": self._json_type(parameter.annotation)}
                if parameter.default is inspect._empty:
                    required.append(name)
        return {"type": "object", "properties": properties, "required": required}

    def get_required_arguments(self, tool_name: str) -> list[str]:
        """Return normalized required argument names for a registered tool."""
        definition = self._tools.get(tool_name)
        if definition is None:
            return []
        parameters = (
            normalize_tool_parameters(definition.parameters)
            if definition.parameters
            else self._parameters_from_signature(definition)
        )
        return [str(item) for item in parameters.get("required", [])]

    def validate_contracts(self, *, strict: bool = False, check_unknown: bool = True) -> list[str]:
        """Validate registered tools against the loaded contract catalog."""
        errors: list[str] = []
        for name, definition in sorted(self._tools.items()):
            if definition.contract is None:
                errors.append(f"tool missing contract: {name}")
                continue
            result_schema = definition.contract.result_schema
            if result_schema and result_schema not in RESULT_SCHEMA_REGISTRY:
                errors.append(f"{name} references unknown result_schema: {result_schema}")
        if check_unknown:
            registered_names = set(self._tools)
            for name in sorted(self.contract_catalog.explicit_tool_names() - registered_names):
                errors.append(f"contract references unknown tool: {name}")
        if strict and errors:
            raise ValueError("; ".join(errors))
        return errors

    def is_tool_available_for_agent(self, agent_name: str, tool_name: str, card: AgentCard | None = None) -> bool:
        """Check card-driven tool availability."""
        if tool_name not in self._tools:
            return False
        if card is None:
            definition = self._tools[tool_name]
            return definition.scope == "public" or definition.agent_name == agent_name
        if tool_name in card.private_tools:
            return True
        if card.public_tools_allowed and tool_name in self._public_tools:
            return True
        if self._is_enabled_mcp_tool(tool_name) and tool_name in card.mcp_tools:
            return True
        if self._is_enabled_mcp_tool(tool_name):
            return any(tool_name.startswith(scope) for scope in card.mcp_tool_scopes)
        return False

    def _is_enabled_mcp_tool(self, name: str) -> bool:
        definition = self._tools.get(name)
        return bool(definition and definition.source == "mcp" and definition.enabled)

    def _with_contract(self, definition: ToolDefinition) -> ToolDefinition:
        contract = self.contract_catalog.contract_for(definition.name, source=definition.source)
        if contract is None:
            return definition
        data_classification = contract.data_classification
        return definition.model_copy(
            update={
                "contract": contract,
                "data_classification": data_classification,
            }
        )

    @staticmethod
    def _coerce_principal(value: Principal | dict[str, Any] | None) -> Principal | None:
        if isinstance(value, Principal):
            return value
        if isinstance(value, dict):
            try:
                return Principal(**value)
            except Exception:
                return None
        return None

    @staticmethod
    def _json_type(annotation: Any) -> str:
        annotation_text = str(annotation)
        if "int" in annotation_text:
            return "integer"
        if "float" in annotation_text:
            return "number"
        if "bool" in annotation_text:
            return "boolean"
        if "dict" in annotation_text:
            return "object"
        if "list" in annotation_text:
            return "array"
        return "string"


async def _mcp_placeholder(**kwargs: Any) -> None:
    """Never called directly; ToolExecutor dispatches source=mcp to MCPClientManager."""
    raise RuntimeError("mcp tools must be executed through MCPClientManager")


def normalize_tool_parameters(parameters: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize any local or MCP input schema to an object JSON schema."""
    if not isinstance(parameters, dict):
        return {"type": "object", "properties": {}, "required": []}

    normalized = dict(parameters)
    normalized["type"] = "object"

    properties = normalized.get("properties")
    if not isinstance(properties, dict):
        properties = {}
    normalized["properties"] = properties

    required = normalized.get("required")
    if not isinstance(required, list):
        required = []
    normalized["required"] = [str(item) for item in required]

    return normalized
