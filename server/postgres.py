"""Small PostgreSQL adapter for the classroom's shared SQL operations.

SQLite remains the local development backend. Vercel always requires DATABASE_URL.
"""
import os, re, sqlite3
from contextlib import contextmanager

def translate(sql):
    sql=sql.strip()
    if sql.upper().startswith('PRAGMA '):return None
    if sql=='BEGIN IMMEDIATE':return 'SELECT pg_advisory_xact_lock(72831120)'
    sql=re.sub(r'json_array_length\((\w+(?:\.\w+)?)\)',r'jsonb_array_length(\1::jsonb)',sql)
    ignore=bool(re.match(r'INSERT OR IGNORE ',sql,re.I))
    sql=re.sub(r'^INSERT OR IGNORE ', 'INSERT ',sql,flags=re.I)
    sql=sql.replace('?', '%s')
    if ignore:sql=sql.rstrip(';')+' ON CONFLICT DO NOTHING'
    return sql

class Connection:
    def __init__(self,connection):self.raw=connection
    def execute(self,sql,args=()):
        import psycopg
        sql=translate(sql)
        if sql is None:return self.raw.execute('SELECT 1 WHERE false')
        try:return self.raw.execute(sql,args)
        except psycopg.IntegrityError as e:raise sqlite3.IntegrityError('Database constraint violation') from e
    def executescript(self,sql):
        for statement in sql.split(';'):
            if statement.strip():self.execute(statement)

@contextmanager
def connect():
    import psycopg
    from psycopg.rows import dict_row
    # Set DATABASE_URL to the provider's pooled TLS URL. Do not log it.
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row,connect_timeout=8) as raw:
        try:yield Connection(raw)
        except BaseException:raw.rollback();raise
