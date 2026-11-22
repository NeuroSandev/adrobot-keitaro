import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app import models  # noqa: F401
from app.config import Settings, get_settings
from app.db import Base, get_db, make_engine
from app.keitaro.deps import get_keitaro
from app.keitaro.fake import FakeKeitaro
from app.main import app


@pytest.fixture
def fake():
    return FakeKeitaro()


@pytest.fixture
def client(fake, tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    settings = Settings(keitaro_fake=True, default_domain="in.posdk.xyz",
                        default_group_name="FORTESTS", default_source_name="FORTESTS",
                        safe_redirect_url="https://google.com", _env_file=None)
    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_keitaro] = lambda: fake
    app.dependency_overrides[get_settings] = lambda: settings
    yield TestClient(app)
    app.dependency_overrides.clear()
