import asyncio
from sqlalchemy import text
from telemetry.db import async_engine

async def main():
    async with async_engine.connect() as conn:
        q1 = "select count(*) from workload_metrics"
        q2 = "select count(*) from kernel_profiles"
        q3 = "select count(*) from bottleneck_analyses"
        q4 = """
        select wm.run_id, r.instance_id, r.status, wm.created_at
        from workload_metrics wm
        join runs r on r.run_id = wm.run_id
        order by wm.created_at desc
        limit 5
        """
        for name, q in [("workload_total", q1), ("kernel_profiles_total", q2), ("bottleneck_total", q3)]:
            print(name, (await conn.execute(text(q))).scalar())
        rows = (await conn.execute(text(q4))).mappings().all()
        print("latest_workload_rows", len(rows))
        for row in rows:
            print(dict(row))

asyncio.run(main())
