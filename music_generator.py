"""
Module hỗ trợ sinh nhạc qua YesScale Suno API.

Hàm chính `generate_music` nhận prompt và trả về đường dẫn file âm thanh
được tải về máy, tự động poll kết quả cách mỗi 5 giây.
"""

import os
import time
from pathlib import Path
from typing import Dict, List, Optional
import dotenv
import requests

dotenv.load_dotenv()

BASE_URL = "https://api.yescale.io"
API_KEY = os.getenv("YESCALE_MUSIC_API_KEY")

SUBMIT_ENDPOINT = f"{BASE_URL}/suno/submit/music"
FETCH_ENDPOINT = f"{BASE_URL}/suno/fetch"


class MusicGenerationError(RuntimeError):
    """Ngoại lệ chung cho quá trình sinh nhạc."""


def _build_headers(api_key: str) -> Dict[str, str]:
    if not api_key:
        raise MusicGenerationError("Thiếu API key cho YesScale.")
    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _download_audio(audio_url: str, output_dir: str, filename: str) -> str:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    url_name = Path(audio_url.split("?")[0]).name or filename
    suffix = Path(url_name).suffix or ".mp3"
    target_path = output_path / f"{filename}{suffix}"

    with requests.get(audio_url, stream=True, timeout=120) as response:
        response.raise_for_status()
        with target_path.open("wb") as audio_file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    audio_file.write(chunk)

    return str(target_path.resolve())


def generate_music(
    prompt: str,
    *,
    tags: str = "emotional punk",
    mv: str = "chirp-v4",
    title: Optional[str] = None,
    output_dir: str = "outputs/music",
    poll_interval: int = 5,
    timeout: int = 600,
) -> str:
    """
    Sinh nhạc dựa trên prompt và trả về đường dẫn file âm thanh tải về.

    Args:
        prompt: Nội dung mô tả bài nhạc.
        tags: Thẻ mô tả phong cách (tùy chọn).
        mv: Model version của Suno.
        title: Tiêu đề bài nhạc (nếu None sẽ dùng task_id).
        output_dir: Thư mục lưu file audio tải về.
        poll_interval: Khoảng thời gian giữa mỗi lần poll (giây).
        timeout: Tổng thời gian chờ tối đa (giây).

    Returns:
        Đường dẫn tuyệt đối tới file âm thanh đã tải về.
    """
    if not prompt or not prompt.strip():
        raise ValueError("Prompt không được rỗng.")

    headers = _build_headers(API_KEY)
    payload = {
        "prompt": prompt.strip(),
        "tags": tags,
        "mv": mv,
        "title": title or "Untitled Track",
    }

    submit_response = requests.post(
        SUBMIT_ENDPOINT, headers=headers, json=payload, timeout=30
    )
    submit_response.raise_for_status()
    task_id = submit_response.json().get("data")

    if not task_id:
        raise MusicGenerationError("Không nhận được task_id từ YesScale.")

    start_time = time.time()

    while True:
        fetch_response = requests.get(
            f"{FETCH_ENDPOINT}/{task_id}", headers=headers, timeout=30
        )
        fetch_response.raise_for_status()
        fetch_data: Dict = fetch_response.json().get("data", {})

        status = (fetch_data.get("status") or "").lower()
        outputs: List[Dict] = fetch_data.get("data") or []

        if status in {"success", "succeeded", "completed"}:
            if not outputs or not outputs[0].get("audio_url"):
                raise MusicGenerationError("Không tìm thấy audio_url trong phản hồi.")
            audio_url = outputs[0]["audio_url"]
            return _download_audio(audio_url, output_dir, filename=task_id)

        if status in {"failed", "error"}:
            reason = fetch_data.get("message") or "Không rõ lý do."
            raise MusicGenerationError(f"Sinh nhạc thất bại: {reason}")

        if timeout and (time.time() - start_time) > timeout:
            raise TimeoutError("Hết thời gian chờ kết quả sinh nhạc.")

        time.sleep(poll_interval)
        
#print(generate_music(prompt="A cheerful and kid-friendly pop song about a happy day at the beach")) 