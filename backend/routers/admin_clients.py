"""Admin router — client CRUD and bulk create."""

import csv
import io
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.middleware.auth_middleware import get_admin_user, hash_password
from backend.models.client import Client
from backend.schemas.admin import (
    BulkCreateResponse,
    ClientListResponse,
    CreateClientRequest,
    UpdateClientRequest,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/clients", response_model=list[ClientListResponse])
async def list_clients(
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> list[ClientListResponse]:
    """List all clients with portfolio counts."""
    stmt = select(Client).options(selectinload(Client.portfolios)).order_by(Client.name)
    clients = list((await db.execute(stmt)).scalars().all())

    return [
        ClientListResponse(
            id=c.id, client_code=c.client_code, name=c.name,
            email=c.email, phone=c.phone, username=c.username,
            is_active=c.is_active, is_admin=c.is_admin,
            portfolio_count=len(c.portfolios), last_login=c.last_login,
        )
        for c in clients
    ]


@router.post("/clients", response_model=ClientListResponse, status_code=201)
async def create_client(
    body: CreateClientRequest,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ClientListResponse:
    """Create a single client with credentials."""
    existing = await db.execute(
        select(Client).where(
            (Client.username == body.username) | (Client.client_code == body.client_code)
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Client with this username or client_code already exists",
        )

    client = Client(
        client_code=body.client_code, name=body.name,
        email=body.email, phone=body.phone,
        username=body.username,
        password_hash=hash_password(body.password),
        is_admin=body.is_admin,
    )
    db.add(client)
    await db.flush()
    await db.refresh(client, ["portfolios"])

    return ClientListResponse(
        id=client.id, client_code=client.client_code, name=client.name,
        email=client.email, phone=client.phone, username=client.username,
        is_active=client.is_active, is_admin=client.is_admin,
        portfolio_count=0, last_login=client.last_login,
    )


@router.post("/clients/bulk-create", response_model=BulkCreateResponse)
async def bulk_create_clients(
    file: UploadFile,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> BulkCreateResponse:
    """Bulk create clients from CSV (client_code,name,email,phone,username,password)."""
    content = await file.read()
    text = content.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))

    required = {"client_code", "name", "username", "password"}
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        raise HTTPException(
            status_code=400,
            detail=f"CSV must have columns: {required}. Found: {reader.fieldnames}",
        )

    created = 0
    skipped = 0
    errors: list[dict[str, Any]] = []

    for row_num, row in enumerate(reader, start=2):
        username = row.get("username", "").strip().lower()
        client_code = row.get("client_code", "").strip()
        password = row.get("password", "").strip()

        if not username or not client_code or not password:
            errors.append({"row": row_num, "error": "Missing required field"})
            skipped += 1
            continue

        if len(password) < 8:
            errors.append({"row": row_num, "error": "Password must be >= 8 chars"})
            skipped += 1
            continue

        existing = await db.execute(
            select(Client.id).where(
                (Client.username == username) | (Client.client_code == client_code)
            )
        )
        if existing.scalar_one_or_none() is not None:
            skipped += 1
            continue

        client = Client(
            client_code=client_code,
            name=row.get("name", "").strip(),
            email=row.get("email", "").strip() or None,
            phone=row.get("phone", "").strip() or None,
            username=username,
            password_hash=hash_password(password),
        )
        db.add(client)
        created += 1

    await db.flush()
    return BulkCreateResponse(created=created, skipped=skipped, errors=errors)


@router.put("/clients/{client_id}", response_model=ClientListResponse)
async def update_client(
    client_id: int,
    body: UpdateClientRequest,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ClientListResponse:
    """Update client info or reset password."""
    stmt = select(Client).options(selectinload(Client.portfolios)).where(Client.id == client_id)
    client = (await db.execute(stmt)).scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    if body.name is not None:
        client.name = body.name
    if body.email is not None:
        client.email = body.email
    if body.phone is not None:
        client.phone = body.phone
    if body.is_active is not None:
        client.is_active = body.is_active
    if body.new_password is not None:
        client.password_hash = hash_password(body.new_password)

    await db.flush()

    return ClientListResponse(
        id=client.id, client_code=client.client_code, name=client.name,
        email=client.email, phone=client.phone, username=client.username,
        is_active=client.is_active, is_admin=client.is_admin,
        portfolio_count=len(client.portfolios), last_login=client.last_login,
    )
