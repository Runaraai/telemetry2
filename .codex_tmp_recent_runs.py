import asyncio
from sqlalchemy import text
from telemetry.db import async_engine

Q = """
select r.run_id, r.instance_id, r.status, r.start_time, r.end_time,
  (select count(*) from gpu_metrics gm where gm.run_id = r.run_id) as gpu_samples,
  (select count(*) from workload_metrics wm where wm.run_id = r.run_id) as workload_rows,
  (select count(*) from kernel_profiles kp where kp.run_id = r.run_id) as kernel_profiles,
  (select count(*) from bottleneck_analyses ba where ba.run_id = r.run_id) as bottleneck_rows
from runs r
order by r.start_time desc
limit 8
"""

async def main():
    async with async_engine.connect() as conn:
        rows = (await conn.execute(text(Q))).mappings().all()
        for row in rows:
            d = dict(row)
            print(d)

asyncio.run(main())
