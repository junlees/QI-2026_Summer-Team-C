"""모델 엔드포인트(Vertex AI 등) REST 호출.

URL과 인증 토큰을 환경변수로 받아 호출한다:
- MODEL_ENDPOINT_URL: predict 엔드포인트 전체 URL
  (예: https://us-central1-aiplatform.googleapis.com/v1/projects/<project>/locations/us-central1/endpoints/<endpoint_id>:predict)
- MODEL_ENDPOINT_AUTH_TOKEN: Authorization: Bearer 헤더에 실릴 토큰
  (Vertex AI는 `gcloud auth print-access-token`으로 얻은 단기 액세스 토큰을 사용)
- MODEL_ENDPOINT_TIMEOUT_SECONDS: 응답 대기 제한 시간(기본 30초)

app/classifier.py의 classify_image()와 동일한 반환 형식
([{"class_name", "confidence"}, ...])을 유지해서 그대로 교체해 쓸 수 있다.
"""
import base64
import os

import requests

MODEL_ENDPOINT_URL = os.environ.get("MODEL_ENDPOINT_URL")
MODEL_ENDPOINT_AUTH_TOKEN = os.environ.get("MODEL_ENDPOINT_AUTH_TOKEN")
MODEL_ENDPOINT_TIMEOUT_SECONDS = float(os.environ.get("MODEL_ENDPOINT_TIMEOUT_SECONDS", "30"))


class ModelEndpointError(Exception):
    """모델 엔드포인트 호출이 실패했을 때(네트워크 오류, 4xx/5xx 응답 등)."""


class ModelEndpointTimeout(ModelEndpointError):
    """모델 엔드포인트가 제한 시간 내에 응답하지 않았을 때."""


def classify_image_vertex(image_bytes: bytes, top_k: int = 3):
    if not MODEL_ENDPOINT_URL:
        raise ModelEndpointError("MODEL_ENDPOINT_URL 환경변수가 설정되지 않았습니다.")

    encoded_content = base64.b64encode(image_bytes).decode("utf-8")
    payload = {
        "instances": [{"content": encoded_content}],
        "parameters": {"confidenceThreshold": 0.0, "maxPredictions": top_k},
    }
    headers = {"Content-Type": "application/json"}
    if MODEL_ENDPOINT_AUTH_TOKEN:
        headers["Authorization"] = f"Bearer {MODEL_ENDPOINT_AUTH_TOKEN}"

    try:
        response = requests.post(
            MODEL_ENDPOINT_URL,
            json=payload,
            headers=headers,
            timeout=MODEL_ENDPOINT_TIMEOUT_SECONDS,
        )
    except requests.exceptions.Timeout:
        raise ModelEndpointTimeout(
            f"모델 엔드포인트가 {MODEL_ENDPOINT_TIMEOUT_SECONDS:.0f}초 내에 응답하지 않았습니다."
        )
    except requests.exceptions.RequestException as e:
        raise ModelEndpointError(f"모델 엔드포인트 호출 실패: {e}")

    if response.status_code != 200:
        raise ModelEndpointError(
            f"모델 엔드포인트가 오류를 반환했습니다 (status {response.status_code}): {response.text[:300]}"
        )

    data = response.json()
    results = []
    for prediction in data.get("predictions", []):
        display_names = prediction.get("displayNames", [])
        confidences = prediction.get("confidences", [])
        for name, confidence in zip(display_names, confidences):
            results.append({"class_name": name, "confidence": round(float(confidence), 4)})

    results.sort(key=lambda r: r["confidence"], reverse=True)
    return results[:top_k]
