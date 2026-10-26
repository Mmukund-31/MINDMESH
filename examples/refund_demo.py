"""The signature demonstration as a script (same as `mindmesh demo refund`)."""

import asyncio

from mindmesh.cli import _demo_refund

if __name__ == "__main__":
    asyncio.run(_demo_refund(database_url="sqlite:///refund-demo.db", project="default", model=None, fresh=True))
