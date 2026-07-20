"""FR-5: 방제 후 사후관리(closed-loop).

DATABASE_URL이 설정되면 Postgres(followup_cases 테이블)에 영속 저장하고,
없으면 로컬 데모용 인메모리 저장소를 사용한다.
"""
import uuid
from datetime import date, timedelta

from app.db import DATABASE_URL, is_healthy
from app.model_client import classify_image

if DATABASE_URL:
    import json

    import psycopg2.extras

    from app.db import POOL

    def _row_to_case(row):
        case = dict(row)
        followup_result = None
        if case["status"] == "completed":
            followup_result = {
                "verdict": case.pop("followup_verdict"),
                "message": case.pop("followup_message"),
                "new_prediction": case.pop("followup_prediction"),
            }
        else:
            case.pop("followup_verdict", None)
            case.pop("followup_message", None)
            case.pop("followup_prediction", None)
        case["created_at"] = case["created_at"].isoformat()
        case["followup_due"] = case["followup_due"].isoformat()
        case["followup_result"] = followup_result
        return case

    def create_case(crop: str, disease_class: str, followup_days: int = 4):
        case_id = str(uuid.uuid4())[:8]
        due_date = date.today() + timedelta(days=followup_days)
        conn = POOL.getconn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO followup_cases (case_id, crop, original_class, created_at, followup_due, status)
                    VALUES (%s, %s, %s, %s, %s, 'awaiting_followup')
                    RETURNING *
                    """,
                    (case_id, crop, disease_class, date.today(), due_date),
                )
                row = cur.fetchone()
            conn.commit()
        finally:
            POOL.putconn(conn)
        return _row_to_case(row)

    def get_case(case_id: str):
        conn = POOL.getconn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM followup_cases WHERE case_id = %s", (case_id,))
                row = cur.fetchone()
        finally:
            POOL.putconn(conn)
        return _row_to_case(row) if row else None

    def submit_followup_photo(case_id: str, image_bytes: bytes):
        conn = POOL.getconn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM followup_cases WHERE case_id = %s", (case_id,))
                row = cur.fetchone()
                if row is None:
                    return None

                predictions = classify_image(image_bytes, top_k=1)
                top = predictions[0]

                if is_healthy(top["class_name"]):
                    verdict = "improved"
                    message = "The re-check photo shows a healthy plant. The treatment was effective."
                elif top["class_name"] == row["original_class"]:
                    verdict = "not_improved"
                    message = "The same symptoms are still present in the re-check photo. Re-treatment or a new diagnosis is recommended."
                else:
                    verdict = "changed"
                    message = f"A different finding ({top['class_name']}) was detected. A new diagnosis is recommended."

                cur.execute(
                    """
                    UPDATE followup_cases
                    SET status = 'completed', followup_verdict = %s, followup_message = %s, followup_prediction = %s
                    WHERE case_id = %s
                    RETURNING *
                    """,
                    (verdict, message, json.dumps(top), case_id),
                )
                updated = cur.fetchone()
            conn.commit()
        finally:
            POOL.putconn(conn)
        return _row_to_case(updated)

else:
    _CASES: dict[str, dict] = {}

    def create_case(crop: str, disease_class: str, followup_days: int = 4):
        case_id = str(uuid.uuid4())[:8]
        due_date = date.today() + timedelta(days=followup_days)
        _CASES[case_id] = {
            "case_id": case_id,
            "crop": crop,
            "original_class": disease_class,
            "created_at": date.today().isoformat(),
            "followup_due": due_date.isoformat(),
            "status": "awaiting_followup",
            "followup_result": None,
        }
        return _CASES[case_id]

    def get_case(case_id: str):
        return _CASES.get(case_id)

    def submit_followup_photo(case_id: str, image_bytes: bytes):
        case = _CASES.get(case_id)
        if case is None:
            return None

        predictions = classify_image(image_bytes, top_k=1)
        top = predictions[0]

        if is_healthy(top["class_name"]):
            verdict = "improved"
            message = "재사진 분석 결과 건강한 상태로 확인되었습니다. 방제가 효과가 있었습니다."
        elif top["class_name"] == case["original_class"]:
            verdict = "not_improved"
            message = "재사진에서도 동일한 병징이 남아 있습니다. 재방제 또는 원인 재진단이 필요합니다."
        else:
            verdict = "changed"
            message = f"이전과 다른 소견({top['class_name']})이 감지되었습니다. 재진단을 권장합니다."

        case["status"] = "completed"
        case["followup_result"] = {
            "verdict": verdict,
            "message": message,
            "new_prediction": top,
        }
        return case
