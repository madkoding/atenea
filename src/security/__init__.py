"""Cross-cutting security helpers: URL, prompt, secret, and TLS concerns.

Each submodule is independent — they used to live as separate ``src/``
modules and the package is a thin namespace to group them. Code that
used to import ``from src.security.url_safety import ...`` should now use
``from src.security.url_safety import ...``.
"""
