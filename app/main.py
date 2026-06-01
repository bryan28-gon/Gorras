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
from .inventory_service import decrease_stock, increase_stock
from .models import CartItem, Product, Purchase, User
from .security import hash_password, verify_password

app = FastAPI(title="Punto de Venta en Linea")
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

sessions: dict[str, int] = {}


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


@app.get("/")
async def home(request: Request, db: AsyncSession = Depends(get_db), q: str = ""):
    query = select(Product)
    if q:
        like = f"%{q}%"
        query = query.where(or_(Product.name.ilike(like), Product.description.ilike(like)))
    products = (await db.scalars(query.order_by(Product.id.desc()))).all()
    return templates.TemplateResponse("products.html", {"request": request, "products": products, "q": q, "user_id": current_user(request)})


@app.get("/product/{product_id}")
async def product_detail(product_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    product = await db.get(Product, product_id)
    if not product:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("product_detail.html", {"request": request, "product": product, "user_id": current_user(request)})


@app.get("/register")
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request, "error": None})


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
        return templates.TemplateResponse("register.html", {"request": request, "error": "Usuario o email ya registrado"})
    users_count = len((await db.scalars(select(User.id))).all())
    role = "ADMIN" if users_count == 0 else "CLIENTE"
    user = User(username=username, email=email, password_hash=hash_password(password), role=role)
    db.add(user)
    await db.commit()
    return RedirectResponse("/login", status_code=303)


@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...), db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.username == username))
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Credenciales invalidas"})
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
async def cart_page(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = current_user(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    items = (
        await db.scalars(
            select(CartItem).where(CartItem.user_id == user_id).options(selectinload(CartItem.product))
        )
    ).all()
    total = sum(i.quantity * i.product.price for i in items if i.product)
    return templates.TemplateResponse("cart.html", {"request": request, "items": items, "total": total, "user_id": user_id})


@app.post("/cart/cancel")
async def cancel_purchase(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = current_user(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    await db.execute(delete(CartItem).where(CartItem.user_id == user_id))
    await db.commit()
    return RedirectResponse("/cart", status_code=303)


@app.post("/cart/checkout")
async def checkout(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = current_user(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    user = await db.get(User, user_id)
    if not user or not user.address or not user.phone or not user.card_last4:
        return RedirectResponse("/profile?error=Completa direccion, telefono y tarjeta", status_code=303)
    items = (
        await db.scalars(
            select(CartItem).where(CartItem.user_id == user_id).options(selectinload(CartItem.product))
        )
    ).all()
    total = 0.0
    for item in items:
        ok = await decrease_stock(db, item.product_id, item.quantity)
        if not ok:
            return RedirectResponse("/cart?error=Stock insuficiente", status_code=303)
        total += item.quantity * item.product.price
    db.add(Purchase(user_id=user_id, total=total, status="ACEPTADO"))
    await db.execute(delete(CartItem).where(CartItem.user_id == user_id))
    await db.commit()
    return RedirectResponse("/cart?ok=Compra aceptada", status_code=303)


@app.get("/profile")
async def profile_page(request: Request, db: AsyncSession = Depends(get_db), error: str = ""):
    user_id = current_user(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    user = await db.get(User, user_id)
    return templates.TemplateResponse("profile.html", {"request": request, "user": user, "error": error, "user_id": user_id, "role": user.role})


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
        query = query.where(or_(Product.name.ilike(like), Product.description.ilike(like)))
    products = (await db.scalars(query.order_by(Product.id.desc()))).all()
    return templates.TemplateResponse("inventory.html", {"request": request, "products": products, "q": q, "user_id": user_id})


@app.post("/inventory/add")
async def inventory_add(
    request: Request,
    name: str = Form(...),
    description: str = Form(...),
    price: float = Form(...),
    stock: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    if not current_user(request):
        return RedirectResponse("/login", status_code=303)
    if not await is_admin(request, db):
        return RedirectResponse("/", status_code=303)
    db.add(Product(name=name, description=description, price=price, stock=stock))
    await db.commit()
    return RedirectResponse("/inventory", status_code=303)


@app.post("/inventory/edit/{product_id}")
async def inventory_edit(
    product_id: int,
    request: Request,
    name: str = Form(...),
    description: str = Form(...),
    price: float = Form(...),
    db: AsyncSession = Depends(get_db),
):
    if not current_user(request):
        return RedirectResponse("/login", status_code=303)
    if not await is_admin(request, db):
        return RedirectResponse("/", status_code=303)
    product = await db.get(Product, product_id)
    if product:
        product.name = name
        product.description = description
        product.price = price
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
    await increase_stock(db, product_id, qty)
    return RedirectResponse("/inventory", status_code=303)


@app.post("/inventory/decrease/{product_id}")
async def inventory_decrease(product_id: int, request: Request, qty: int = Form(...), db: AsyncSession = Depends(get_db)):
    if not current_user(request):
        return RedirectResponse("/login", status_code=303)
    if not await is_admin(request, db):
        return RedirectResponse("/", status_code=303)
    await decrease_stock(db, product_id, qty)
    return RedirectResponse("/inventory", status_code=303)
