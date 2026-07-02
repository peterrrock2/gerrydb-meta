"""Test configuration for GerryDB."""

import os
import pickle
from pathlib import Path

import geopandas as gpd
import networkx as nx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from gerrydb_meta import models

DEFAULT_TEST_DATABASE_URI = "postgresql://postgres:test@localhost:54321"


@pytest.fixture(scope="session")
def db_engine():
    """SpatialLite-enabled SQLAlchemy engine."""
    engine = create_engine(os.getenv("GERRYDB_TEST_DATABASE_URI", DEFAULT_TEST_DATABASE_URI))
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def db_schema(db_engine):
    """SQLAlchemy ORM session maker with GerryDB schema initialized."""
    with db_engine.connect() as conn:
        init_transaction = conn.begin()
        conn.execute(text("DROP SCHEMA IF EXISTS gerrydb CASCADE"))
        conn.execute(text("CREATE SCHEMA gerrydb"))
        init_transaction.commit()

        models.Base.metadata.create_all(db_engine)
        yield sessionmaker(db_engine)

        cleanup_transaction = conn.begin()
        conn.execute(text("DROP SCHEMA gerrydb CASCADE"))
        cleanup_transaction.commit()


@pytest.fixture
def db(db_schema):
    """SQLAlchemy ORM session (rolls back on cleanup)."""
    session = db_schema()
    yield session
    session.rollback()
    session.close()


@pytest.fixture(scope="session")
def me_2010_gdf():
    """`GeoDataFrame` of Maine 2010 Census blocks."""
    pkl_path = Path(__file__).resolve().parent / "fixtures" / "23_county_all_geos_2010.pkl"

    with open(pkl_path, "rb") as pkl_fp:
        gdf = pickle.load(pkl_fp)

    return gdf


@pytest.fixture(scope="session")
def me_2010_column_tabluation():
    pkl_path = Path(__file__).resolve().parent / "fixtures" / "tabular_config_geo_columns_2010.pkl"

    with open(pkl_path, "rb") as pkl_fp:
        gdf = pickle.load(pkl_fp)

    return gdf


@pytest.fixture
def me_2010_nx_graph():
    return nx.from_edgelist(
        [
            ("23029", "23009"),
            ("23029", "23019"),
            ("23029", "23003"),
            ("23005", "23031"),
            ("23005", "23023"),
            ("23005", "23001"),
            ("23005", "23017"),
            ("23017", "23031"),
            ("23017", "23001"),
            ("23017", "23007"),
            ("23003", "23025"),
            ("23003", "23019"),
            ("23003", "23021"),
            ("23025", "23011"),
            ("23025", "23007"),
            ("23025", "23027"),
            ("23025", "23019"),
            ("23025", "23021"),
            ("23009", "23013"),
            ("23009", "23027"),
            ("23009", "23019"),
            ("23023", "23001"),
            ("23023", "23011"),
            ("23023", "23015"),
            ("23019", "23027"),
            ("23019", "23021"),
            ("23015", "23011"),
            ("23015", "23013"),
            ("23015", "23027"),
            ("23013", "23027"),
            ("23001", "23011"),
            ("23001", "23007"),
            ("23011", "23007"),
            ("23011", "23027"),
        ]
    )


@pytest.fixture
def me_2010_plan_dict():
    return {
        "23009": 0,
        "23013": 0,
        "23021": 0,
        "23023": 0,
        "23019": 0,
        "23011": 0,
        "23007": 0,
        "23003": 0,
        "23029": 0,
        "23015": 0,
        "23025": 0,
        "23027": 0,
        "23031": 1,
        "23001": 1,
        "23017": 1,
        "23005": 1,
    }


@pytest.fixture
def ia_dataframe():
    """`GeoDataFrame` of Iowa counties."""
    shp_path = Path(__file__).resolve().parent / "fixtures" / "tl_2020_19_county20.zip"
    return gpd.read_file(shp_path).set_index("GEOID20")
