"""
Module hỗ trợ sinh audio thông qua FAL AI Minimax TTS API.

Hàm `generate_audio` gửi request tạo audio, poll kết quả và tải file về.
"""

import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

import dotenv
import requests

dotenv.load_dotenv()

FAL_BASE_URL = os.getenv("FAL_MINIMAX_BASE_URL", "https://api.yescale.io")
SUBMIT_ENDPOINT = "http://api.yescale.io/fal-ai/minimax/speech-02-hd"
TASK_ENDPOINT_TEMPLATE = f"{FAL_BASE_URL}/task/{{task_id}}"
FAL_API_KEY = "sk-zSQ0JP6It3SicTqO6O0j6KQzLiPGND1M4SH7dmGCHjMyTeNg"
DEFAULT_VOICE_ID = os.getenv("FAL_MINIMAX_VOICE_ID", "Voice904740431752642196")


class AudioGenerationError(RuntimeError):
    """Ngoại lệ chung cho quá trình sinh audio."""


def _build_headers(api_key: str) -> Dict[str, str]:
    if not api_key:
        raise AudioGenerationError("Thiếu API key cho FAL AI.")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _extract_task_id(payload: Dict[str, Any]) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    candidates = [
        payload.get("task_id"),
        payload.get("request_id"),
        payload.get("id"),
    ]
    nested_candidates = [
        payload.get("data"),
        payload.get("response"),
        payload.get("result"),
    ]
    for candidate in candidates:
        if candidate:
            return str(candidate)
    for nested in nested_candidates:
        if isinstance(nested, dict):
            nested_id = _extract_task_id(nested)
            if nested_id:
                return nested_id
    return None


def _find_audio_url(payload: Any) -> Optional[str]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == "audio_url" and isinstance(value, str):
                return value
            result = _find_audio_url(value)
            if result:
                return result
    elif isinstance(payload, list):
        for item in payload:
            result = _find_audio_url(item)
            if result:
                return result
    return None


def _resolve_output_path(output_path: str, audio_url: str) -> Path:
    target = Path(output_path)
    if target.suffix:
        return target
    url_suffix = Path(audio_url.split("?")[0]).suffix or ".mp3"
    return target.with_suffix(url_suffix)


def _download_audio(audio_url: str, target_path: Path, session: requests.Session) -> str:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with session.get(audio_url, stream=True, timeout=120) as response:
        response.raise_for_status()
        with target_path.open("wb") as audio_file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    audio_file.write(chunk)
    return str(target_path.resolve())


def generate_audio(
    script: str,
    output_path: str,
    *,
    voice_id: Optional[str] = None,
    speed: float = 1,
    volume: float = 1,
    pitch: float = 0,
    english_normalization: bool = False,
    language_boost: str = "Vietnamese",
    poll_interval: int = 2,
    timeout: int = 180,
) -> str:
    """
    Sinh audio từ văn bản và lưu về output_path.

    Args:
        script: Nội dung cần đọc.
        output_path: Đường dẫn file đầu ra (có thể chưa có đuôi).
        voice_id: Tùy chọn voice id, mặc định dùng Voice9047...
        speed/volume/pitch: Các tham số cấu hình giọng đọc.
        english_normalization: Chuẩn hoá tiếng Anh.
        language_boost: Ưu tiên ngôn ngữ.
        poll_interval: Khoảng cách giữa các lần poll (giây).
        timeout: Tổng thời gian chờ tối đa (giây).

    Returns:
        Đường dẫn tuyệt đối tới file audio đã tải.
    """
    if not script or not script.strip():
        raise ValueError("script không được để trống.")

    session = requests.Session()
    headers = _build_headers(FAL_API_KEY)
    payload = {
        "text": script.strip(),
        "voice_setting": {
            "speed": speed,
            "vol": volume,
            "pitch": pitch,
            "english_normalization": english_normalization,
            "voice_id": "Chinese (Mandarin)_Cute_Spirit",
        },
        "language_boost": 'auto',
        "output_format": "url",
    }

    submit_response = session.post(
        SUBMIT_ENDPOINT, headers=headers, json=payload, timeout=30
    )
    submit_response.raise_for_status()
    submit_json = submit_response.json()
    task_id = _extract_task_id(submit_json)

    if not task_id:
        raise AudioGenerationError("Không nhận được task_id từ FAL AI.")

    poll_url = TASK_ENDPOINT_TEMPLATE.format(task_id=task_id)
    start_time = time.time()

    while True:
        poll_response = session.get(poll_url, headers=headers, timeout=30)
        poll_response.raise_for_status()
        poll_json = poll_response.json()

        status = (
            poll_json.get("status")
            or poll_json.get("task_status")
            or poll_json.get("state")
            or poll_json.get("task", {}).get("status")
            or ""
        ).lower()

        if status in {"completed", "succeeded", "success", "done"}:
            audio_url = (
                _find_audio_url(poll_json.get("response"))
                or _find_audio_url(poll_json.get("result"))
                or _find_audio_url(poll_json)
            )
            if not audio_url:
                raise AudioGenerationError("Không tìm thấy audio_url trong phản hồi.")
            target_path = _resolve_output_path(output_path, audio_url)
            return _download_audio(audio_url, target_path, session)

        if status in {"failed", "error"}:
            reason = (
                poll_json.get("error")
                or poll_json.get("message")
                or poll_json.get("response", {}).get("error")
                or "Không rõ lý do."
            )
            raise AudioGenerationError(f"Sinh audio thất bại: {reason}")

        if timeout and (time.time() - start_time) > timeout:
            raise TimeoutError("Hết thời gian chờ kết quả sinh audio.")

        time.sleep(poll_interval)


__all__ = ["generate_audio", "AudioGenerationError"]

generate_audio(script = "Việt nam có đẹp không", output_path = "audio.mp3")