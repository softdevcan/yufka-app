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

        # Ürün stokları tablosu (üretilen ve hazır alınan ürünler için)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS product_stock (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_type TEXT NOT NULL UNIQUE,
                stock_quantity INTEGER NOT NULL DEFAULT 0,
                min_stock_level INTEGER NOT NULL DEFAULT 0,
                price REAL NOT NULL DEFAULT 0,
                unit TEXT NOT NULL DEFAULT 'adet',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Ürün stok hareketleri tablosu
        await db.execute("""
            CREATE TABLE IF NOT EXISTS product_stock_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_type TEXT NOT NULL,
                movement_type TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                reference_type TEXT,
                reference_id INTEGER,
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

        # Ürün fiyatı kolonu ekle (migration)
        try:
            await db.execute("ALTER TABLE product_stock ADD COLUMN price REAL NOT NULL DEFAULT 0")
        except:
            pass  # Kolon zaten var

        # Ürün birimi kolonu ekle (migration)
        try:
            await db.execute("ALTER TABLE product_stock ADD COLUMN unit TEXT NOT NULL DEFAULT 'adet'")
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

        # Varsayılan ürün stokları, fiyatları ve birimlerini ekle
        default_products = [
            ("yufka", 50, "adet"),
            ("sigara_boregi", 75, "adet"),
            ("manti", 100, "kg"),
            ("kadayif", 80, "kg"),
        ]
        for product_type, price, unit in default_products:
            await db.execute("""
                INSERT OR IGNORE INTO product_stock (product_type, stock_quantity, min_stock_level, price, unit)
                VALUES (?, 0, 0, ?, ?)
            """, (product_type, price, unit))
            
            # Mevcut ürünlerin fiyatlarını ve birimlerini güncelle (eğer varsayılan değerlerde ise)
            await db.execute("""
                UPDATE product_stock 
                SET price = ?, unit = ?
                WHERE product_type = ? AND (price = 0 OR unit = 'adet')
            """, (price, unit, product_type))

        # Siparişler tablosu
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_date DATE NOT NULL,
                delivery_date DATE NOT NULL,
                delivery_type TEXT NOT NULL,
                customer_name TEXT NOT NULL,
                customer_phone TEXT NOT NULL,
                address TEXT,
                items TEXT NOT NULL,
                total_amount REAL NOT NULL,
                payment_method TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.commit()


# Stok hareket tipleri
MOVEMENT_TYPES = {
    "in": "Giriş",
    "out": "Çıkış",
    "production": "Üretim",
    "sale": "Satış",
    "adjustment": "Düzeltme",
}


# Üretilen ürünler (hammaddeden üretim yapılan)
PRODUCED_PRODUCTS = {
    "yufka": "Yufka",
    "sigara_boregi": "Sigara Böreği",
}

# Hazır alınıp satılan ürünler
PURCHASED_PRODUCTS = {
    "manti": "Mantı",
    "kadayif": "Kadayıf",
}

# Tüm ürün tipleri
PRODUCT_TYPES = {**PRODUCED_PRODUCTS, **PURCHASED_PRODUCTS}

# Sipariş teslim tipleri
DELIVERY_TYPES = {
    "gel_al": "Gel Al",
    "eve_gelsin": "Eve Gelsin",
}

# Ödeme yöntemleri
PAYMENT_METHODS = {
    "nakit": "Nakit",
    "kart": "Kart",
}

# Sipariş durumları
ORDER_STATUS = {
    "active": "Aktif",
    "delivered": "Teslim Edildi",
    "cancelled": "İptal Edildi",
}

# Minimum eve sipariş tutarı (TL)
MIN_DELIVERY_AMOUNT = 500
