"""
Module gọi YesScale VEO API để sinh video dựa trên prompt và hai frame tham chiếu.
"""

import base64
import mimetypes
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

import dotenv
import requests

dotenv.load_dotenv()

BASE_URL = os.getenv("YESCALE_VIDEO_BASE_URL", "https://api.yescale.io")
SUBMIT_ENDPOINT = f"{BASE_URL}/veo/generations"
FETCH_ENDPOINT_TEMPLATE = f"{BASE_URL}/veo/generations/{{task_id}}"
API_KEY = os.getenv("YESCALE_VIDEO_API_KEY")


class YesScaleVideoError(RuntimeError):
    """Ngoại lệ chung cho quá trình sinh video với YesScale."""


def _build_headers(api_key: Optional[str]) -> Dict[str, str]:
    if not api_key:
        raise YesScaleVideoError("Thiếu YESCALE_VIDEO_API_KEY.")
    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _prepare_image_input(image_path: Optional[str]) -> Optional[str]:
    if not image_path:
        return None
    lowered = image_path.lower()
    if lowered.startswith(("http://", "https://", "data:")):
        return image_path

    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"Không tìm thấy ảnh: {image_path}")

    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def _extract_task_id(payload: Any) -> Optional[str]:
    if isinstance(payload, dict):
        candidates = [
            payload.get("task_id"),
            payload.get("id"),
            payload.get("data"),
        ]
        for candidate in candidates:
            if isinstance(candidate, (str, int)):
                return str(candidate)
            if isinstance(candidate, dict):
                nested = _extract_task_id(candidate)
                if nested:
                    return nested
        for value in payload.values():
            nested = _extract_task_id(value)
            if nested:
                return nested
    elif isinstance(payload, list):
        for item in payload:
            nested = _extract_task_id(item)
            if nested:
                return nested
    return None


def _find_video_url(payload: Any) -> Optional[str]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in {"video_url", "url", "download_url", "output_url"} and isinstance(
                value, str
            ):
                return value
            result = _find_video_url(value)
            if result:
                return result
    elif isinstance(payload, list):
        for item in payload:
            result = _find_video_url(item)
            if result:
                return result
    return None


def _download_video(video_url: str, output_path: str, session: requests.Session) -> str:
    target = Path(output_path)
    if not target.suffix:
        target = target.with_suffix(".mp4")
    target.parent.mkdir(parents=True, exist_ok=True)

    with session.get(video_url, stream=True, timeout=180) as response:
        response.raise_for_status()
        with target.open("wb") as video_file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    video_file.write(chunk)
    return str(target.resolve())


def generate_yescale_video(
    prompt: str,
    output_path: str,
    first_image: Optional[str] = None,
    last_image: Optional[str] = None,
    *,
    model: str = "veo2-fast-frames",
    enhance_prompt: bool = True,
    poll_interval: int = 5,
    timeout: int = 600,
) -> str:
    """
    Sinh video bằng YesScale VEO API và lưu file về output_path.

    Args:
        prompt: Nội dung mô tả chuyển động.
        first_image: (Tuỳ chọn) ảnh khởi đầu, chấp nhận URL hoặc file cục bộ.
        last_image: (Tuỳ chọn) ảnh kết thúc.
        output_path: Đường dẫn file đầu ra (.mp4 hoặc không đuôi).
        model: Tên model VEO.
        enhance_prompt: Cho phép API tự tối ưu prompt.
        poll_interval: Khoảng chờ giữa các lần kiểm tra task (giây).
        timeout: Tổng thời gian chờ tối đa (giây).

    Returns:
        Đường dẫn tuyệt đối đến file video đã tải.
    """
    if not prompt or not prompt.strip():
        raise ValueError("Prompt không được để trống.")

    headers = _build_headers(API_KEY)
    session = requests.Session()
    payload: Dict[str, Any] = {
        "prompt": prompt.strip(),
        "model": model,
        "enhance_prompt": enhance_prompt,
        "aspect_ratio": "16:9",
    }
    images = [
        image
        for image in (
            _prepare_image_input(first_image),
            _prepare_image_input(last_image),
        )
        if image
    ]
    if images:
        payload["images"] = images

    submit_response = session.post(
        SUBMIT_ENDPOINT, headers=headers, json=payload, timeout=30
    )
    submit_response.raise_for_status()
    submit_json = submit_response.json()
    task_id = _extract_task_id(submit_json)

    if not task_id:
        raise YesScaleVideoError("Không nhận được task_id từ YesScale.")

    poll_url = FETCH_ENDPOINT_TEMPLATE.format(task_id=task_id)
    start_time = time.time()

    while True:
        fetch_response = session.get(poll_url, headers=headers, timeout=30)
        fetch_response.raise_for_status()
        fetch_json = fetch_response.json()
        data_block = fetch_json.get("data") or fetch_json
        status = (data_block.get("status") or fetch_json.get("status") or "").lower()

        if status in {"completed", "success", "succeeded"}:
            video_url = (
                _find_video_url(data_block)
                or _find_video_url(fetch_json)
            )
            if not video_url:
                raise YesScaleVideoError("Không tìm thấy video_url trong phản hồi.")
            return _download_video(video_url, output_path, session)

        if status in {"failed", "error"}:
            reason = (
                data_block.get("message")
                or fetch_json.get("error")
                or "Không rõ lý do."
            )
            raise YesScaleVideoError(f"Sinh video thất bại: {reason}")

        if timeout and (time.time() - start_time) > timeout:
            raise TimeoutError("Hết thời gian chờ kết quả sinh video.")

        time.sleep(poll_interval)


#generate_yescale_video(prompt = "Chú mèo máy doraemon chào các bạn nhỏ", output_path = "test.mp4", first_image = "1.jpg")