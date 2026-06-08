"""Chat pipeline: chat handler, processor, agent loop, context, helpers.

The agent loop lives here too because the two share a heavy amount of
plumbing (context budget, model context, helpers). Keep the agent loop's
historical import path ``src.agent_loop`` working via the facade
``src.chat.agent_loop``; downstream code that imported
``from src.chat.handler import ...`` should now use
``from src.chat.handler import ...`` (and likewise for the other modules),
but the legacy module names continue to work as re-export shims.
"""
