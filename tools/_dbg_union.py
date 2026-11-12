import sys
sys.path.insert(0, '.')
from app.db import query

# Test the UNION query (fixed - no parens around first SELECT)
sql = """SELECT id, name, description, price_cents, currency, category_id, created_at
         FROM products WHERE active = 1"""
params = []
seller_sql = """SELECT id, name, description, price_cents, currency, category_id, created_at
                FROM seller_listings WHERE status = 'active'"""
sql = f"{sql} UNION ALL {seller_sql} ORDER BY created_at DESC"
print('SQL:', sql)
rows = query(sql, tuple(params))
print('Rows:', rows)