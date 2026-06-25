import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .db import Base, engine, get_db
from .email_service import send_ticket_email, ticket_timestamp
from .inventory_service import checkout_cart, decrease_stock, increase_stock
from .models import CartItem, Product, User
from .security import hash_password, verify_password

app = FastAPI(title="Punto de Venta de Gorras")
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

sessions: dict[str, int] = {}


def render(request: Request, template_name: str, context: dict):
    context.setdefault("request", request)
    return templates.TemplateResponse(request, template_name, context)


def current_user(request: Request):
    session_id = request.cookies.get("session_id")
    if not session_id:
        return None
    user_id = sessions.get(session_id)
    return user_id


async def is_admin(request: Request, db: AsyncSession) -> bool:
    user_id = current_user(request)
    if not user_id:
        return False
    user = await db.get(User, user_id)
    return bool(user and user.role == "ADMIN")


@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        columns = await conn.execute(text("PRAGMA table_info(users)"))
        names = [row[1] for row in columns.fetchall()]
        if "role" not in names:
            await conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(20) DEFAULT 'CLIENTE'"))
        await conn.execute(text("UPDATE users SET role='CLIENTE' WHERE role IS NULL"))
        product_columns = await conn.execute(text("PRAGMA table_info(products)"))
        product_names = [row[1] for row in product_columns.fetchall()]
        product_schema = {
            "sku": "VARCHAR(30)",
            "brand": "VARCHAR(80)",
            "color": "VARCHAR(30)",
            "size": "VARCHAR(20)",
            "image_url": "VARCHAR(500)",
        }
        for name, column_type in product_schema.items():
            if name not in product_names:
                await conn.execute(text(f"ALTER TABLE products ADD COLUMN {name} {column_type}"))

        products_count = await conn.execute(text("SELECT COUNT(*) FROM products"))
        if products_count.scalar_one() == 0:
            await conn.execute(
                text(
                    """
                    INSERT INTO products
                    (sku, name, brand, color, size, description, price, stock, image_url)
                    VALUES
                    ('GOR-001', 'Gorra Beisbol Verde', 'UrbanCap', 'Verde', 'Ajustable',
                     'Gorra tipo beisbol con broche ajustable para venta rapida.', 299.00, 12,
                     'https://images.unsplash.com/photo-1588850561407-ed78c282e89b?auto=format&fit=crop&w=900&q=80'),
                    ('GOR-014', 'Gorra Snapback Azul', 'Street Crown', 'Azul', 'Unitalla',
                     'Gorra snapback estructurada para uso casual.', 349.00, 8,
                     'https://images.unsplash.com/photo-1521369909029-2afed882baee?auto=format&fit=crop&w=900&q=80'),
                    ('GOR-220', 'Gorra Trucker Naranja', 'RoadCap', 'Naranja', 'Ajustable',
                     'Gorra trucker con malla trasera y frente rigido.', 279.00, 15,
                     'https://images.unsplash.com/photo-1576871337632-b9aef4c17ab9?auto=format&fit=crop&w=900&q=80'),
                    ('GOR-099', 'Gorra Roja Clasica', 'CapLine', 'Rojo', 'Unitalla',
                     'Gorra clasica para mostrador y pedidos rapidos.', 259.00, 6,
                     'https://images.unsplash.com/photo-1534215754734-18e55d13e346?auto=format&fit=crop&w=900&q=80')
                    """
                )
            )


@app.get("/")
async def home(request: Request, db: AsyncSession = Depends(get_db), q: str = ""):
    query = select(Product)
    if q:
        like = f"%{q}%"
        query = query.where(
            or_(
                Product.name.ilike(like),
                Product.description.ilike(like),
                Product.brand.ilike(like),
                Product.color.ilike(like),
                Product.size.ilike(like),
                Product.sku.ilike(like),
            )
        )
    products = (await db.scalars(query.order_by(Product.id.desc()))).all()
    return render(request, "products.html", {"products": products, "q": q, "user_id": current_user(request)})


@app.get("/product/{product_id}")
async def product_detail(product_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    product = await db.get(Product, product_id)
    if not product:
        return RedirectResponse("/", status_code=303)
    return render(request, "product_detail.html", {"product": product, "user_id": current_user(request)})


@app.get("/register")
async def register_page(request: Request):
    return render(request, "register.html", {"error": None})


@app.post("/register")
async def register(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    exists = await db.scalar(select(User).where(or_(User.username == username, User.email == email)))
    if exists:
        return render(request, "register.html", {"error": "Usuario o email ya registrado"})
    users_count = len((await db.scalars(select(User.id))).all())
    role = "ADMIN" if users_count == 0 else "CLIENTE"
    user = User(username=username, email=email, password_hash=hash_password(password), role=role)
    db.add(user)
    await db.commit()
    return RedirectResponse("/login", status_code=303)


@app.get("/login")
async def login_page(request: Request):
    return render(request, "login.html", {"error": None})


@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...), db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.username == username))
    if not user or not verify_password(password, user.password_hash):
        return render(request, "login.html", {"error": "Credenciales invalidas"})
    sid = secrets.token_hex(16)
    sessions[sid] = user.id
    response = RedirectResponse("/", status_code=303)
    response.set_cookie("session_id", sid, httponly=True, samesite="lax")
    return response


@app.get("/logout")
async def logout(request: Request):
    sid = request.cookies.get("session_id")
    if sid and sid in sessions:
        sessions.pop(sid)
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie("session_id")
    return response


@app.post("/cart/add/{product_id}")
async def add_to_cart(product_id: int, request: Request, quantity: int = Form(1), db: AsyncSession = Depends(get_db)):
    user_id = current_user(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    item = await db.scalar(select(CartItem).where(CartItem.user_id == user_id, CartItem.product_id == product_id))
    if item:
        item.quantity += quantity
    else:
        db.add(CartItem(user_id=user_id, product_id=product_id, quantity=quantity))
    await db.commit()
    return RedirectResponse("/cart", status_code=303)


@app.get("/cart")
async def cart_page(request: Request, db: AsyncSession = Depends(get_db), ok: str = "", error: str = ""):
    user_id = current_user(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    items = (
        await db.scalars(
            select(CartItem).where(CartItem.user_id == user_id).options(selectinload(CartItem.product))
        )
    ).all()
    subtotal = sum(i.quantity * i.product.price for i in items if i.product)
    iva = round(subtotal * 0.16, 2)
    total = round(subtotal + iva, 2)
    return render(
        request,
        "cart.html",
        {
            "items": items,
            "subtotal": subtotal,
            "iva": iva,
            "total": total,
            "user_id": user_id,
            "ok": ok,
            "error": error,
        },
    )


@app.post("/cart/cancel")
async def cancel_purchase(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = current_user(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    await db.execute(delete(CartItem).where(CartItem.user_id == user_id))
    await db.commit()
    return RedirectResponse("/cart", status_code=303)

## TODO:Asincronismo
@app.post("/cart/checkout")
async def checkout(request: Request, db: AsyncSession = Depends(get_db)):
    # EXPLICACION: ASINCRONISMO
    # Esta ruta es async, por eso FastAPI puede atender otras peticiones mientras
    # espera el resultado de checkout_cart con await.
    user_id = current_user(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    result = await checkout_cart(user_id)
    if not result["ok"]:
        target = "/profile" if "tarjeta" in result["error"] else "/cart"
        return RedirectResponse(f"{target}?error={result['error']}", status_code=303)
    ticket = result["ticket"]
    ticket["created_at"] = ticket_timestamp()
    try:
        await send_ticket_email(ticket)
    except Exception:
        return RedirectResponse(
            "/cart?ok=Compra aceptada&error=La compra se registro, pero no se pudo enviar el ticket por correo",
            status_code=303,
        )
    return RedirectResponse("/cart?ok=Compra aceptada y ticket enviado al correo registrado", status_code=303)


@app.get("/profile")
async def profile_page(request: Request, db: AsyncSession = Depends(get_db), error: str = ""):
    user_id = current_user(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    user = await db.get(User, user_id)
    return render(request, "profile.html", {"user": user, "error": error, "user_id": user_id, "role": user.role})


@app.post("/profile")
async def update_profile(
    request: Request,
    address: str = Form(...),
    phone: str = Form(...),
    card: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    user_id = current_user(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    user = await db.get(User, user_id)
    user.address = address
    user.phone = phone
    user.card_last4 = card[-4:]
    await db.commit()
    return RedirectResponse("/profile", status_code=303)


@app.get("/inventory")
async def inventory_page(request: Request, db: AsyncSession = Depends(get_db), q: str = ""):
    user_id = current_user(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    if not await is_admin(request, db):
        return RedirectResponse("/?error=Solo admin puede entrar a inventario", status_code=303)
    query = select(Product)
    if q:
        like = f"%{q}%"
        query = query.where(
            or_(
                Product.name.ilike(like),
                Product.description.ilike(like),
                Product.brand.ilike(like),
                Product.color.ilike(like),
                Product.size.ilike(like),
                Product.sku.ilike(like),
            )
        )
    products = (await db.scalars(query.order_by(Product.id.desc()))).all()
    return render(request, "inventory.html", {"products": products, "q": q, "user_id": user_id})


@app.post("/inventory/add")
async def inventory_add(
    request: Request,
    name: str = Form(...),
    sku: str = Form(""),
    brand: str = Form(""),
    color: str = Form(""),
    size: str = Form(""),
    description: str = Form(...),
    price: float = Form(...),
    stock: int = Form(...),
    image_url: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    if not current_user(request):
        return RedirectResponse("/login", status_code=303)
    if not await is_admin(request, db):
        return RedirectResponse("/", status_code=303)
    db.add(
        Product(
            name=name,
            sku=sku or None,
            brand=brand or None,
            color=color or None,
            size=size or None,
            description=description,
            price=price,
            stock=stock,
            image_url=image_url or None,
        )
    )
    await db.commit()
    return RedirectResponse("/inventory", status_code=303)


@app.post("/inventory/edit/{product_id}")
async def inventory_edit(
    product_id: int,
    request: Request,
    name: str = Form(...),
    sku: str = Form(""),
    brand: str = Form(""),
    color: str = Form(""),
    size: str = Form(""),
    description: str = Form(...),
    price: float = Form(...),
    image_url: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    if not current_user(request):
        return RedirectResponse("/login", status_code=303)
    if not await is_admin(request, db):
        return RedirectResponse("/", status_code=303)
    product = await db.get(Product, product_id)
    if product:
        product.sku = sku or None
        product.name = name
        product.brand = brand or None
        product.color = color or None
        product.size = size or None
        product.description = description
        product.price = price
        product.image_url = image_url or None
        await db.commit()
    return RedirectResponse("/inventory", status_code=303)


@app.post("/inventory/delete/{product_id}")
async def inventory_delete(product_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not current_user(request):
        return RedirectResponse("/login", status_code=303)
    if not await is_admin(request, db):
        return RedirectResponse("/", status_code=303)
    product = await db.get(Product, product_id)
    if product:
        await db.delete(product)
        await db.commit()
    return RedirectResponse("/inventory", status_code=303)


@app.post("/inventory/increase/{product_id}")
async def inventory_increase(product_id: int, request: Request, qty: int = Form(...), db: AsyncSession = Depends(get_db)):
    if not current_user(request):
        return RedirectResponse("/login", status_code=303)
    if not await is_admin(request, db):
        return RedirectResponse("/", status_code=303)
    await increase_stock(product_id, qty)
    return RedirectResponse("/inventory", status_code=303)


@app.post("/inventory/decrease/{product_id}")
async def inventory_decrease(product_id: int, request: Request, qty: int = Form(...), db: AsyncSession = Depends(get_db)):
    if not current_user(request):
        return RedirectResponse("/login", status_code=303)
    if not await is_admin(request, db):
        return RedirectResponse("/", status_code=303)
    await decrease_stock(product_id, qty)
    return RedirectResponse("/inventory", status_code=303)


@app.get("/technical")
async def technical_page(request: Request):
    return render(request, "technical.html", {"user_id": current_user(request)})
