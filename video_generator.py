import os
import time
import argparse
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from google import genai
from google.genai import types
import dotenv

dotenv.load_dotenv()

DEFAULT_MODEL = "veo-2.0-generate-001" #veo-3.0-fast-generate-001


def _get_client(api_key: Optional[str] = None) -> genai.Client:
    """Khởi tạo Gemini client (v1beta)."""
    return genai.Client(
        http_options={"api_version": "v1beta"},
        api_key=api_key or os.getenv("GEMINI_API_KEY"),
    )


def _build_video_config(
    aspect_ratio: str = "16:9",
    number_of_videos: int = 1,
    duration_seconds: int = 8,
    person_generation: str = "allow_adult",
) -> types.GenerateVideosConfig:
    """Tạo cấu hình sinh video cho VEO."""
    return types.GenerateVideosConfig(
        aspect_ratio=aspect_ratio,
        number_of_videos=number_of_videos,
        duration_seconds=duration_seconds,
    )


def generate_videos(
    prompt: str,
    output_dir: str = "outputs/videos",
    *,
    images_path: str = None,
    model: str = DEFAULT_MODEL,
    poll_interval_sec: int = 10,
    aspect_ratio: str = "16:9",
    number_of_videos: int = 1,
    duration_seconds: int = 8,
    person_generation: str = "allow_all",
    api_key: Optional[str] = None,
    max_retries: int = 3,
) -> List[str]:
    """
    Sinh video bằng Google GenAI VEO từ `prompt` và lưu file MP4.

    Returns: Danh sách đường dẫn video đã lưu.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    if images_path:
        image_bytes = open(images_path, "rb").read()
    client = _get_client(api_key)

    video_config = _build_video_config(
        aspect_ratio=aspect_ratio,
        number_of_videos=number_of_videos,
        duration_seconds=duration_seconds,
        person_generation=person_generation,
    )
    last_error: Optional[Exception] = None
    for attempt_index in range(1, max_retries + 1):
        try:
            operation = client.models.generate_videos(
                model=model,
                prompt=prompt,
                config=video_config,
                image=types.Image(image_bytes=image_bytes, mime_type="image/png") if images_path else None,
            )

            while not operation.done:
                print("Video chưa sẵn sàng. Kiểm tra lại sau...")
                time.sleep(poll_interval_sec)
                operation = client.operations.get(operation)

            result = operation.result
            if not result:
                raise RuntimeError("Không nhận được kết quả sinh video")

            generated_videos = result.generated_videos or []
            if not generated_videos:
                raise RuntimeError("Không có video nào được sinh ra")

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            saved_paths: List[str] = []

            for index, generated_video in enumerate(generated_videos):
                client.files.download(file=generated_video.video)
                filename = f"veo_{timestamp}_{index}.mp4"
                save_path = str(Path(output_dir) / filename)
                generated_video.video.save(save_path)
                print(f"Đã tải video về: {save_path}")
                saved_paths.append(save_path)

            return saved_paths
        except Exception as error:
            last_error = error
            if attempt_index < max_retries:
                print(
                    f"Sinh video thất bại (lần {attempt_index}/{max_retries}). Sẽ thử lại sau..."
                )
                time.sleep(max(1, poll_interval_sec))
            else:
                break

    return None


#generate_videos(prompt = "a cute creature with snow leopard-like fur is walking in a winter forest.", images_path = "2.jpg")