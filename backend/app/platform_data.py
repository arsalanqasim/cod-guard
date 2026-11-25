"""The PostgreSQL transaction boundary for merchant data."""
import base64
import json
import os
from contextlib import contextmanager
from functools import lru_cache

import psycopg
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def database_url():
    return os.environ.get("COD_GUARD_DATABASE_URL", "")


@lru_cache(maxsize=4)
def _keys(configuration):
    document = json.loads(configuration)
    raw = document["keys"]
    if not isinstance(raw, dict):
        raise ValueError("Invalid data key configuration")
    keys = {}
    for key, value in raw.items():
        data = base64.b64decode(value, validate=True)
        if len(data) != 32 or not key.isascii() or not key.isalnum():
            raise ValueError("Invalid data key configuration")
        keys[key] = AESGCM(data)
    active = document["active"]
    if active not in keys:
        raise ValueError("Invalid data key configuration")
    return active, keys


class DataEncryptionError(RuntimeError):
    pass


def _context(tenant_id, object_id, field):
    return json.dumps([tenant_id, object_id, field], separators=(",", ":")).encode()


def seal(value, tenant_id, object_id, field):
    if value is None:
        return None
    try:
        active, keys = _keys(os.environ["COD_GUARD_DATA_KEYS"])
        nonce = os.urandom(12)
        sealed = keys[active].encrypt(nonce, value, _context(tenant_id, object_id, field))
        return active + "." + base64.b64encode(nonce + sealed).decode("ascii")
    except (KeyError, TypeError, ValueError) as exc:
        raise DataEncryptionError("Encryption configuration is unavailable") from exc


def unseal(value, tenant_id, object_id, field):
    if value is None:
        return None
    try:
        _, keys = _keys(os.environ["COD_GUARD_DATA_KEYS"])
        key, encoded = value.split(".", 1)
        data = base64.b64decode(encoded, validate=True)
        return keys[key].decrypt(data[:12], data[12:], _context(tenant_id, object_id, field))
    except (InvalidTag, KeyError, TypeError, ValueError) as exc:
        raise DataEncryptionError("Encrypted data is unavailable") from exc


def encrypt(value, tenant_id, object_id, field):
    return seal(value.encode() if value is not None else None, tenant_id, object_id, field)


def decrypt(value, tenant_id, object_id, field):
    return unseal(value, tenant_id, object_id, field).decode() if value is not None else None


class _Row(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


def _row_factory(cursor):
    names = [column.name for column in cursor.description] if cursor.description else ()
    return lambda values: _Row(zip(names, values))


class TenantConnection:
    encrypted = True

    def __init__(self, connection):
        self.connection = connection

    @staticmethod
    def _sql(query):
        # Shared statements use static qmark placeholders. Values stay bound.
        return query.replace("%", "%%").replace("?", "%s")

    def execute(self, query, parameters=()):
        return self.connection.execute(self._sql(query), parameters)

    def executemany(self, query, parameters):
        cursor = self.connection.cursor()
        cursor.executemany(self._sql(query), parameters)
        return cursor


@contextmanager
def connection():
    with psycopg.connect(database_url(), row_factory=_row_factory, connect_timeout=5) as db:
        _require_runtime(db)
        yield db


def _require_runtime(db):
    db.execute("SET LOCAL search_path TO pg_catalog, cod_guard")
    if not db.execute("SELECT row_security_active('cod_guard.orders'::regclass)").fetchone()[0]:
        raise psycopg.ProgrammingError("Merchant runtime role must be subject to row security")


@contextmanager
def tenant_connection(tenant_id, *, writable=False):
    if not tenant_id:
        raise ValueError("PostgreSQL transactions require a tenant")
    with psycopg.connect(database_url(), row_factory=_row_factory, connect_timeout=5) as db:
        if not writable:
            db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        _require_runtime(db)
        db.execute("SELECT set_config('cod_guard.tenant_id', %s, true)", (tenant_id,))
        if writable:
            # Preserve the pilot's serialized decision revisions within each tenant.
            db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (tenant_id,))
        yield TenantConnection(db)
