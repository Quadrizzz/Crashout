from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,               # Automatically tests and recovers dead/stale connections
    pool_recycle=300,                 # Recycle connections every 5 minutes to prevent idle drops
    pool_size=10,
    max_overflow=20,
    connect_args={
        "statement_cache_size": 0,    # Required for Supabase PgBouncer pooler
        "prepared_statement_cache_size": 0,
    }
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

class Base(DeclarativeBase):
    pass