"""Ingest TARGET_SCHEDULE_M51.5.xer into project TEP3-177 and materialize version."""

import asyncio
import hashlib
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.adapters.p6_xer import parse_xer_bytes
from app.adapters.storage import get_storage_adapter
from app.core.config import get_settings
from app.db.session import get_db_session
from app.domains.ingestion.normalization import normalize_schedule_bundle
from app.domains.projects.version_service import create_version_from_confirmed_job
from app.models.auth import User, Workspace
from app.models.project import ImportJob, Project, ProjectVersion, UploadedFile


async def main() -> None:
    file_path = Path(
        r"C:/Users/USER/.gemini/antigravity/brain/3d165acc-6793-4244-bfd4-be6efa373cbd/.user_uploaded/media_1794186478482_f84478be.xer"
    )
    if not file_path.exists():
        raise FileNotFoundError(f"Source file not found at {file_path}")

    print(f"Reading {file_path} ({file_path.stat().st_size:,} bytes)...")
    with open(file_path, "rb") as f:
        file_bytes = f.read()

    file_hash = hashlib.sha256(file_bytes).hexdigest()
    settings = get_settings()
    storage = get_storage_adapter(settings)

    async with get_db_session() as session:
        # 1. Resolve workspace and user
        user = (await session.execute(select(User).limit(1))).scalar_one()
        ws = (
            await session.execute(
                select(Workspace).where(Workspace.owner_user_id == user.id)
            )
        ).scalar_one()

        # Ensure enterprise plan
        ws.plan_code = "enterprise"
        await session.commit()

        print(f"Using Workspace: {ws.id} ({ws.name}), User: {user.id} ({user.email})")

        # 2. Find or create Project TEP3-177
        project = (
            await session.execute(
                select(Project).where(
                    Project.workspace_id == ws.id,
                    Project.project_code == "TEP3-177",
                )
            )
        ).scalar_one_or_none()

        if not project:
            project = Project(
                id=uuid.uuid4(),
                workspace_id=ws.id,
                name="TEP3-177 Offshore Gas Processing Facility",
                project_code="TEP3-177",
                description="Target Schedule M51.5 for Offshore GPF Revamp and Subsea Tie-In Package",
                industry="Oil & Gas EPC",
                client_name="Total E&P",
                contractor_name="Engineering & Construction Consortium",
                currency_code="USD",
                timezone="Asia/Jakarta",
                status="active",
            )
            session.add(project)
            await session.flush()
            print(f"Created Project: {project.id} ({project.project_code})")
        else:
            print(f"Found existing Project: {project.id} ({project.project_code})")

        # 3. Store file into object storage
        object_key = f"{ws.id}/{project.id}/uploads/{uuid.uuid4()}/TARGET_SCHEDULE_M51.5.xer"
        await storage.put_object(object_key, file_bytes, "application/octet-stream")
        print(f"Stored file in object storage key: {object_key}")

        # 4. Create UploadedFile record
        uploaded_file = UploadedFile(
            id=uuid.uuid4(),
            workspace_id=ws.id,
            project_id=project.id,
            uploaded_by=user.id,
            original_filename="TARGET_SCHEDULE_M51.5.xer",
            object_key=object_key,
            content_type="application/octet-stream",
            file_size_bytes=len(file_bytes),
            sha256_checksum=file_hash,
            source_format="xer",
            storage_status="private",
        )
        session.add(uploaded_file)
        await session.flush()
        print(f"Created UploadedFile: {uploaded_file.id}")

        # 5. Parse XER
        t0 = time.time()
        print("Parsing XER payload...")
        bundle = parse_xer_bytes(file_bytes)
        t_parse = time.time() - t0
        print(
            f"Parsed XER in {t_parse:.2f}s: {len(bundle.activities)} activities, "
            f"{len(bundle.relationships)} relationships, {len(bundle.wbs_nodes)} WBS nodes, "
            f"{len(bundle.calendars)} calendars."
        )

        # 6. Normalize schedule bundle
        t1 = time.time()
        print("Normalizing schedule bundle to canonical representation...")
        schedule = normalize_schedule_bundle(bundle)
        t_norm = time.time() - t1
        print(f"Normalized schedule in {t_norm:.2f}s.")

        # 7. Create ImportJob
        import_job = ImportJob(
            id=uuid.uuid4(),
            workspace_id=ws.id,
            project_id=project.id,
            uploaded_file_id=uploaded_file.id,
            status="preview_ready",
            parser_name="p6_xer_parser",
            parser_version="0.2.0",
            progress_pct=100.0,
            detected_metadata={
                "project_name": bundle.project_name or "TEP3-177",
                "source_project_key": bundle.source_project_key,
                "data_date": bundle.data_date.isoformat() if bundle.data_date else None,
                "activities_count": len(bundle.activities),
                "relationships_count": len(bundle.relationships),
                "wbs_nodes_count": len(bundle.wbs_nodes),
                "calendars_count": len(bundle.calendars),
            },
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        )
        session.add(import_job)
        await session.flush()
        print(f"Created ImportJob: {import_job.id} (status: preview_ready)")

        # 8. Materialize version
        t2 = time.time()
        print("Materializing ProjectVersion and all canonical schedule entities...")
        version = await create_version_from_confirmed_job(
            session=session,
            job=import_job,
            schedule=schedule,
            user_id=user.id,
        )
        await session.commit()
        t_mat = time.time() - t2
        print(f"Successfully materialized ProjectVersion {version.id} (V{version.version_number}) in {t_mat:.2f}s!")

        # Verify project state
        project = await session.get(Project, project.id)
        print(f"Project {project.name} latest_version_id is now: {project.latest_version_id}")
        print("All done!")


if __name__ == "__main__":
    asyncio.run(main())
