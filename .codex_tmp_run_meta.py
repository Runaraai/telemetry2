import asyncio
from sqlalchemy import text
from telemetry.db import async_engine

RUN_ID = "5bc045fe-900d-4936-b848-a1293682119b"
Q = """
select run_id, instance_id, provider, gpu_model, gpu_count, status, start_time, end_time, tags, notes
from runs
where run_id=:run_id
"""

async def main():
    async with async_engine.connect() as conn:
        row = (await conn.execute(text(Q), {"run_id": RUN_ID})).mappings().first()
        print(dict(row) if row else None)

asyncio.run(main())
