import os
import argparse
import mimetypes
from pathlib import Path
from typing import List, Optional

from google import genai
from google.genai import types
import dotenv


dotenv.load_dotenv()

DEFAULT_IMAGE_MODEL = "gemini-2.5-flash-image"


def _get_client(api_key: Optional[str] = None) -> genai.Client:
    return genai.Client(api_key=api_key or os.getenv("GEMINI_API_KEY"))


def _save_binary(file_path: str, data: bytes) -> str:
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "wb") as f:
        f.write(data)
    print(f"Đã lưu file: {file_path}")
    return file_path


def generate_images(
    prompt: str,
    *,
    model: str = DEFAULT_IMAGE_MODEL,
    output_path: str = "outputs/images/image",
    api_key: Optional[str] = None,
    images_path: str = None,
) -> List[str]:
    """
    Sinh ảnh từ prompt bằng Google GenAI (streaming). Trả về danh sách đường dẫn ảnh đã lưu.
    """
    client = _get_client(api_key)
    if images_path:
        image_bytes = open(images_path, "rb").read()
    contents = [
        types.Part.from_bytes(
        data=image_bytes,
        mime_type='image/png',
      ),
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=prompt)],
        )
    ]

    config = types.GenerateContentConfig(
        response_modalities=["IMAGE"],
        image_config=types.ImageConfig(
            aspect_ratio="16:9",
        ),
    )

    saved_paths: List[str] = []
    file_index = 0

    for chunk in client.models.generate_content_stream(
        model=model,
        contents=contents,
        config=config,
    ):
        if (
            not getattr(chunk, "candidates", None)
            or not chunk.candidates[0].content
            or not chunk.candidates[0].content.parts
        ):
            continue

        part = chunk.candidates[0].content.parts[0]
        if getattr(part, "inline_data", None) and part.inline_data.data:
            inline_data = part.inline_data
            data_buffer = inline_data.data
            ext = mimetypes.guess_extension(inline_data.mime_type) or ".png"
            base = Path(output_path)
            dir_path = base.parent if base.name else base
            prefix = base.name or "image"
            filename = f"{prefix}_{file_index}{ext}"
            file_index += 1
            full_path = str(dir_path / filename)
            _save_binary(full_path, data_buffer)
            saved_paths.append(full_path)
        else:
            if getattr(chunk, "text", None):
                # Một số chunk trả về văn bản (mô tả/thông tin)
                print(chunk.text)

    return saved_paths


#generate_images(prompt = "A young girl playing with her toys, Use image reference ", images_path = "2.jpg")


