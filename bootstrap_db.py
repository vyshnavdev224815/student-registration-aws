"""Create the assignment's students table from within the private VPC."""

import time

import pymysql

from app import get_db_connection


SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(150) NOT NULL,
    course VARCHAR(100),
    photo_url VARCHAR(500)
)
"""


def main() -> int:
    for attempt in range(30):
        try:
            with get_db_connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(SCHEMA)
                connection.commit()
            return 0
        except (pymysql.MySQLError, OSError):
            if attempt == 29:
                raise
            time.sleep(10)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
