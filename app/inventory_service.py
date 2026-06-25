import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from .db import SessionLocalSync
from .models import CartItem, Product, Purchase, User


inventory_lock = threading.Lock()

# EXPLICACION: HILOS
# Este pool crea trabajadores en segundo plano para procesar operaciones
# criticas del punto de venta sin bloquear las rutas async de FastAPI.
worker_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="pos-worker")


def _decrease_stock_sync(product_id: int, quantity: int) -> bool:
    if quantity <= 0:
        return False

    # EXPLICACION: SINCRONIZACION CON HILOS
    # El Lock permite que solo un hilo a la vez modifique el inventario.
    with inventory_lock:
        with SessionLocalSync() as db:
            # EXPLICACION: TRANSACCION DE BASE DE DATOS
            # db.begin() confirma el cambio si todo sale bien o revierte si falla.
            with db.begin():
                product = db.scalar(select(Product).where(Product.id == product_id))
                if not product or product.stock < quantity:
                    return False
                product.stock -= quantity
            return True


def _increase_stock_sync(product_id: int, quantity: int) -> bool:
    if quantity <= 0:
        return False

    # EXPLICACION: SINCRONIZACION CON HILOS
    # Aumentar stock tambien se protege para evitar cambios simultaneos.
    with inventory_lock:
        with SessionLocalSync() as db:
            # EXPLICACION: TRANSACCION DE BASE DE DATOS
            # El aumento de inventario queda guardado como una operacion atomica.
            with db.begin():
                product = db.scalar(select(Product).where(Product.id == product_id))
                if not product:
                    return False
                product.stock += quantity
            return True


def _checkout_sync(user_id: int) -> dict:
    # EXPLICACION: SINCRONIZACION CON HILOS
    # En una compra, el Lock evita que dos clientes descuenten la misma gorra al mismo tiempo.
    with inventory_lock:
        with SessionLocalSync() as db:
            # EXPLICACION: TRANSACCION DE BASE DE DATOS
            # En esta transaccion se valida stock, se descuenta inventario,
            # se registra la compra y se vacia el carrito como una sola unidad.
            with db.begin():
                user = db.get(User, user_id)
                if not user or not user.address or not user.phone or not user.card_last4:
                    return {"ok": False, "error": "Completa direccion, telefono y tarjeta"}

                items = db.scalars(
                    select(CartItem)
                    .where(CartItem.user_id == user_id)
                    .options(selectinload(CartItem.product))
                ).all()

                if not items:
                    return {"ok": False, "error": "El carrito esta vacio"}

                total = 0.0
                for item in items:
                    if not item.product or item.product.stock < item.quantity:
                        return {"ok": False, "error": "Stock insuficiente"}
                    item.product.stock -= item.quantity
                    total += item.quantity * item.product.price

                db.add(Purchase(user_id=user_id, total=total, status="ACEPTADO"))
                db.execute(delete(CartItem).where(CartItem.user_id == user_id))
                return {"ok": True, "total": total}


async def decrease_stock(product_id: int, quantity: int) -> bool:
    loop = asyncio.get_running_loop()
    # EXPLICACION: ASINCRONISMO + HILOS
    # await espera el resultado del hilo sin bloquear el event loop de FastAPI.
    return await loop.run_in_executor(worker_pool, _decrease_stock_sync, product_id, quantity)


async def increase_stock(product_id: int, quantity: int) -> bool:
    loop = asyncio.get_running_loop()
    # EXPLICACION: ASINCRONISMO + HILOS
    # Esta llamada manda el aumento de stock al pool de hilos.
    return await loop.run_in_executor(worker_pool, _increase_stock_sync, product_id, quantity)


async def checkout_cart(user_id: int) -> dict:
    loop = asyncio.get_running_loop()
    # EXPLICACION: ASINCRONISMO + HILOS
    # La compra completa se ejecuta en un hilo y la ruta async espera con await.
    return await loop.run_in_executor(worker_pool, _checkout_sync, user_id)
