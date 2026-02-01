import os
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Form, Depends, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

load_dotenv()

from .database import (
    init_db, get_db_connection,
    PRODUCT_TYPES, PRODUCED_PRODUCTS, PURCHASED_PRODUCTS, MOVEMENT_TYPES,
    DELIVERY_TYPES, PAYMENT_METHODS, ORDER_STATUS, MIN_DELIVERY_AMOUNT
)
from .auth import (
    verify_credentials,
    get_current_user,
    require_auth,
    create_login_response,
    create_logout_response,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Kadıoğlu Yufka", lifespan=lifespan)

BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

templates.env.globals["PRODUCT_TYPES"] = PRODUCT_TYPES
templates.env.globals["PRODUCED_PRODUCTS"] = PRODUCED_PRODUCTS
templates.env.globals["PURCHASED_PRODUCTS"] = PURCHASED_PRODUCTS


def format_date(value, format="%d.%m.%Y"):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.strftime(format)


def format_currency(value):
    return f"{value:,.2f} ₺".replace(",", ".")


templates.env.filters["date"] = format_date
templates.env.filters["currency"] = format_currency


# ==================== AUTH ROUTES ====================

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if verify_credentials(username, password):
        return create_login_response(username)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "Geçersiz kullanıcı adı veya şifre"},
        status_code=401,
    )


@app.get("/logout")
async def logout():
    return create_logout_response()


# ==================== DASHBOARD ====================

@app.get("/", response_class=HTMLResponse)
@require_auth
async def dashboard(request: Request):
    today = date.today().isoformat()

    async with get_db_connection() as db:
        # Bugünkü üretim
        cursor = await db.execute(
            "SELECT product_type, SUM(quantity) as total FROM production WHERE date = ? GROUP BY product_type",
            (today,),
        )
        today_production = await cursor.fetchall()

        # Bugünkü satış
        cursor = await db.execute(
            "SELECT product_type, SUM(quantity) as total, SUM(total_price) as revenue FROM sales WHERE date = ? GROUP BY product_type",
            (today,),
        )
        today_sales = await cursor.fetchall()

        # Toplam gelir
        cursor = await db.execute(
            "SELECT SUM(total_price) as total FROM sales WHERE date = ?", (today,)
        )
        row = await cursor.fetchone()
        today_revenue = row["total"] if row["total"] else 0

        # Düşük hammadde stok uyarıları
        cursor = await db.execute("""
            SELECT name, unit, stock_quantity, min_stock_level, 'material' as type
            FROM materials
            WHERE stock_quantity <= min_stock_level AND min_stock_level > 0
            ORDER BY stock_quantity ASC
        """)
        low_stock_materials = await cursor.fetchall()

        # Düşük ürün stok uyarıları
        cursor = await db.execute("""
            SELECT product_type, stock_quantity, min_stock_level, 'product' as type
            FROM product_stock
            WHERE stock_quantity <= min_stock_level AND min_stock_level > 0
            ORDER BY stock_quantity ASC
        """)
        low_stock_products = await cursor.fetchall()

        # Son 5 işlem (üretim + satış)
        cursor = await db.execute("""
            SELECT 'production' as type, date, product_type, quantity, NULL as total_price, created_at
            FROM production
            UNION ALL
            SELECT 'sales' as type, date, product_type, quantity, total_price, created_at
            FROM sales
            ORDER BY created_at DESC
            LIMIT 5
        """)
        recent_activities = await cursor.fetchall()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "today": today,
            "today_production": today_production,
            "today_sales": today_sales,
            "today_revenue": today_revenue,
            "low_stock_materials": low_stock_materials,
            "low_stock_products": low_stock_products,
            "recent_activities": recent_activities,
            "product_types": PRODUCT_TYPES,
        },
    )


# ==================== PRODUCTION ====================

@app.get("/production", response_class=HTMLResponse)
@require_auth
async def production_page(request: Request):
    async with get_db_connection() as db:
        cursor = await db.execute("SELECT * FROM materials ORDER BY name")
        materials = await cursor.fetchall()

        cursor = await db.execute(
            "SELECT * FROM production ORDER BY date DESC, created_at DESC LIMIT 20"
        )
        productions = await cursor.fetchall()

        # Ürün stoklarını al
        cursor = await db.execute("SELECT * FROM product_stock")
        product_stocks = {row["product_type"]: row for row in await cursor.fetchall()}

    return templates.TemplateResponse(
        "production.html",
        {
            "request": request,
            "materials": materials,
            "productions": productions,
            "product_types": PRODUCED_PRODUCTS,  # Sadece üretilen ürünler
            "product_stocks": product_stocks,
            "today": date.today().isoformat(),
        },
    )


@app.post("/production")
@require_auth
async def add_production(request: Request):
    form = await request.form()
    production_date = form.get("production_date")
    product_type = form.get("product_type")
    quantity = int(form.get("quantity"))
    notes = form.get("notes", "")

    # Kullanılan malzemeleri topla
    materials_used = {}
    for key, value in form.items():
        if key.startswith("material_") and value:
            material_id = int(key.replace("material_", ""))
            amount = float(value)
            if amount > 0:
                materials_used[material_id] = amount

    async with get_db_connection() as db:
        # Üretim kaydı ekle
        cursor = await db.execute(
            """INSERT INTO production (date, product_type, quantity, materials_used, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (production_date, product_type, quantity, json.dumps(materials_used) if materials_used else None, notes or None),
        )
        production_id = cursor.lastrowid

        # Hammadde stoktan düş
        for material_id, amount in materials_used.items():
            await db.execute(
                "UPDATE materials SET stock_quantity = stock_quantity - ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (amount, material_id),
            )
            await db.execute(
                """INSERT INTO stock_movements (material_id, movement_type, quantity, reference_type, reference_id, notes)
                   VALUES (?, 'production', ?, 'production', ?, ?)""",
                (material_id, -amount, production_id, f"{PRODUCT_TYPES.get(product_type, product_type)} üretimi"),
            )

        # Ürün stoğuna ekle
        await db.execute(
            "UPDATE product_stock SET stock_quantity = stock_quantity + ?, updated_at = CURRENT_TIMESTAMP WHERE product_type = ?",
            (quantity, product_type),
        )
        await db.execute(
            """INSERT INTO product_stock_movements (product_type, movement_type, quantity, reference_type, reference_id, notes)
               VALUES (?, 'production', ?, 'production', ?, ?)""",
            (product_type, quantity, production_id, "Üretim"),
        )

        await db.commit()

    return RedirectResponse(url="/production", status_code=302)


@app.post("/production/{production_id}/delete")
@require_auth
async def delete_production(request: Request, production_id: int):
    async with get_db_connection() as db:
        # Üretim kaydını al
        cursor = await db.execute("SELECT product_type, quantity, materials_used FROM production WHERE id = ?", (production_id,))
        row = await cursor.fetchone()

        if row:
            # Hammadde stoklarını geri ekle
            if row["materials_used"]:
                materials_used = json.loads(row["materials_used"])
                for material_id, amount in materials_used.items():
                    await db.execute(
                        "UPDATE materials SET stock_quantity = stock_quantity + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (amount, int(material_id)),
                    )

            # Ürün stoğundan düş
            await db.execute(
                "UPDATE product_stock SET stock_quantity = stock_quantity - ?, updated_at = CURRENT_TIMESTAMP WHERE product_type = ?",
                (row["quantity"], row["product_type"]),
            )

        # Stok hareketlerini sil
        await db.execute("DELETE FROM stock_movements WHERE reference_type = 'production' AND reference_id = ?", (production_id,))
        await db.execute("DELETE FROM product_stock_movements WHERE reference_type = 'production' AND reference_id = ?", (production_id,))

        # Üretim kaydını sil
        await db.execute("DELETE FROM production WHERE id = ?", (production_id,))
        await db.commit()

    return RedirectResponse(url="/production", status_code=302)


# ==================== SALES ====================

@app.get("/sales", response_class=HTMLResponse)
@require_auth
async def sales_page(request: Request):
    async with get_db_connection() as db:
        cursor = await db.execute(
            "SELECT * FROM sales ORDER BY date DESC, created_at DESC LIMIT 20"
        )
        sales = await cursor.fetchall()

        # Ürün stoklarını ve fiyatlarını al
        cursor = await db.execute("SELECT * FROM product_stock")
        product_stocks = {row["product_type"]: row for row in await cursor.fetchall()}
        product_prices = {row["product_type"]: row["price"] for row in product_stocks.values()}

    return templates.TemplateResponse(
        "sales.html",
        {
            "request": request,
            "sales": sales,
            "product_types": PRODUCT_TYPES,
            "product_stocks": product_stocks,
            "product_prices": product_prices,
            "today": date.today().isoformat(),
        },
    )


@app.post("/sales")
@require_auth
async def add_sale(
    request: Request,
    sale_date: str = Form(...),
    product_type: str = Form(...),
    quantity: int = Form(...),
    unit_price: float = Form(...),
    customer_name: str = Form(""),
    notes: str = Form(""),
):
    total_price = quantity * unit_price

    async with get_db_connection() as db:
        # Satış kaydı ekle
        cursor = await db.execute(
            """INSERT INTO sales (date, product_type, quantity, unit_price, total_price, customer_name, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (sale_date, product_type, quantity, unit_price, total_price, customer_name or None, notes or None),
        )
        sale_id = cursor.lastrowid

        # Ürün stoğundan düş
        await db.execute(
            "UPDATE product_stock SET stock_quantity = stock_quantity - ?, updated_at = CURRENT_TIMESTAMP WHERE product_type = ?",
            (quantity, product_type),
        )
        await db.execute(
            """INSERT INTO product_stock_movements (product_type, movement_type, quantity, reference_type, reference_id, notes)
               VALUES (?, 'sale', ?, 'sale', ?, ?)""",
            (product_type, -quantity, sale_id, customer_name or "Satış"),
        )

        await db.commit()

    return RedirectResponse(url="/sales", status_code=302)


@app.post("/sales/{sale_id}/delete")
@require_auth
async def delete_sale(request: Request, sale_id: int):
    async with get_db_connection() as db:
        # Satış kaydını al
        cursor = await db.execute("SELECT product_type, quantity FROM sales WHERE id = ?", (sale_id,))
        row = await cursor.fetchone()

        if row:
            # Ürün stoğuna geri ekle
            await db.execute(
                "UPDATE product_stock SET stock_quantity = stock_quantity + ?, updated_at = CURRENT_TIMESTAMP WHERE product_type = ?",
                (row["quantity"], row["product_type"]),
            )

        # Stok hareketini sil
        await db.execute("DELETE FROM product_stock_movements WHERE reference_type = 'sale' AND reference_id = ?", (sale_id,))

        # Satış kaydını sil
        await db.execute("DELETE FROM sales WHERE id = ?", (sale_id,))
        await db.commit()

    return RedirectResponse(url="/sales", status_code=302)


# ==================== MATERIALS ====================

@app.get("/materials", response_class=HTMLResponse)
@require_auth
async def materials_page(request: Request):
    async with get_db_connection() as db:
        cursor = await db.execute("SELECT * FROM materials ORDER BY name")
        materials = await cursor.fetchall()

    return templates.TemplateResponse(
        "materials.html",
        {"request": request, "materials": materials},
    )


@app.post("/materials")
@require_auth
async def add_material(
    request: Request,
    name: str = Form(...),
    unit: str = Form(...),
    price: float = Form(0),
    min_stock_level: float = Form(0),
):
    async with get_db_connection() as db:
        await db.execute(
            """INSERT OR REPLACE INTO materials (name, unit, price, stock_quantity, min_stock_level, updated_at)
               VALUES (?, ?, ?, 0, ?, CURRENT_TIMESTAMP)""",
            (name, unit, price, min_stock_level),
        )
        await db.commit()

    return RedirectResponse(url="/materials", status_code=302)


@app.post("/materials/{material_id}/update")
@require_auth
async def update_material(
    request: Request,
    material_id: int,
    price: float = Form(...),
    min_stock_level: float = Form(0),
):
    async with get_db_connection() as db:
        await db.execute(
            "UPDATE materials SET price = ?, min_stock_level = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (price, min_stock_level, material_id),
        )
        await db.commit()

    return RedirectResponse(url="/materials", status_code=302)


@app.post("/materials/{material_id}/delete")
@require_auth
async def delete_material(request: Request, material_id: int):
    async with get_db_connection() as db:
        await db.execute("DELETE FROM stock_movements WHERE material_id = ?", (material_id,))
        await db.execute("DELETE FROM materials WHERE id = ?", (material_id,))
        await db.commit()

    return RedirectResponse(url="/materials", status_code=302)


# ==================== STOCK ====================

@app.get("/stock", response_class=HTMLResponse)
@require_auth
async def stock_page(request: Request):
    async with get_db_connection() as db:
        # Hammadde stokları
        cursor = await db.execute("SELECT * FROM materials ORDER BY name")
        materials = await cursor.fetchall()

        # Ürün stokları
        cursor = await db.execute("SELECT * FROM product_stock ORDER BY product_type")
        product_stocks = await cursor.fetchall()

        # Hammadde hareketleri
        cursor = await db.execute("""
            SELECT sm.*, m.name as material_name, m.unit as material_unit
            FROM stock_movements sm
            JOIN materials m ON sm.material_id = m.id
            ORDER BY sm.created_at DESC
            LIMIT 20
        """)
        material_movements = await cursor.fetchall()

        # Ürün stok hareketleri
        cursor = await db.execute("""
            SELECT * FROM product_stock_movements
            ORDER BY created_at DESC
            LIMIT 20
        """)
        product_movements = await cursor.fetchall()

    return templates.TemplateResponse(
        "stock.html",
        {
            "request": request,
            "materials": materials,
            "product_stocks": product_stocks,
            "material_movements": material_movements,
            "product_movements": product_movements,
            "movement_types": MOVEMENT_TYPES,
            "product_types": PRODUCT_TYPES,
            "purchased_products": PURCHASED_PRODUCTS,
        },
    )


@app.post("/stock/add")
@require_auth
async def add_stock(
    request: Request,
    material_id: int = Form(...),
    quantity: float = Form(...),
    notes: str = Form(""),
):
    async with get_db_connection() as db:
        # Stok miktarını güncelle
        await db.execute(
            "UPDATE materials SET stock_quantity = stock_quantity + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (quantity, material_id),
        )

        # Stok hareketi kaydet
        await db.execute(
            """INSERT INTO stock_movements (material_id, movement_type, quantity, notes)
               VALUES (?, 'in', ?, ?)""",
            (material_id, quantity, notes or "Stok girişi"),
        )

        await db.commit()

    return RedirectResponse(url="/stock", status_code=302)


@app.post("/stock/adjust")
@require_auth
async def adjust_stock(
    request: Request,
    material_id: int = Form(...),
    new_quantity: float = Form(...),
    notes: str = Form(""),
):
    async with get_db_connection() as db:
        # Mevcut stok miktarını al
        cursor = await db.execute("SELECT stock_quantity FROM materials WHERE id = ?", (material_id,))
        row = await cursor.fetchone()
        current_quantity = row["stock_quantity"] if row else 0

        difference = new_quantity - current_quantity

        # Stok miktarını güncelle
        await db.execute(
            "UPDATE materials SET stock_quantity = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (new_quantity, material_id),
        )

        # Stok hareketi kaydet
        await db.execute(
            """INSERT INTO stock_movements (material_id, movement_type, quantity, notes)
               VALUES (?, 'adjustment', ?, ?)""",
            (material_id, difference, notes or "Stok düzeltmesi"),
        )

        await db.commit()

    return RedirectResponse(url="/stock", status_code=302)


@app.post("/stock/product/add")
@require_auth
async def add_product_stock(
    request: Request,
    product_type: str = Form(...),
    quantity: int = Form(...),
    notes: str = Form(""),
):
    """Hazır ürün alımı (Mantı, Kadayıf gibi)"""
    async with get_db_connection() as db:
        # Ürün stoğunu güncelle
        await db.execute(
            "UPDATE product_stock SET stock_quantity = stock_quantity + ?, updated_at = CURRENT_TIMESTAMP WHERE product_type = ?",
            (quantity, product_type),
        )

        # Stok hareketi kaydet
        await db.execute(
            """INSERT INTO product_stock_movements (product_type, movement_type, quantity, notes)
               VALUES (?, 'in', ?, ?)""",
            (product_type, quantity, notes or "Ürün alımı"),
        )

        await db.commit()

    return RedirectResponse(url="/stock", status_code=302)


@app.post("/stock/product/adjust")
@require_auth
async def adjust_product_stock(
    request: Request,
    product_type: str = Form(...),
    new_quantity: int = Form(...),
    notes: str = Form(""),
):
    """Ürün stok düzeltmesi"""
    async with get_db_connection() as db:
        # Mevcut stok miktarını al
        cursor = await db.execute("SELECT stock_quantity FROM product_stock WHERE product_type = ?", (product_type,))
        row = await cursor.fetchone()
        current_quantity = row["stock_quantity"] if row else 0

        difference = new_quantity - current_quantity

        # Stok miktarını güncelle
        await db.execute(
            "UPDATE product_stock SET stock_quantity = ?, updated_at = CURRENT_TIMESTAMP WHERE product_type = ?",
            (new_quantity, product_type),
        )

        # Stok hareketi kaydet
        await db.execute(
            """INSERT INTO product_stock_movements (product_type, movement_type, quantity, notes)
               VALUES (?, 'adjustment', ?, ?)""",
            (product_type, difference, notes or "Stok düzeltmesi"),
        )

        await db.commit()

    return RedirectResponse(url="/stock", status_code=302)


@app.post("/stock/product/price")
@require_auth
async def update_product_price(
    request: Request,
    product_type: str = Form(...),
    price: float = Form(...),
):
    """Ürün fiyatı güncelleme"""
    async with get_db_connection() as db:
        await db.execute(
            "UPDATE product_stock SET price = ?, updated_at = CURRENT_TIMESTAMP WHERE product_type = ?",
            (price, product_type),
        )
        await db.commit()
    
    return RedirectResponse(url="/stock", status_code=302)


# ==================== REPORTS ====================

@app.get("/reports", response_class=HTMLResponse)
@require_auth
async def reports_page(
    request: Request,
    period: str = Query("today"),
    start_date: str = Query(None),
    end_date: str = Query(None),
):
    today = date.today()

    if period == "today":
        start = end = today
    elif period == "week":
        start = today - timedelta(days=today.weekday())
        end = today
    elif period == "month":
        start = today.replace(day=1)
        end = today
    elif period == "custom" and start_date and end_date:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    else:
        start = end = today

    async with get_db_connection() as db:
        # Üretim raporu
        cursor = await db.execute(
            """SELECT product_type, SUM(quantity) as total
               FROM production
               WHERE date BETWEEN ? AND ?
               GROUP BY product_type""",
            (start.isoformat(), end.isoformat()),
        )
        production_summary = await cursor.fetchall()

        # Satış raporu
        cursor = await db.execute(
            """SELECT product_type, SUM(quantity) as total_qty, SUM(total_price) as total_revenue
               FROM sales
               WHERE date BETWEEN ? AND ?
               GROUP BY product_type""",
            (start.isoformat(), end.isoformat()),
        )
        sales_summary = await cursor.fetchall()

        # Toplam gelir
        cursor = await db.execute(
            "SELECT SUM(total_price) as total FROM sales WHERE date BETWEEN ? AND ?",
            (start.isoformat(), end.isoformat()),
        )
        row = await cursor.fetchone()
        total_revenue = row["total"] if row["total"] else 0

        # Günlük detay
        cursor = await db.execute(
            """SELECT date, SUM(quantity) as production_qty
               FROM production
               WHERE date BETWEEN ? AND ?
               GROUP BY date
               ORDER BY date DESC""",
            (start.isoformat(), end.isoformat()),
        )
        daily_production = await cursor.fetchall()

        cursor = await db.execute(
            """SELECT date, SUM(quantity) as sales_qty, SUM(total_price) as revenue
               FROM sales
               WHERE date BETWEEN ? AND ?
               GROUP BY date
               ORDER BY date DESC""",
            (start.isoformat(), end.isoformat()),
        )
        daily_sales = await cursor.fetchall()

    return templates.TemplateResponse(
        "reports.html",
        {
            "request": request,
            "period": period,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "production_summary": production_summary,
            "sales_summary": sales_summary,
            "total_revenue": total_revenue,
            "daily_production": daily_production,
            "daily_sales": daily_sales,
            "product_types": PRODUCT_TYPES,
        },
    )


# ==================== ORDERS ====================

@app.get("/order", response_class=HTMLResponse)
async def order_form_page(request: Request):
    """Müşteri sipariş formu (public)"""
    async with get_db_connection() as db:
        # Ürün fiyatlarını ve birimlerini veritabanından al
        cursor = await db.execute("SELECT product_type, price, unit FROM product_stock")
        rows = await cursor.fetchall()
        product_prices = {row["product_type"]: row["price"] for row in rows}
        product_units = {row["product_type"]: row["unit"] for row in rows}
    
    return templates.TemplateResponse(
        "order_form.html",
        {
            "request": request,
            "product_types": PRODUCT_TYPES,
            "product_prices": product_prices,
            "product_units": product_units,
            "delivery_types": DELIVERY_TYPES,
            "payment_methods": PAYMENT_METHODS,
            "min_delivery_amount": MIN_DELIVERY_AMOUNT,
            "today": date.today().isoformat(),
        },
    )


@app.post("/order")
async def submit_order(request: Request):
    """Sipariş gönderme (public)"""
    form = await request.form()
    
    delivery_date = form.get("delivery_date")
    delivery_type = form.get("delivery_type")
    customer_name = form.get("customer_name")
    customer_phone = form.get("customer_phone")
    address = form.get("address", "")
    payment_method = form.get("payment_method")
    notes = form.get("notes", "")
    
    
    # Ürünleri topla
    items = []
    total_amount = 0
    
    # Ürün fiyatlarını veritabanından al
    async with get_db_connection() as db:
        cursor = await db.execute("SELECT product_type, price FROM product_stock")
        rows = await cursor.fetchall()
        product_prices = {row["product_type"]: row["price"] for row in rows}
    
    for key, value in form.items():
        if key.startswith("product_") and value:
            product_type = key.replace("product_", "")
            quantity = int(value)
            if quantity > 0:
                unit_price = product_prices.get(product_type, 50)
                item_total = quantity * unit_price
                items.append({
                    "product_type": product_type,
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "total": item_total
                })
                total_amount += item_total
    
    # Eve teslimat için minimum tutar kontrolü
    if delivery_type == "eve_gelsin" and total_amount < MIN_DELIVERY_AMOUNT:
        async with get_db_connection() as db:
            cursor = await db.execute("SELECT product_type, price, unit FROM product_stock")
            rows = await cursor.fetchall()
            product_prices = {row["product_type"]: row["price"] for row in rows}
            product_units = {row["product_type"]: row["unit"] for row in rows}
        
        return templates.TemplateResponse(
            "order_form.html",
            {
                "request": request,
                "error": f"Eve teslimat için minimum sipariş tutarı {MIN_DELIVERY_AMOUNT} TL olmalıdır.",
                "product_types": PRODUCT_TYPES,
                "product_prices": product_prices,
                "product_units": product_units,
                "delivery_types": DELIVERY_TYPES,
                "payment_methods": PAYMENT_METHODS,
                "min_delivery_amount": MIN_DELIVERY_AMOUNT,
                "today": date.today().isoformat(),
            },
            status_code=400,
        )
    
    if not items:
        async with get_db_connection() as db:
            cursor = await db.execute("SELECT product_type, price, unit FROM product_stock")
            rows = await cursor.fetchall()
            product_prices = {row["product_type"]: row["price"] for row in rows}
            product_units = {row["product_type"]: row["unit"] for row in rows}
        
        return templates.TemplateResponse(
            "order_form.html",
            {
                "request": request,
                "error": "Lütfen en az bir ürün seçin.",
                "product_types": PRODUCT_TYPES,
                "product_prices": product_prices,
                "product_units": product_units,
                "delivery_types": DELIVERY_TYPES,
                "payment_methods": PAYMENT_METHODS,
                "min_delivery_amount": MIN_DELIVERY_AMOUNT,
                "today": date.today().isoformat(),
            },
            status_code=400,
        )
    
    async with get_db_connection() as db:
        cursor = await db.execute(
            """INSERT INTO orders (order_date, delivery_date, delivery_type, customer_name, customer_phone, 
                                   address, items, total_amount, payment_method, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                date.today().isoformat(),
                delivery_date,
                delivery_type,
                customer_name,
                customer_phone,
                address if delivery_type == "eve_gelsin" else None,
                json.dumps(items),
                total_amount,
                payment_method,
                notes or None,
            ),
        )
        order_id = cursor.lastrowid
        await db.commit()
    
    # Ürün fiyatlarını ve birimlerini tekrar al (template için)
    async with get_db_connection() as db:
        cursor = await db.execute("SELECT product_type, price, unit FROM product_stock")
        rows = await cursor.fetchall()
        product_prices = {row["product_type"]: row["price"] for row in rows}
        product_units = {row["product_type"]: row["unit"] for row in rows}
    
    return templates.TemplateResponse(
        "order_form.html",
        {
            "request": request,
            "success": True,
            "order_id": order_id,
            "product_types": PRODUCT_TYPES,
            "product_prices": product_prices,
            "product_units": product_units,
            "delivery_types": DELIVERY_TYPES,
            "payment_methods": PAYMENT_METHODS,
            "min_delivery_amount": MIN_DELIVERY_AMOUNT,
            "today": date.today().isoformat(),
        },
    )


@app.get("/orders", response_class=HTMLResponse)
@require_auth
async def orders_page(
    request: Request,
    status: str = Query(None),
    date_filter: str = Query("all"),
):
    """Admin sipariş yönetimi"""
    async with get_db_connection() as db:
        query = "SELECT * FROM orders WHERE 1=1"
        params = []
        
        if status:
            query += " AND status = ?"
            params.append(status)
        
        if date_filter == "today":
            query += " AND delivery_date = ?"
            params.append(date.today().isoformat())
        elif date_filter == "upcoming":
            query += " AND delivery_date >= ?"
            params.append(date.today().isoformat())
        
        query += " ORDER BY delivery_date ASC, created_at DESC"
        
        cursor = await db.execute(query, params)
        orders = await cursor.fetchall()
        
        # JSON items'ı parse et
        orders_list = []
        for order in orders:
            order_dict = dict(order)
            # items key'i dict.items() ile çakışıyor, order_items olarak değiştir
            order_dict["order_items"] = json.loads(order["items"])
            del order_dict["items"]  # Eski items'ı sil
            orders_list.append(order_dict)
        
        # Ürün birimlerini al
        cursor = await db.execute("SELECT product_type, unit FROM product_stock")
        rows = await cursor.fetchall()
        product_units = {row["product_type"]: row["unit"] for row in rows}
    
    return templates.TemplateResponse(
        "orders.html",
        {
            "request": request,
            "orders": orders_list,
            "product_types": PRODUCT_TYPES,
            "product_units": product_units,
            "delivery_types": DELIVERY_TYPES,
            "payment_methods": PAYMENT_METHODS,
            "order_status": ORDER_STATUS,
            "current_status": status,
            "date_filter": date_filter,
        },
    )


@app.post("/orders/{order_id}/status")
@require_auth
async def update_order_status(
    request: Request,
    order_id: int,
    status: str = Form(...),
):
    """Sipariş durumu güncelleme"""
    async with get_db_connection() as db:
        await db.execute(
            "UPDATE orders SET status = ? WHERE id = ?",
            (status, order_id),
        )
        await db.commit()
    
    return RedirectResponse(url="/orders", status_code=302)


@app.post("/orders/{order_id}/delete")
@require_auth
async def delete_order(request: Request, order_id: int):
    """Sipariş silme"""
    async with get_db_connection() as db:
        await db.execute("DELETE FROM orders WHERE id = ?", (order_id,))
        await db.commit()
    
    return RedirectResponse(url="/orders", status_code=302)
