"""Bootstrap TaskPal when executed as the top-level script.

Single responsibility: expose the process entry point so ``python main.py``
(or an equivalent launcher) can start the menubar application without importing
package internals at interpreter startup more than necessary.
"""


def main() -> None:
    """Start TaskPal."""
    import os
    from dotenv import load_dotenv
    # override=True so .env is authoritative — shell exports don't
    # silently win when a user edits .env and expects it to take effect.
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)

    from taskpal.app import TaskPalApp
    TaskPalApp().run()


if __name__ == "__main__":
    main()
