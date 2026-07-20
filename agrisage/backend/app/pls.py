"""FR-4: PLS(안전사용기간) 자동 체크."""
from datetime import date, datetime


def check_pls(product: dict, expected_harvest_date: str, spray_date: str | None = None):
    """
    product: pesticide_db.json의 product dict (phi_days 포함)
    expected_harvest_date: "YYYY-MM-DD" 예상 수확일
    spray_date: "YYYY-MM-DD" 방제(살포) 예정일. 미지정 시 오늘 날짜 사용.
    """
    harvest = datetime.strptime(expected_harvest_date, "%Y-%m-%d").date()
    spray = (
        datetime.strptime(spray_date, "%Y-%m-%d").date() if spray_date else date.today()
    )
    days_until_harvest = (harvest - spray).days
    phi = product["phi_days"]

    if days_until_harvest < 0:
        status = "invalid"
        message = "The expected harvest date is before the spray date. Please double-check the dates."
    elif days_until_harvest < phi:
        status = "violation"
        message = (
            f"Warning: '{product['product_name']}' has a pre-harvest interval (PHI) of {phi} days, but "
            f"only {days_until_harvest} day(s) remain between the spray date and the expected harvest date. "
            f"This risks exceeding the maximum residue limit, so this product is not recommended."
        )
    else:
        status = "safe"
        message = (
            f"Safe: {days_until_harvest} day(s) remain between the spray date and the expected harvest "
            f"date, which meets the pre-harvest interval ({phi} days)."
        )

    return {
        "status": status,  # safe | violation | invalid
        "message": message,
        "phi_days": phi,
        "days_until_harvest": days_until_harvest,
    }


def check_pls_for_products(products: list[dict], expected_harvest_date: str, spray_date: str | None = None):
    results = []
    for p in products:
        pls_result = check_pls(p, expected_harvest_date, spray_date)
        results.append({**p, "pls": pls_result})
    # 안전한 제품 우선 정렬 (safe > violation > invalid)
    order = {"safe": 0, "violation": 1, "invalid": 2}
    results.sort(key=lambda r: order.get(r["pls"]["status"], 3))
    return results
