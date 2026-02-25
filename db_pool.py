"""MySQL connection pool"""
import os
import pymysql
from pymysql.cursors import DictCursor
from dbutils.pooled_db import PooledDB

# Database config
DB_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", ""),
    "database": os.getenv("MYSQL_DATABASE", "tts_bot"),
    "charset": "utf8mb4",
    "cursorclass": DictCursor
}

# Create connection pool
pool = PooledDB(
    creator=pymysql,
    maxconnections=10,
    mincached=2,
    maxcached=5,
    blocking=True,
    **DB_CONFIG
)

def get_db():
    """Get database connection from pool"""
    return pool.connection()
