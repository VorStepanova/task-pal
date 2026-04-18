"""Bootstrap TaskPal when executed as the top-level script.

Single responsibility: expose the process entry point so ``python main.py``
(or an equivalent launcher) can start the menubar application without importing
package internals at interpreter startup more than necessary.
"""


def main() -> None:
    """Start TaskPal."""
    import os
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

    from taskpal.app import TaskPalApp
    TaskPalApp().run()


if __name__ == "__main__":
    main()
