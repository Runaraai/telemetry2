import asyncio
from sqlalchemy import text
from telemetry.db import async_engine

RUN_ID = "5bc045fe-900d-4936-b848-a1293682119b"
QUERIES = [
    ("run_status", "select status from runs where run_id=:run_id"),
    ("gpu_metrics", "select count(*) from gpu_metrics where run_id=:run_id"),
    ("workload_metrics", "select count(*) from workload_metrics where run_id=:run_id"),
    ("kernel_profiles", "select count(*) from kernel_profiles where run_id=:run_id"),
    ("kernel_categories", "select count(*) from kernel_categories kc join kernel_profiles kp on kc.profile_id=kp.profile_id where kp.run_id=:run_id"),
    ("bottleneck_analyses", "select count(*) from bottleneck_analyses where run_id=:run_id"),
]

async def main():
    async with async_engine.connect() as conn:
        for name, query in QUERIES:
            result = await conn.execute(text(query), {"run_id": RUN_ID})
            print(name, result.scalar())

asyncio.run(main())
