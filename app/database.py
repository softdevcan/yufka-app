import aiosqlite
import os
from pathlib import Path
from contextlib import asynccontextmanager

DATABASE_PATH = Path(__file__).parent.parent / "data" / "yufka.db"


async def get_db():
    """Get database connection."""
    db = await aiosqlite.connect(DATABASE_PATH)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()


@asynccontextmanager
async def get_db_connection():
    """Context manager for database connection."""
    db = await aiosqlite.connect(DATABASE_PATH)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()


async def init_db():
    """Initialize database tables."""
    os.makedirs(DATABASE_PATH.parent, exist_ok=True)

    async with aiosqlite.connect(DATABASE_PATH) as db:
        # Malzemeler tablosu
        await db.execute("""
            CREATE TABLE IF NOT EXISTS materials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                unit TEXT NOT NULL,
                price REAL NOT NULL DEFAULT 0,
                stock_quantity REAL NOT NULL DEFAULT 0,
                min_stock_level REAL NOT NULL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Stok hareketleri tablosu
        await db.execute("""
            CREATE TABLE IF NOT EXISTS stock_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                material_id INTEGER NOT NULL,
                movement_type TEXT NOT NULL,
                quantity REAL NOT NULL,
                reference_type TEXT,
                reference_id INTEGER,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (material_id) REFERENCES materials(id)
            )
        """)

        # Üretim tablosu
        await db.execute("""
            CREATE TABLE IF NOT EXISTS production (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE NOT NULL,
                product_type TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                materials_used TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Satış tablosu
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE NOT NULL,
                product_type TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price REAL NOT NULL,
                total_price REAL NOT NULL,
                customer_name TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Mevcut tabloya yeni kolonları ekle (migration)
        try:
            await db.execute("ALTER TABLE materials ADD COLUMN stock_quantity REAL NOT NULL DEFAULT 0")
        except:
            pass  # Kolon zaten var

        try:
            await db.execute("ALTER TABLE materials ADD COLUMN min_stock_level REAL NOT NULL DEFAULT 0")
        except:
            pass  # Kolon zaten var

        # Varsayılan malzemeleri ekle
        default_materials = [
            ("Un", "kg", 0),
            ("Su", "lt", 0),
            ("Tuz", "kg", 0),
            ("Yağ", "lt", 0),
        ]

        for name, unit, price in default_materials:
            await db.execute("""
                INSERT OR IGNORE INTO materials (name, unit, price, stock_quantity, min_stock_level)
                VALUES (?, ?, ?, 0, 0)
            """, (name, unit, price))

        await db.commit()


# Stok hareket tipleri
MOVEMENT_TYPES = {
    "in": "Giriş",
    "out": "Çıkış",
    "production": "Üretim",
    "adjustment": "Düzeltme",
}


# Ürün tipleri
PRODUCT_TYPES = {
    "yufka": "Yufka",
    "manti": "Mantı",
    "kadayif": "Kadayıf",
    "sigara_boregi": "Sigara Böreği",
}
