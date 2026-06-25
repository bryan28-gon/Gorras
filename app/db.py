import os

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import sessionmaker


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./pos.db")
SYNC_DATABASE_URL = os.getenv("SYNC_DATABASE_URL", DATABASE_URL.replace("+aiosqlite", ""))

engine = create_async_engine(DATABASE_URL, future=True, echo=False)
SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
sync_engine = create_engine(
    SYNC_DATABASE_URL,
    future=True,
    echo=False,
    connect_args={"check_same_thread": False},
)
SessionLocalSync = sessionmaker(bind=sync_engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with SessionLocal() as session:
        yield session
