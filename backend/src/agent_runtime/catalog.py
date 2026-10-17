"""The runtime's catalogue: what agent definitions may reference (R15.2).

Composition root for the agent loader's `Catalog`: the registered tools and
hooks, so `runtime agents validate` checks definitions against the real thing.
"""

from agent_runtime.agents.loader import Catalog
from agent_runtime.tools.builtin import default_tools
from agent_runtime.tools.hooks import default_hooks


def default_catalog() -> Catalog:
    return Catalog(tools=default_tools().catalog(), hooks=default_hooks().catalog())
