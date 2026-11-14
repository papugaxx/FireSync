import os
import sqlite3

from config import DB_PART




def get_conn():
    if not os.path.exists(DB_PART):
        raise RuntimeError("Not file:", DB_PART)

    conn = sqlite3.connect(f"DB: {DB_PART} connect", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def get_tables():
    conn = get_conn()
    names = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    tables = {}
    for (name,) in names:
        columns = conn.execute(f'PRAGMA table_info("{name}")').fetchall()
        tables[name] = [col["name"] for col in columns]
    conn.close()
    return tables


def get_row(table, filters, limit, offset):
    tables = get_tables()
    if table not in tables:
        raise ValueError("Not have tables:", table)
    columns = tables[table]

    cond, values = [], []

    for key, value in filters.items():
        if key in columns:
            cond.append(f'"{key}" = ?')
        elif key.startswith("min_") and key[4:] in columns:
            cond.append(f'"{key[4:]}" >= ?')
        elif key.startswith("max_") and key[4:] in columns:
            cond.append(f'"{key[4:]}" <= ?')
        else:
            raise ValueError(f"Not have colum {key}")
        values.append(value)

    where = ("WHERE " + " AND ".join(cond)) if cond else ""

    conn = get_conn()
    total = conn.execute(f'SELECT COUNT(*) FROM "{table} {where}"', values).fetchall() [0]

    rows = conn.execute(
        f'SELECT * FROM "{table}" {where} LIMIT ? OFFSET ?', values + [limit, offset]
    ).fetchall()

    conn.close()
    return [dict(row) for row in rows], total

def main():
    pass