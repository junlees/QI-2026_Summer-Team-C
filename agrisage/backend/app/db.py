import json
import os

_DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "pesticide_db.json")

DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    import psycopg2
    import psycopg2.extras
    import psycopg2.pool

    POOL = psycopg2.pool.SimpleConnectionPool(1, 5, DATABASE_URL)

    def _query(sql, params=()):
        conn = POOL.getconn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return cur.fetchall()
        finally:
            POOL.putconn(conn)

    def get_disease_info(class_name: str):
        rows = _query(
            "SELECT crop, crop_en, disease_name, pathogen_type FROM diseases WHERE class_name = %s",
            (class_name,),
        )
        if not rows:
            return None
        info = dict(rows[0])
        products = _query(
            """
            SELECT product_name, active_ingredient, phi_days, organic_allowed, notes
            FROM products WHERE class_name = %s ORDER BY id
            """,
            (class_name,),
        )
        info["products"] = [dict(p) for p in products]
        return info

    def is_healthy(class_name: str) -> bool:
        rows = _query("SELECT 1 FROM healthy_labels WHERE class_name = %s", (class_name,))
        return len(rows) > 0

else:
    with open(_DATA_PATH, encoding="utf-8") as f:
        PESTICIDE_DB = json.load(f)

    def get_disease_info(class_name: str):
        return PESTICIDE_DB["diseases"].get(class_name)

    def is_healthy(class_name: str) -> bool:
        return class_name in PESTICIDE_DB.get("healthy_labels", [])


def recommend_products(class_name: str, organic_only: bool = False):
    info = get_disease_info(class_name)
    if not info:
        return None
    products = info["products"]
    if organic_only:
        products = [p for p in products if p["organic_allowed"]]
    return {
        "crop": info["crop"],
        "disease_name": info["disease_name"],
        "pathogen_type": info["pathogen_type"],
        "products": products,
    }
