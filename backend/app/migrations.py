"""One-time SQLite upgrade for explicitly undated source records."""
import re
import sqlite3
from uuid import uuid4


def allow_undated(engine, path):
    with engine.raw_connection() as connection:
        db = connection.driver_connection
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        targets = {'conversations': {'date_order', 'started_at', 'ended_at'}, 'messages': {'timestamp', 'raw_timestamp'}}
        changes = {table: {row[1] for row in db.execute(f'PRAGMA table_info("{table}")') if row[1] in columns and row[3]}
                   for table, columns in targets.items() if table in tables}
        needs_format = 'conversations' in tables and 'transcript_format' not in {row[1] for row in db.execute('PRAGMA table_info(conversations)')}
        if not any(changes.values()) and not needs_format:
            return
        # SQLite's online backup captures a consistent pre-migration database.
        backup = path.with_name(f'{path.stem}.pre-undated-{uuid4().hex[:8]}.db')
        with sqlite3.connect(backup) as target:
            db.backup(target)
        db.execute('PRAGMA foreign_keys=OFF')
        try:
            db.execute('BEGIN IMMEDIATE')
            for table, columns in changes.items():
                if not columns:
                    continue
                sql = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0]
                indexes = [row[0] for row in db.execute("SELECT sql FROM sqlite_master WHERE type IN ('index','trigger') AND tbl_name=? AND sql IS NOT NULL", (table,))]
                temporary = f'__echo_undated_{table}'
                sql = re.sub(r'^CREATE TABLE\s+"?' + table + r'"?', f'CREATE TABLE "{temporary}"', sql, count=1, flags=re.I)
                for column in columns:
                    sql, count = re.subn(r'(?m)^(\s*"?' + column + r'"?\s+\w+(?:\(\d+\))?)\s+NOT NULL', r'\1', sql, flags=re.I)
                    if count != 1:
                        raise RuntimeError(f'Cannot safely migrate {table}.{column}; pre-upgrade backup retained.')
                db.execute(sql)
                db.execute(f'INSERT INTO "{temporary}" SELECT * FROM "{table}"')
                db.execute(f'DROP TABLE "{table}"')
                db.execute(f'ALTER TABLE "{temporary}" RENAME TO "{table}"')
                for index in indexes:
                    db.execute(index)
            if needs_format:
                db.execute("ALTER TABLE conversations ADD COLUMN transcript_format VARCHAR NOT NULL DEFAULT 'whatsapp'")
            if db.execute('PRAGMA foreign_key_check').fetchone():
                raise RuntimeError('Foreign key check failed; upgrade rolled back.')
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.execute('PRAGMA foreign_keys=ON')
