"""이미지 분류 진입점.

MODEL_ENDPOINT_URL이 설정되어 있으면 원격 모델 엔드포인트(app/vertex_classifier.py)를
쓰고, 없으면 로컬 모델(app/classifier.py)로 폴백한다.
"""
from app.classifier import classify_image as _classify_image_local
from app.vertex_classifier import MODEL_ENDPOINT_URL, classify_image_vertex

# main.py에서 예외를 구분해 HTTP 상태 코드로 매핑할 수 있도록 재노출한다.
from app.vertex_classifier import ModelEndpointError, ModelEndpointTimeout  # noqa: F401


def classify_image(image_bytes: bytes, top_k: int = 3):
    if MODEL_ENDPOINT_URL:
        return classify_image_vertex(image_bytes, top_k)
    return _classify_image_local(image_bytes, top_k)
