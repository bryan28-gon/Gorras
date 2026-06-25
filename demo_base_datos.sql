-- Consultas para demostrar la base de datos del POS de gorras.
-- Abre pos.db con una extension SQLite en VS Code y ejecuta estas consultas.

-- 1. Ver usuarios y roles.
SELECT id, username, email, role, phone, address, card_last4
FROM users
ORDER BY id;

-- 2. Ver inventario actual de gorras.
SELECT id, sku, name, brand, color, size AS ajuste, price, stock
FROM products
ORDER BY id;

-- 3. Antes de comprar, deja una gorra con stock 1 para la demo.
-- Cambia el id por el producto que vas a usar.
UPDATE products
SET stock = 1
WHERE id = 1;

-- 4. Confirmar que el stock quedo en 1.
SELECT id, sku, name, stock
FROM products
WHERE id = 1;

-- 5. Ver carritos activos antes de la compra.
SELECT
  cart_items.id,
  users.username,
  products.name AS producto,
  cart_items.quantity
FROM cart_items
JOIN users ON users.id = cart_items.user_id
JOIN products ON products.id = cart_items.product_id
ORDER BY cart_items.id;

-- 6. Ver compras registradas despues del checkout.
SELECT
  purchases.id,
  users.username,
  purchases.total,
  purchases.status,
  purchases.created_at
FROM purchases
JOIN users ON users.id = purchases.user_id
ORDER BY purchases.id DESC;

-- 7. Revisar que el stock bajo y no quedo negativo.
SELECT id, sku, name, stock
FROM products
WHERE id = 1;
