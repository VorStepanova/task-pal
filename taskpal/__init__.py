"""TaskPal application package root.

Single responsibility: mark the ``taskpal`` directory as a Python package so
absolute imports (for example ``from taskpal.app import ...``) resolve correctly
across the menubar app, chat UI bridge, and reminder subsystems.
"""
