import inspect
import re
from typing import Any, Callable, Dict, List, Optional, Sequence

from composio.core.provider import AgenticProvider, AgenticProviderExecuteFn

# Agno natively accepts standard Python callables as tools
AgnoToolCollection = List[Callable]

_TYPE_MAPPING: Dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


class AgnoProvider(AgenticProvider[Callable, AgnoToolCollection], name="agno"):
    """Custom Composio provider for Agno AI Agents."""

    def wrap_tool(self, tool: Any, execute_tool: AgenticProviderExecuteFn) -> Callable:
        """Transform a Composio tool into an Agno-compatible Python function.

        The key challenge is that Agno wraps every callable with Pydantic's
        ``validate_call``, which internally calls ``get_type_hints()`` to resolve
        parameter types.  ``get_type_hints()`` reads from ``__annotations__``, NOT
        from ``__signature__``.  If ``__annotations__`` is empty/missing Pydantic
        raises a ``KeyError`` for every parameter and the tool silently fails with
        "Could not add tool ... 'param_name'" warnings.

        Fix: set both ``__signature__`` (so Agno builds the correct JSON schema)
        AND ``__annotations__`` (so Pydantic/validate_call can introspect types).
        """

        # 1. Parse the Composio JSON schema into inspect.Parameters
        parameters: List[inspect.Parameter] = []
        annotations: Dict[str, Any] = {}

        properties: Dict[str, Any] = tool.input_parameters.get("properties", {})
        required_params: List[str] = tool.input_parameters.get("required", [])

        for param_name, param_info in properties.items():
            param_type_str = param_info.get("type", "string")
            if param_type_str == "array":
                items_info = param_info.get("items", {})
                if isinstance(items_info, dict):
                    items_type_str = items_info.get("type", "string")
                    items_type = _TYPE_MAPPING.get(items_type_str, str)
                else:
                    items_type = str
                param_type = list[items_type]
            elif param_type_str == "object":
                param_type = dict
            else:
                param_type = _TYPE_MAPPING.get(param_type_str, Any)

            is_required = param_name in required_params
            default_value = inspect.Parameter.empty if is_required else param_info.get("default", None)

            annotations[param_name] = param_type
            parameters.append(
                inspect.Parameter(
                    name=param_name,
                    kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=default_value,
                    annotation=param_type,
                )
            )

        # Required params must come before optional ones (Python signature rule)
        parameters.sort(key=lambda p: p.default is not inspect.Parameter.empty)

        # 2. Build a clean tool name (OpenAI only allows [a-zA-Z0-9_-])
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", tool.slug.lower())

        # 3. Create the execution wrapper
        #    We accept **kwargs at runtime so it works regardless of which params
        #    the model chooses to pass.  The __signature__ / __annotations__ below
        #    are what Agno/Pydantic use for schema generation — they never actually
        #    enforce the signature at call time for tool functions.
        def execute_wrapper(**kwargs: Any) -> Dict[str, Any]:
            result = execute_tool(tool.slug, kwargs)
            if not result.get("successful", False):
                # Return the error to the agent instead of crashing the app
                return {"error": result.get("error", "Tool execution failed"), "status": "failed"}
            return result.get("data", {})

        # 4. Attach metadata
        execute_wrapper.__name__ = safe_name
        execute_wrapper.__qualname__ = safe_name
        execute_wrapper.__doc__ = tool.description or f"Execute {tool.slug}"

        # 5. Attach __signature__ — Agno reads this to build the OpenAI tool schema
        execute_wrapper.__signature__ = inspect.Signature(parameters)

        # 6. Attach __annotations__ — Pydantic's validate_call reads this via
        #    get_type_hints().  Without it every tool registration raises KeyError
        #    and falls back to a "Could not add tool" WARNING, meaning the model
        #    never receives the tool definition.
        execute_wrapper.__annotations__ = annotations

        return execute_wrapper

    def wrap_tools(
        self,
        tools: Sequence[Any],
        execute_tool: AgenticProviderExecuteFn,
    ) -> AgnoToolCollection:
        """Transform a collection of Composio tools into Agno callables."""
        return [self.wrap_tool(tool, execute_tool) for tool in tools]