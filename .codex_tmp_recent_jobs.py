import asyncio
from sqlalchemy import text
from telemetry.db import async_engine

Q = """
select job_id, instance_id, run_id, deployment_type, status, attempt_count, error_message, created_at, updated_at
from deployment_jobs
order by created_at desc
limit 10
"""

async def main():
    async with async_engine.connect() as conn:
        rows = (await conn.execute(text(Q))).mappings().all()
        for row in rows:
            print(dict(row))

asyncio.run(main())
