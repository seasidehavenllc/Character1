---
title: SQL
summary: The language for storing and querying data in relational databases (SQLite, PostgreSQL, MySQL, SQL Server).
tags: [language, data, database, backend]
---
# SQL

## Overview
SQL describes what data you want, and the database works out how to get it. Data lives in tables of rows and columns, linked by keys. Almost every app with users, orders or records uses a SQL database.

## Setup and running
- Easiest: SQLite — a single file, no server. Built into Python (`import sqlite3`), or use the `sqlite3` command-line tool or "DB Browser for SQLite".
- Servers: PostgreSQL (recommended) or MySQL, often via Docker.

## Core syntax
```sql
CREATE TABLE suits (
  id INTEGER PRIMARY KEY,
  mark INTEGER NOT NULL UNIQUE,
  color TEXT DEFAULT 'red',
  power INTEGER CHECK (power BETWEEN 0 AND 100)
);
INSERT INTO suits (mark, color, power) VALUES (42, 'red', 90), (43, 'gold', 55);
SELECT mark, power FROM suits WHERE power > 50 ORDER BY power DESC LIMIT 10;
UPDATE suits SET power = power - 10 WHERE mark = 42;
DELETE FROM suits WHERE power = 0;
```

## Joins and grouping
```sql
SELECT p.name, COUNT(s.id) AS suits, AVG(s.power) AS avg_power
FROM pilots p
LEFT JOIN suits s ON s.pilot_id = p.id     -- LEFT keeps pilots with no suits
GROUP BY p.id
HAVING COUNT(s.id) >= 1;                   -- HAVING filters groups, WHERE filters rows
```

## Common mistakes
- **SQL injection**: never build queries by pasting user input into strings. Use parameters: `db.execute("SELECT * FROM users WHERE name = ?", (name,))`.
- `UPDATE` or `DELETE` without `WHERE` changes every row. Run the `SELECT` first.
- Comparing with `= NULL`; use `IS NULL`.
- Forgetting indexes on columns you search or join on, making big tables slow.
- Storing lists in one text column instead of a separate table.

## Learning path
### Level 1 — Querying
`SELECT`, `WHERE`, `ORDER BY`, `LIMIT`, `AND/OR`, `LIKE`, `NULL`.
Exercise: answer five questions about a sample table of movies.

### Level 2 — Changing data and design
`CREATE TABLE`, types, constraints, primary and foreign keys, `INSERT/UPDATE/DELETE`, normalization.
Exercise: design tables for a school (students, classes, enrollments).

### Level 3 — Combining data
Joins, `GROUP BY`, aggregate functions, subqueries, views, indexes, transactions.
Exercise: report each class's average grade and its top student.

### Level 4 — In applications
Parameterized queries from Python/JS, migrations, an ORM (SQLAlchemy, Prisma), PostgreSQL features, query plans (`EXPLAIN`).
Exercise: add a SQLite database to a Python or Node app.

## Complete example
```sql run
CREATE TABLE pilots (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE suits (id INTEGER PRIMARY KEY, mark INTEGER, power INTEGER, pilot_id INTEGER REFERENCES pilots(id));
INSERT INTO pilots (id, name) VALUES (1, 'Tony'), (2, 'Rhodey'), (3, 'Pepper');
INSERT INTO suits (mark, power, pilot_id) VALUES (42, 90, 1), (43, 40, 1), (2, 75, 2);
SELECT p.name, COUNT(s.id) AS suits, COALESCE(MAX(s.power), 0) AS best
FROM pilots p LEFT JOIN suits s ON s.pilot_id = p.id
GROUP BY p.id ORDER BY suits DESC, p.name;
```
