"""Bootstrap logic for telemetry database schema."""

from __future__ import annotations

import os
import re
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


def _migration_fallback_email() -> str:
    """Return the email used to backfill orphaned rows during migrations."""
    return os.getenv("MIGRATION_FALLBACK_EMAIL", "demo@omniference.com")


IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _normalize_identifier(value: str) -> str:
    """Return a safe SQL identifier or raise ValueError."""

    if not IDENTIFIER_RE.match(value):
        raise ValueError(f"Invalid SQL identifier: {value!r}")
    return value


async def run_bootstrap(
    engine: AsyncEngine,
    *,
    schema: str = "public",
    retention_days: int = 30,
) -> None:
    """Ensure Timescale extensions, schema, tables, and policies exist."""

    safe_schema = _normalize_identifier(schema)
    retention_days = max(1, int(retention_days))

    statements: Iterable[str] = (
        f"CREATE SCHEMA IF NOT EXISTS {safe_schema};",
        "CREATE EXTENSION IF NOT EXISTS timescaledb;",
        "CREATE EXTENSION IF NOT EXISTS pgcrypto;",
        f"SET search_path TO {safe_schema}, public;",
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            instance_id VARCHAR(255) NOT NULL,
            provider VARCHAR(50),
            gpu_model VARCHAR(50),
            gpu_count INTEGER,
            start_time TIMESTAMPTZ NOT NULL,
            end_time TIMESTAMPTZ,
            status VARCHAR(20) NOT NULL,
            tags JSONB,
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_runs_instance ON runs(instance_id);",
        "CREATE INDEX IF NOT EXISTS idx_runs_start_time ON runs(start_time DESC);",
        "CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);",
        """
        CREATE TABLE IF NOT EXISTS gpu_metrics (
            time TIMESTAMPTZ NOT NULL,
            run_id UUID NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            gpu_id INTEGER NOT NULL,
            -- Core utilization
            gpu_utilization REAL,
            sm_utilization REAL,
            hbm_utilization REAL,
            sm_occupancy REAL,
            tensor_active REAL,
            fp64_active REAL,
            fp32_active REAL,
            fp16_active REAL,
            gr_engine_active REAL,
            -- Memory
            memory_used_mb REAL,
            memory_total_mb REAL,
            memory_utilization REAL,
            -- Clocks
            sm_clock_mhz REAL,
            memory_clock_mhz REAL,
            -- Power
            power_draw_watts REAL,
            power_limit_watts REAL,
            -- Temperature
            temperature_celsius REAL,
            memory_temperature_celsius REAL,
            -- PCIe
            pcie_rx_mb_per_sec REAL,
            pcie_tx_mb_per_sec REAL,
            pcie_replay_errors INTEGER DEFAULT 0,
            -- NVLink
            nvlink_rx_mb_per_sec REAL,
            nvlink_tx_mb_per_sec REAL,
            nvlink_bandwidth_total REAL,
            nvlink_replay_errors INTEGER DEFAULT 0,
            nvlink_recovery_errors INTEGER DEFAULT 0,
            nvlink_crc_errors INTEGER DEFAULT 0,
            -- ECC errors
            ecc_sbe_errors INTEGER DEFAULT 0,
            ecc_dbe_errors INTEGER DEFAULT 0,
            ecc_sbe_aggregate INTEGER DEFAULT 0,
            ecc_dbe_aggregate INTEGER DEFAULT 0,
            -- Throttle and health
            throttle_reasons INTEGER DEFAULT 0,
            throttle_thermal INTEGER DEFAULT 0,
            throttle_power INTEGER DEFAULT 0,
            throttle_sw_power INTEGER DEFAULT 0,
            xid_errors INTEGER DEFAULT 0,
            -- Configuration
            compute_mode INTEGER,
            persistence_mode INTEGER,
            ecc_mode INTEGER,
            power_min_limit REAL,
            power_max_limit REAL,
            slowdown_temp REAL,
            shutdown_temp REAL,
            total_energy_joules REAL,
            -- Retired pages
            retired_pages_sbe INTEGER DEFAULT 0,
            retired_pages_dbe INTEGER DEFAULT 0,
            retired_pages_pending INTEGER DEFAULT 0,
            PRIMARY KEY (time, run_id, gpu_id)
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_gpu_metrics_run_id ON gpu_metrics(run_id, time DESC);",
        "CREATE INDEX IF NOT EXISTS idx_gpu_metrics_gpu_id ON gpu_metrics(run_id, gpu_id, time DESC);",
        """
        CREATE TABLE IF NOT EXISTS run_summaries (
            run_id UUID PRIMARY KEY REFERENCES runs(run_id) ON DELETE CASCADE,
            duration_seconds REAL,
            total_samples INTEGER,
            avg_gpu_utilization REAL,
            max_gpu_utilization REAL,
            avg_memory_utilization REAL,
            avg_power_draw_watts REAL,
            max_power_draw_watts REAL,
            total_energy_wh REAL,
            avg_temperature REAL,
            max_temperature REAL,
            computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS gpu_policy_events (
            event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id UUID NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            gpu_id INTEGER NOT NULL,
            event_time TIMESTAMPTZ NOT NULL,
            event_type VARCHAR(50) NOT NULL,
            severity VARCHAR(20) NOT NULL,
            message TEXT NOT NULL,
            metric_value REAL,
            threshold_value REAL,
            metadata JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_policy_events_run_id ON gpu_policy_events(run_id, event_time DESC);",
        "CREATE INDEX IF NOT EXISTS idx_policy_events_severity ON gpu_policy_events(run_id, severity, event_time DESC);",
        """
        CREATE TABLE IF NOT EXISTS gpu_topology (
            topology_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id UUID NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            topology_data JSONB NOT NULL,
            captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (run_id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS credential_store (
            credential_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            provider VARCHAR(50) NOT NULL,
            name VARCHAR(100) NOT NULL,
            credential_type VARCHAR(50) NOT NULL,
            secret_ciphertext TEXT NOT NULL,
            description TEXT,
            metadata JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_used_at TIMESTAMPTZ,
            UNIQUE (provider, name, credential_type)
        );
        """,
        "SELECT create_hypertable('gpu_metrics', 'time', if_not_exists => TRUE);",
        f"SELECT add_retention_policy('gpu_metrics', INTERVAL '{retention_days} days', if_not_exists => TRUE);",
    )

    timescale_keywords = ("timescaledb", "create_hypertable", "add_retention_policy")

    # Detect whether TimescaleDB is available so we can skip its statements
    # without poisoning the transaction.
    _has_timescale = False
    async with engine.connect() as probe:
        try:
            result = await probe.execute(
                text("SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb'")
            )
            _has_timescale = result.scalar() is not None
        except Exception:
            pass

    async with engine.begin() as conn:
        for statement in statements:
            is_timescale = any(kw in statement.lower() for kw in timescale_keywords)
            if is_timescale and not _has_timescale:
                print(f"TimescaleDB not available, skipping: {statement.strip()[:80]}")
                continue
            try:
                nested = await conn.begin_nested()
                await conn.execute(text(statement))
                await nested.commit()
            except Exception as e:
                await nested.rollback()
                print(f"Warning: bootstrap statement failed (continuing): {statement.strip()[:80]} — {e}")
        
        # Add new columns to existing gpu_metrics table (migration)
        await _migrate_gpu_metrics_table(conn, safe_schema)
        
        # Add SM profiling tables
        await _migrate_sm_profiling_tables(conn, safe_schema)
        
        # Add instance orchestration tables
        await _migrate_instance_orchestration_tables(conn, safe_schema)
        
        # Add deployment queue and provisioning tables
        await _migrate_deployment_queue_tables(conn, safe_schema)
        
        # Add user_id to runs table (migration)
        await _migrate_runs_user_id(conn, safe_schema)
        # Add provider to runs table (migration)
        await _migrate_runs_provider(conn, safe_schema)
        
        # Add user_id to provisioning_api_keys table (migration)
        await _migrate_provisioning_api_keys_user_id(conn, safe_schema)
        
        # Add user_id to credential_store table (migration)
        await _migrate_credential_store_user_id(conn, safe_schema)
        
        # Add ingest_token_hash to runs table and composite index (migration)
        await _migrate_runs_ingest_token(conn, safe_schema)

        # Add workload/kernel/bottleneck profiling tables
        await _migrate_profiling_tables(conn, safe_schema)

        # Add gpu_summary column to runs for agent upload GPU aggregates
        await _migrate_runs_gpu_summary(conn, safe_schema)

        # Add run_type column to runs for distinguishing monitoring/workload/kernel runs
        await _migrate_runs_run_type(conn, safe_schema)


async def _migrate_runs_ingest_token(conn, schema: str) -> None:
    """Add ingest_token_hash, token_created_at columns and composite index to runs table."""
    try:
        # Check if ingest_token_hash column exists
        check_stmt = text(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_schema = '{schema}' 
            AND table_name = 'runs' 
            AND column_name = 'ingest_token_hash'
        """)
        result = await conn.execute(check_stmt)
        exists = result.scalar_one_or_none()
        
        if not exists:
            await conn.execute(text(f"""
                ALTER TABLE {schema}.runs 
                ADD COLUMN ingest_token_hash VARCHAR(64);
            """))
            print("Added ingest_token_hash column to runs table")
        
        # Check if token_created_at column exists
        check_stmt_created = text(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_schema = '{schema}' 
            AND table_name = 'runs' 
            AND column_name = 'token_created_at'
        """)
        result_created = await conn.execute(check_stmt_created)
        created_exists = result_created.scalar_one_or_none()
        
        if not created_exists:
            await conn.execute(text(f"""
                ALTER TABLE {schema}.runs 
                ADD COLUMN token_created_at TIMESTAMPTZ;
            """))
            print("Added token_created_at column to runs table")
        
        # Add composite index for common query pattern (instance_id, status)
        await conn.execute(text(f"""
            CREATE INDEX IF NOT EXISTS idx_runs_instance_status 
            ON {schema}.runs(instance_id, status);
        """))
    except Exception as e:
        print(f"Note: ingest_token migration: {e}")


async def _migrate_runs_user_id(conn, schema: str) -> None:
    """Add user_id column to runs table if it doesn't exist."""
    try:
        # Check if user_id column exists
        check_stmt = text(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_schema = '{schema}' 
            AND table_name = 'runs' 
            AND column_name = 'user_id'
        """)
        result = await conn.execute(check_stmt)
        exists = result.scalar_one_or_none()
        
        if not exists:
            # First, ensure users table exists (should already exist from earlier)
            # Add user_id column with a temporary default (we'll update it)
            await conn.execute(text(f"""
                ALTER TABLE {schema}.runs 
                ADD COLUMN user_id UUID;
            """))
            
            # Create index
            await conn.execute(text(f"""
                CREATE INDEX IF NOT EXISTS idx_runs_user_id ON {schema}.runs(user_id);
            """))
            
            # Add foreign key constraint
            await conn.execute(text(f"""
                ALTER TABLE {schema}.runs 
                ADD CONSTRAINT fk_runs_user_id 
                FOREIGN KEY (user_id) REFERENCES {schema}.users(user_id) ON DELETE CASCADE;
            """))
            
            # For existing runs without user_id, assign them to the fallback account if it exists
            fallback_email = _migration_fallback_email()
            await conn.execute(text(f"""
                UPDATE {schema}.runs r
                SET user_id = (
                    SELECT user_id FROM {schema}.users
                    WHERE email = :fallback_email
                    LIMIT 1
                )
                WHERE r.user_id IS NULL;
            """), {"fallback_email": fallback_email})
            
            # Only enforce NOT NULL if every legacy row has been backfilled
            null_check = await conn.execute(text(f"""
                SELECT 1 FROM {schema}.runs 
                WHERE user_id IS NULL 
                LIMIT 1;
            """))
            has_nulls = null_check.scalar_one_or_none()
            if has_nulls:
                print("Note: runs table still has rows without user_id; column left nullable for now.")
            else:
                await conn.execute(text(f"""
                    ALTER TABLE {schema}.runs 
                    ALTER COLUMN user_id SET NOT NULL;
                """))
    except Exception as e:
        # Column might already exist or constraint might fail
        print(f"Note: user_id migration: {e}")


async def _migrate_runs_provider(conn, schema: str) -> None:
    """Add provider column to runs table if it doesn't exist."""
    try:
        check_stmt = text(f"""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = '{schema}'
            AND table_name = 'runs'
            AND column_name = 'provider'
        """)
        result = await conn.execute(check_stmt)
        exists = result.scalar_one_or_none()

        if not exists:
            await conn.execute(text(f"""
                ALTER TABLE {schema}.runs
                ADD COLUMN provider VARCHAR(50);
            """))
            await conn.execute(text(f"""
                CREATE INDEX IF NOT EXISTS idx_runs_provider ON {schema}.runs(provider);
            """))
    except Exception as e:
        print(f"Note: provider migration: {e}")


async def _migrate_provisioning_api_keys_user_id(conn, schema: str) -> None:
    """Add user_id column to provisioning_api_keys table if it doesn't exist."""
    try:
        # Check if user_id column exists
        check_stmt = text(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_schema = '{schema}' 
            AND table_name = 'provisioning_api_keys' 
            AND column_name = 'user_id'
        """)
        result = await conn.execute(check_stmt)
        exists = result.scalar_one_or_none()
        
        if not exists:
            # Add user_id column
            await conn.execute(text(f"""
                ALTER TABLE {schema}.provisioning_api_keys 
                ADD COLUMN user_id UUID;
            """))
            
            # Create index
            await conn.execute(text(f"""
                CREATE INDEX IF NOT EXISTS idx_provisioning_api_keys_user_id 
                ON {schema}.provisioning_api_keys(user_id);
            """))
            
            # For existing API keys without user_id, assign them to the fallback account if it exists
            fallback_email = _migration_fallback_email()
            await conn.execute(text(f"""
                UPDATE {schema}.provisioning_api_keys p
                SET user_id = (
                    SELECT user_id FROM {schema}.users
                    WHERE email = :fallback_email
                    LIMIT 1
                )
                WHERE p.user_id IS NULL;
            """), {"fallback_email": fallback_email})
            
            # Add foreign key constraint
            await conn.execute(text(f"""
                ALTER TABLE {schema}.provisioning_api_keys 
                ADD CONSTRAINT fk_provisioning_api_keys_user_id 
                FOREIGN KEY (user_id) REFERENCES {schema}.users(user_id) ON DELETE CASCADE;
            """))
            
            null_check = await conn.execute(text(f"""
                SELECT 1 FROM {schema}.provisioning_api_keys 
                WHERE user_id IS NULL 
                LIMIT 1;
            """))
            has_nulls = null_check.scalar_one_or_none()
            if has_nulls:
                print("Note: provisioning_api_keys still has rows without user_id; column left nullable for now.")
            else:
                await conn.execute(text(f"""
                    ALTER TABLE {schema}.provisioning_api_keys 
                    ALTER COLUMN user_id SET NOT NULL;
                """))
    except Exception as e:
        # Column might already exist or constraint might fail
        print(f"Note: provisioning_api_keys user_id migration: {e}")


async def _migrate_credential_store_user_id(conn, schema: str) -> None:
    """Add user_id column to credential_store table if it doesn't exist."""
    try:
        # Check if user_id column exists
        check_stmt = text(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_schema = '{schema}' 
            AND table_name = 'credential_store' 
            AND column_name = 'user_id'
        """)
        result = await conn.execute(check_stmt)
        exists = result.scalar_one_or_none()
        
        if not exists:
            # Add user_id column
            await conn.execute(text(f"""
                ALTER TABLE {schema}.credential_store 
                ADD COLUMN user_id UUID;
            """))
            
            # Create index
            await conn.execute(text(f"""
                CREATE INDEX IF NOT EXISTS idx_credential_store_user_id 
                ON {schema}.credential_store(user_id);
            """))
            
            # For existing credentials without user_id, assign them to the fallback account if it exists
            fallback_email = _migration_fallback_email()
            await conn.execute(text(f"""
                UPDATE {schema}.credential_store c
                SET user_id = (
                    SELECT user_id FROM {schema}.users
                    WHERE email = :fallback_email
                    LIMIT 1
                )
                WHERE c.user_id IS NULL;
            """), {"fallback_email": fallback_email})
            
            # Add foreign key constraint
            await conn.execute(text(f"""
                ALTER TABLE {schema}.credential_store 
                ADD CONSTRAINT fk_credential_store_user_id 
                FOREIGN KEY (user_id) REFERENCES {schema}.users(user_id) ON DELETE CASCADE;
            """))

        # Drop any legacy unique constraints that did not include user_id
        for constraint in (
            "uq_credential_provider_name_type",
            "credential_store_provider_name_credential_type_key",
        ):
            try:
                await conn.execute(text(f"""
                    ALTER TABLE {schema}.credential_store 
                    DROP CONSTRAINT IF EXISTS {constraint};
                """))
            except Exception:
                pass  # Constraint might not exist on this deployment
        
        # Add new unique constraint with user_id
        await conn.execute(text(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint 
                    WHERE conname = 'uq_credential_provider_name_type_user'
                    AND conrelid = '{schema}.credential_store'::regclass
                ) THEN
                    ALTER TABLE {schema}.credential_store 
                    ADD CONSTRAINT uq_credential_provider_name_type_user 
                    UNIQUE (provider, name, credential_type, user_id);
                END IF;
            END $$;
        """))
        
        null_check = await conn.execute(text(f"""
            SELECT 1 FROM {schema}.credential_store 
            WHERE user_id IS NULL 
            LIMIT 1;
        """))
        has_nulls = null_check.scalar_one_or_none()
        if has_nulls:
            print("Note: credential_store still has rows without user_id; column left nullable for now.")
        else:
            await conn.execute(text(f"""
                ALTER TABLE {schema}.credential_store 
                ALTER COLUMN user_id SET NOT NULL;
            """))
    except Exception as e:
        # Column might already exist or constraint might fail
        print(f"Note: credential_store user_id migration: {e}")


async def _migrate_gpu_metrics_table(conn, schema: str) -> None:
    """Add new columns to gpu_metrics table if they don't exist."""
    
    # List of new columns to add
    new_columns = [
        ("hbm_utilization", "REAL"),
        ("sm_occupancy", "REAL"),
        ("tensor_active", "REAL"),
        ("fp64_active", "REAL"),
        ("fp32_active", "REAL"),
        ("fp16_active", "REAL"),
        ("gr_engine_active", "REAL"),
        ("encoder_utilization", "REAL"),
        ("decoder_utilization", "REAL"),
        ("memory_temperature_celsius", "REAL"),
        ("slowdown_temperature_celsius", "REAL"),
        ("pcie_replay_errors", "INTEGER DEFAULT 0"),
        ("nvlink_bandwidth_total", "REAL"),
        ("nvlink_replay_errors", "INTEGER DEFAULT 0"),
        ("nvlink_recovery_errors", "INTEGER DEFAULT 0"),
        ("nvlink_crc_errors", "INTEGER DEFAULT 0"),
        ("ecc_sbe_errors", "INTEGER DEFAULT 0"),
        ("ecc_dbe_errors", "INTEGER DEFAULT 0"),
        ("ecc_sbe_aggregate", "INTEGER DEFAULT 0"),
        ("ecc_dbe_aggregate", "INTEGER DEFAULT 0"),
        ("throttle_reasons", "INTEGER DEFAULT 0"),
        ("throttle_thermal", "INTEGER DEFAULT 0"),
        ("throttle_power", "INTEGER DEFAULT 0"),
        ("throttle_sw_power", "INTEGER DEFAULT 0"),
        ("xid_errors", "INTEGER DEFAULT 0"),
        ("compute_mode", "INTEGER"),
        ("persistence_mode", "INTEGER"),
        ("ecc_mode", "INTEGER"),
        ("power_min_limit", "REAL"),
        ("power_max_limit", "REAL"),
        ("slowdown_temp", "REAL"),
        ("shutdown_temp", "REAL"),
        ("total_energy_joules", "REAL"),
        ("retired_pages_sbe", "INTEGER DEFAULT 0"),
        ("retired_pages_dbe", "INTEGER DEFAULT 0"),
        ("retired_pages_pending", "INTEGER DEFAULT 0"),
        ("fan_speed_percent", "REAL"),
        ("pstate", "INTEGER"),
        ("tokens_per_second", "REAL"),  # Application-level token throughput
        ("requests_per_second", "REAL"),  # Application-level request throughput
        ("ttft_p50_ms", "REAL"),  # Time to first token P50 (milliseconds)
        ("ttft_p95_ms", "REAL"),  # Time to first token P95 (milliseconds)
        ("cost_per_watt", "REAL"),  # Performance per watt (tokens/sec/watt)
        # vLLM live inference metrics (from Prometheus scrape of vLLM /metrics)
        ("prompt_tokens_per_second", "REAL"),
        ("vllm_requests_running", "REAL"),
        ("vllm_requests_waiting", "REAL"),
        ("vllm_gpu_cache_usage", "REAL"),
        ("vllm_cpu_cache_usage", "REAL"),
    ]
    
    for column_name, column_type in new_columns:
        try:
            await conn.execute(text(
                f"ALTER TABLE {schema}.gpu_metrics ADD COLUMN IF NOT EXISTS {column_name} {column_type};"
            ))
        except Exception:
            # Column might already exist, continue
            pass


async def _migrate_sm_profiling_tables(conn, schema: str) -> None:
    """Create SM profiling tables if they don't exist."""
    
    # Create SM profiling sessions table
    await conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {schema}.sm_profiling_sessions (
            session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id UUID NOT NULL REFERENCES {schema}.runs(run_id) ON DELETE CASCADE,
            instance_id VARCHAR(255) NOT NULL,
            gpu_id INTEGER NOT NULL,
            metric_names JSONB,
            status VARCHAR(20) NOT NULL,
            ncu_command TEXT,
            error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ
        );
    """))
    
    # Create indexes for sm_profiling_sessions
    await conn.execute(text(
        f"CREATE INDEX IF NOT EXISTS idx_sm_profiling_run_id ON {schema}.sm_profiling_sessions(run_id);"
    ))
    await conn.execute(text(
        f"CREATE INDEX IF NOT EXISTS idx_sm_profiling_status ON {schema}.sm_profiling_sessions(status);"
    ))
    
    # Create SM metrics table
    await conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {schema}.sm_metrics (
            id SERIAL PRIMARY KEY,
            session_id UUID NOT NULL REFERENCES {schema}.sm_profiling_sessions(session_id) ON DELETE CASCADE,
            sm_id INTEGER NOT NULL,
            metric_name VARCHAR(100) NOT NULL,
            value REAL NOT NULL,
            timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """))
    
    # Create indexes for sm_metrics
    await conn.execute(text(
        f"CREATE INDEX IF NOT EXISTS idx_sm_metrics_session ON {schema}.sm_metrics(session_id);"
    ))
    await conn.execute(text(
        f"CREATE INDEX IF NOT EXISTS idx_sm_metrics_sm_id ON {schema}.sm_metrics(sm_id);"
    ))


async def _migrate_instance_orchestration_tables(conn, schema: str) -> None:
    """Create instance orchestration tables if they don't exist."""
    
    # Create instance_orchestrations table
    await conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {schema}.instance_orchestrations (
            orchestration_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            instance_id VARCHAR(255) NOT NULL,
            status VARCHAR(20) NOT NULL,
            current_phase VARCHAR(50) NOT NULL,
            progress INTEGER NOT NULL DEFAULT 0,
            ip_address VARCHAR(50),
            ssh_user VARCHAR(50) NOT NULL DEFAULT 'ubuntu',
            ssh_key_name VARCHAR(100) NOT NULL,
            model_deployed VARCHAR(100),
            vllm_config JSONB,
            error_message TEXT,
            logs TEXT,
            config JSONB,
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMPTZ,
            last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """))
    
    # Add ssh_key_name column if it doesn't exist (migration for existing tables)
    # First add as nullable
    await conn.execute(text(f"""
        ALTER TABLE {schema}.instance_orchestrations 
        ADD COLUMN IF NOT EXISTS ssh_key_name VARCHAR(100);
    """))
    
    # Update existing rows to have a default ssh_key_name if null
    await conn.execute(text(f"""
        UPDATE {schema}.instance_orchestrations 
        SET ssh_key_name = COALESCE((config->>'ssh_key_name'), 'unknown')
        WHERE ssh_key_name IS NULL;
    """))
    
    # Make ssh_key_name NOT NULL after setting defaults (only if column was just added)
    # We'll use a DO block to check if we need to alter
    try:
        await conn.execute(text(f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_schema = '{schema}' 
                    AND table_name = 'instance_orchestrations' 
                    AND column_name = 'ssh_key_name'
                    AND is_nullable = 'YES'
                ) THEN
                    ALTER TABLE {schema}.instance_orchestrations 
                    ALTER COLUMN ssh_key_name SET NOT NULL;
                END IF;
            END $$;
        """))
    except Exception:
        # If the DO block fails, try direct ALTER (might fail if already NOT NULL)
        try:
            await conn.execute(text(f"""
                ALTER TABLE {schema}.instance_orchestrations 
                ALTER COLUMN ssh_key_name SET NOT NULL;
            """))
        except Exception:
            # Column might already be NOT NULL, ignore
            pass
    
    # Create indexes for instance_orchestrations
    await conn.execute(text(
        f"CREATE INDEX IF NOT EXISTS idx_orchestration_instance ON {schema}.instance_orchestrations(instance_id);"
    ))
    await conn.execute(text(
        f"CREATE INDEX IF NOT EXISTS idx_orchestration_status ON {schema}.instance_orchestrations(status);"
    ))
    await conn.execute(text(
        f"CREATE INDEX IF NOT EXISTS idx_orchestration_instance_status ON {schema}.instance_orchestrations(instance_id, status);"
    ))


async def _migrate_deployment_queue_tables(conn, schema: str) -> None:
    """Create deployment queue and provisioning tables if they don't exist."""
    
    # Create deployment_jobs table
    await conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {schema}.deployment_jobs (
            job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            instance_id VARCHAR(255) NOT NULL,
            run_id UUID NOT NULL REFERENCES {schema}.runs(run_id) ON DELETE CASCADE,
            deployment_type VARCHAR(20) NOT NULL DEFAULT 'ssh',
            status VARCHAR(20) NOT NULL,
            priority INTEGER NOT NULL DEFAULT 0,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            payload JSONB NOT NULL,
            error_message TEXT,
            error_log TEXT,
            locked_by VARCHAR(255),
            locked_at TIMESTAMPTZ,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """))
    
    # Create indexes for deployment_jobs
    await conn.execute(text(
        f"CREATE INDEX IF NOT EXISTS idx_deployment_jobs_instance ON {schema}.deployment_jobs(instance_id);"
    ))
    await conn.execute(text(
        f"CREATE INDEX IF NOT EXISTS idx_deployment_jobs_status ON {schema}.deployment_jobs(status);"
    ))
    await conn.execute(text(
        f"CREATE INDEX IF NOT EXISTS idx_deployment_jobs_created ON {schema}.deployment_jobs(created_at DESC);"
    ))
    await conn.execute(text(
        f"CREATE INDEX IF NOT EXISTS idx_deployment_jobs_instance_status ON {schema}.deployment_jobs(instance_id, status);"
    ))
    await conn.execute(text(
        f"CREATE INDEX IF NOT EXISTS idx_deployment_jobs_run_status ON {schema}.deployment_jobs(run_id, status);"
    ))
    
    # Create provisioning_manifests table
    await conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {schema}.provisioning_manifests (
            manifest_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            deployment_job_id UUID NOT NULL REFERENCES {schema}.deployment_jobs(job_id) ON DELETE CASCADE,
            instance_id VARCHAR(255) NOT NULL,
            token_hash VARCHAR(255) NOT NULL,
            manifest_data JSONB NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """))
    
    # Create indexes for provisioning_manifests
    await conn.execute(text(
        f"CREATE INDEX IF NOT EXISTS idx_provisioning_manifests_deployment ON {schema}.provisioning_manifests(deployment_job_id);"
    ))
    await conn.execute(text(
        f"CREATE INDEX IF NOT EXISTS idx_provisioning_manifests_token ON {schema}.provisioning_manifests(token_hash);"
    ))
    await conn.execute(text(
        f"CREATE INDEX IF NOT EXISTS idx_provisioning_manifests_expires ON {schema}.provisioning_manifests(expires_at);"
    ))
    
    # Create agent_heartbeats table
    await conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {schema}.agent_heartbeats (
            heartbeat_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            manifest_id UUID REFERENCES {schema}.provisioning_manifests(manifest_id) ON DELETE CASCADE,
            instance_id VARCHAR(255) NOT NULL,
            agent_version VARCHAR(50) NOT NULL,
            phase VARCHAR(50) NOT NULL,
            status VARCHAR(20) NOT NULL,
            message TEXT,
            metadata JSONB,
            timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """))
    
    # Make manifest_id nullable if it's not already (migration for existing tables)
    # Check if column exists and is NOT NULL, then alter it
    try:
        result = await conn.execute(text(f"""
            SELECT is_nullable 
            FROM information_schema.columns 
            WHERE table_schema = '{schema}' 
            AND table_name = 'agent_heartbeats' 
            AND column_name = 'manifest_id';
        """))
        row = result.fetchone()
        if row and row[0] == 'NO':
            await conn.execute(text(f"""
                ALTER TABLE {schema}.agent_heartbeats 
                ALTER COLUMN manifest_id DROP NOT NULL;
            """))
    except Exception:
        # Column might not exist yet or already nullable, continue
        pass
    
    # Create indexes for agent_heartbeats
    await conn.execute(text(
        f"CREATE INDEX IF NOT EXISTS idx_agent_heartbeats_instance ON {schema}.agent_heartbeats(instance_id);"
    ))
    await conn.execute(text(
        f"CREATE INDEX IF NOT EXISTS idx_agent_heartbeats_manifest ON {schema}.agent_heartbeats(manifest_id);"
    ))
    await conn.execute(text(
        f"CREATE INDEX IF NOT EXISTS idx_agent_heartbeats_timestamp ON {schema}.agent_heartbeats(timestamp DESC);"
    ))
    
    # Create provisioning_api_keys table
    await conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {schema}.provisioning_api_keys (
            key_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            key_hash VARCHAR(255) NOT NULL UNIQUE,
            name VARCHAR(100) NOT NULL,
            description TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            revoked_at TIMESTAMPTZ,
            last_used_at TIMESTAMPTZ
        );
    """))
    
    # Create indexes for provisioning_api_keys
    await conn.execute(text(
        f"CREATE INDEX IF NOT EXISTS idx_provisioning_api_keys_key_hash ON {schema}.provisioning_api_keys(key_hash);"
    ))
    await conn.execute(text(
        f"CREATE INDEX IF NOT EXISTS idx_provisioning_api_keys_revoked ON {schema}.provisioning_api_keys(revoked_at);"
    ))
    # Note: user_id index is created by migration since column is added later
    
    # Create users table for authentication
    await conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {schema}.users (
            user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email VARCHAR(255) NOT NULL UNIQUE,
            hashed_password VARCHAR(255) NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_login TIMESTAMPTZ
        );
    """))
    
    # Create unique constraint on email (already handled by UNIQUE in table, but adding explicit constraint)
    await conn.execute(text(
        f"CREATE UNIQUE INDEX IF NOT EXISTS uq_user_email ON {schema}.users(email);"
    ))


async def _migrate_profiling_tables(conn, schema: str) -> None:
    """Create workload_metrics, kernel_profiles, kernel_categories, bottleneck_analyses tables."""
    try:
        await conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {schema}.workload_metrics (
                run_id UUID PRIMARY KEY REFERENCES {schema}.runs(run_id) ON DELETE CASCADE,
                model_name VARCHAR(255),
                server_url VARCHAR(500),
                concurrency INTEGER,
                num_requests INTEGER,
                successful_requests INTEGER,
                failed_requests INTEGER,
                duration_s DOUBLE PRECISION,
                ttft_mean_ms DOUBLE PRECISION,
                ttft_p50_ms DOUBLE PRECISION,
                ttft_p95_ms DOUBLE PRECISION,
                ttft_p99_ms DOUBLE PRECISION,
                tpot_mean_ms DOUBLE PRECISION,
                tpot_p50_ms DOUBLE PRECISION,
                tpot_p95_ms DOUBLE PRECISION,
                tpot_p99_ms DOUBLE PRECISION,
                e2e_latency_mean_ms DOUBLE PRECISION,
                e2e_latency_p99_ms DOUBLE PRECISION,
                throughput_req_sec DOUBLE PRECISION,
                throughput_tok_sec DOUBLE PRECISION,
                total_input_tokens INTEGER,
                total_output_tokens INTEGER,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
        """))

        await conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {schema}.kernel_profiles (
                profile_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                run_id UUID NOT NULL REFERENCES {schema}.runs(run_id) ON DELETE CASCADE,
                total_cuda_ms DOUBLE PRECISION,
                total_flops DOUBLE PRECISION,
                estimated_tflops DOUBLE PRECISION,
                profiled_requests VARCHAR(50),
                trace_source VARCHAR(500),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
        """))
        await conn.execute(text(f"""
            CREATE INDEX IF NOT EXISTS idx_kernel_profiles_run_id
            ON {schema}.kernel_profiles(run_id);
        """))

        await conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {schema}.kernel_categories (
                id SERIAL PRIMARY KEY,
                profile_id UUID NOT NULL REFERENCES {schema}.kernel_profiles(profile_id) ON DELETE CASCADE,
                category VARCHAR(50) NOT NULL,
                total_ms DOUBLE PRECISION NOT NULL,
                pct DOUBLE PRECISION NOT NULL,
                kernel_count INTEGER NOT NULL
            );
        """))
        await conn.execute(text(f"""
            CREATE INDEX IF NOT EXISTS idx_kernel_categories_profile
            ON {schema}.kernel_categories(profile_id);
        """))

        await conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {schema}.bottleneck_analyses (
                run_id UUID PRIMARY KEY REFERENCES {schema}.runs(run_id) ON DELETE CASCADE,
                primary_bottleneck VARCHAR(20) NOT NULL,
                compute_util_pct DOUBLE PRECISION,
                sm_active_mean_pct DOUBLE PRECISION,
                memory_bw_util_pct DOUBLE PRECISION,
                hbm_bw_mean_gbps DOUBLE PRECISION,
                cpu_overhead_estimated_pct DOUBLE PRECISION,
                nvlink_util_pct DOUBLE PRECISION,
                arithmetic_intensity DOUBLE PRECISION,
                roofline_bound VARCHAR(20),
                mfu_pct DOUBLE PRECISION,
                actual_tflops DOUBLE PRECISION,
                peak_tflops_bf16 DOUBLE PRECISION,
                recommendations JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
        """))
        print("Profiling tables (workload_metrics, kernel_profiles, kernel_categories, bottleneck_analyses) created.")
    except Exception as e:
        print(f"Note: profiling tables migration: {e}")


async def _migrate_runs_run_type(conn, schema: str) -> None:
    """Add run_type column to runs table to distinguish monitoring/workload/kernel runs."""
    try:
        check_stmt = text(f"""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = '{schema}'
            AND table_name = 'runs'
            AND column_name = 'run_type'
        """)
        result = await conn.execute(check_stmt)
        exists = result.scalar_one_or_none()

        if not exists:
            await conn.execute(text(f"""
                ALTER TABLE {schema}.runs
                ADD COLUMN run_type VARCHAR(20) DEFAULT 'monitoring';
            """))
            print("Added run_type column to runs table")
    except Exception as e:
        print(f"Note: run_type migration: {e}")


async def _migrate_runs_gpu_summary(conn, schema: str) -> None:
    """Add gpu_summary JSONB column to runs table for agent profile uploads."""
    try:
        check_stmt = text(f"""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = '{schema}'
            AND table_name = 'runs'
            AND column_name = 'gpu_summary'
        """)
        result = await conn.execute(check_stmt)
        exists = result.scalar_one_or_none()

        if not exists:
            await conn.execute(text(f"""
                ALTER TABLE {schema}.runs
                ADD COLUMN gpu_summary JSONB;
            """))
            print("Added gpu_summary column to runs table")
    except Exception as e:
        print(f"Note: gpu_summary migration: {e}")
