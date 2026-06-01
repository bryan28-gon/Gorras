import asyncio
import threading

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Product


inventory_lock = threading.Lock()


async def decrease_stock(db: AsyncSession, product_id: int, quantity: int) -> bool:
    if quantity <= 0:
        return False
    with inventory_lock:
        async with db.begin():
            product = await db.scalar(select(Product).where(Product.id == product_id))
            if not product or product.stock < quantity:
                return False
            product.stock -= quantity
        await db.commit()
    await asyncio.sleep(0)
    return True


async def increase_stock(db: AsyncSession, product_id: int, quantity: int) -> bool:
    if quantity <= 0:
        return False
    with inventory_lock:
        async with db.begin():
            product = await db.scalar(select(Product).where(Product.id == product_id))
            if not product:
                return False
            product.stock += quantity
        await db.commit()
    await asyncio.sleep(0)
    return True
