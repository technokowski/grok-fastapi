from collections.abc import Generator

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import BOOTSTRAP_PASSWORD, BOOTSTRAP_USERNAME, DATA_DIR, DB_PATH
from app.files import ensure_uploads_dir
from app.models import Base, User
from app.security import hash_password

DATA_DIR.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    ensure_uploads_dir()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        count = db.scalar(select(func.count()).select_from(User)) or 0
        if count == 0:
            db.add(
                User(
                    username=BOOTSTRAP_USERNAME,
                    password_hash=hash_password(BOOTSTRAP_PASSWORD),
                    is_admin=True,
                    is_active=True,
                    must_change_password=True,
                )
            )
            db.commit()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
