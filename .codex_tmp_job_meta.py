import asyncio
from sqlalchemy import text
from telemetry.db import async_engine

RUN_ID = "5bc045fe-900d-4936-b848-a1293682119b"
Q = """
select job_id, deployment_type, status, attempt_count, max_attempts, error_message, created_at, updated_at
from deployment_jobs
where run_id=:run_id
order by created_at desc
"""

async def main():
    async with async_engine.connect() as conn:
        rows = (await conn.execute(text(Q), {"run_id": RUN_ID})).mappings().all()
        for row in rows:
            print(dict(row))

asyncio.run(main())
