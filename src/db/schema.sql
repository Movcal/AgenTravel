-- AgenTravel Database Schema

CREATE TABLE IF NOT EXISTS cities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    country TEXT,
    timezone TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS places (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    category TEXT,
    description TEXT,
    opening_hours TEXT,
    closed_days TEXT,
    price TEXT,
    currency TEXT,
    address TEXT,
    contact TEXT,
    official_website TEXT,
    source TEXT,
    last_verified TEXT,
    confidence_level TEXT CHECK(confidence_level IN ('high', 'medium', 'low')),
    is_free INTEGER,
    is_indoor INTEGER,
    target_audience TEXT,
    has_own_agenda INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (city_id) REFERENCES cities(id)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT UNIQUE,
    city_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    category TEXT,
    venue TEXT,
    start_date TEXT,
    end_date TEXT,
    time TEXT,
    price TEXT,
    ticket_source TEXT,
    official_source TEXT,
    status TEXT DEFAULT 'scheduled' CHECK(status IN ('scheduled', 'active', 'completed', 'archived', 'cancelled')),
    confidence_level TEXT CHECK(confidence_level IN ('high', 'medium', 'low')),
    is_free INTEGER,
    is_indoor INTEGER,
    target_audience TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (city_id) REFERENCES cities(id)
);

-- Tabla clave/valor para metadata operativa (ej: ultima corrida del Guardian).
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- Migraciones: agregar columnas si no existen (SQLite no soporta IF NOT EXISTS en ALTER)
-- Se ejecutan desde database.py con try/except

-- Index para queries rapidas por ciudad y fecha
CREATE INDEX IF NOT EXISTS idx_places_city ON places(city_id);
CREATE INDEX IF NOT EXISTS idx_events_city ON events(city_id);
CREATE INDEX IF NOT EXISTS idx_events_dates ON events(start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);
