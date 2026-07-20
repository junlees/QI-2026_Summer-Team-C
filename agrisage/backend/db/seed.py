"""pesticide_db.json의 데모 데이터를 Postgres(diseases/healthy_labels/products)로 적재.

사용법:
    export DATABASE_URL=postgresql://...
    python3 db/seed.py
"""
import json
import os
import sys

import psycopg2

_HERE = os.path.dirname(os.path.abspath(__file__))
_JSON_PATH = os.path.join(os.path.dirname(_HERE), "data", "pesticide_db.json")
_SCHEMA_PATH = os.path.join(_HERE, "schema.sql")


def main():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit("DATABASE_URL 환경변수를 설정하세요.")

    with open(_JSON_PATH, encoding="utf-8") as f:
        data = json.load(f)

    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor() as cur:
            with open(_SCHEMA_PATH, encoding="utf-8") as f:
                cur.execute(f.read())

            for class_name, info in data["diseases"].items():
                cur.execute(
                    """
                    INSERT INTO diseases (class_name, crop, crop_en, disease_name, pathogen_type)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (class_name) DO UPDATE SET
                        crop = EXCLUDED.crop,
                        crop_en = EXCLUDED.crop_en,
                        disease_name = EXCLUDED.disease_name,
                        pathogen_type = EXCLUDED.pathogen_type
                    """,
                    (class_name, info["crop"], info.get("crop_en"), info["disease_name"], info.get("pathogen_type")),
                )

                cur.execute("DELETE FROM products WHERE class_name = %s", (class_name,))
                for product in info["products"]:
                    cur.execute(
                        """
                        INSERT INTO products (class_name, product_name, active_ingredient, phi_days, organic_allowed, notes)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            class_name,
                            product["product_name"],
                            product.get("active_ingredient"),
                            product["phi_days"],
                            product.get("organic_allowed", False),
                            product.get("notes"),
                        ),
                    )

            for class_name in data.get("healthy_labels", []):
                cur.execute(
                    "INSERT INTO healthy_labels (class_name) VALUES (%s) ON CONFLICT DO NOTHING",
                    (class_name,),
                )

        conn.commit()
        print(f"Seeded {len(data['diseases'])} diseases, "
              f"{sum(len(i['products']) for i in data['diseases'].values())} products, "
              f"{len(data.get('healthy_labels', []))} healthy labels.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
