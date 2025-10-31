import os
import argparse
import mimetypes
import struct
import time
from pathlib import Path
from typing import List, Optional, Dict, Union

from google import genai
from google.genai import types
import dotenv


dotenv.load_dotenv()

DEFAULT_TTS_MODEL = "gemini-2.5-pro-preview-tts"
DEFAULT_VOICE = "Zephyr"


def _get_client(api_key: Optional[str] = None) -> genai.Client:
    return genai.Client(api_key=api_key or os.getenv("GEMINI_API_KEY"))


def save_binary_file(file_path: str, data: bytes) -> str:
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "wb") as f:
        f.write(data)
    print(f"Đã lưu file: {file_path}")
    return file_path


def parse_audio_mime_type(mime_type: str) -> Dict[str, Optional[int]]:
    bits_per_sample = 16
    rate = 24000
    parts = mime_type.split(";")
    for param in parts:
        param = param.strip()
        if param.lower().startswith("rate="):
            try:
                rate = int(param.split("=", 1)[1])
            except Exception:
                pass
        elif param.startswith("audio/L"):
            try:
                bits_per_sample = int(param.split("L", 1)[1])
            except Exception:
                pass
    return {"bits_per_sample": bits_per_sample, "rate": rate}


def convert_to_wav(audio_data: bytes, mime_type: str) -> bytes:
    params = parse_audio_mime_type(mime_type)
    bits_per_sample = int(params["bits_per_sample"] or 16)
    sample_rate = int(params["rate"] or 24000)
    num_channels = 1
    data_size = len(audio_data)
    bytes_per_sample = bits_per_sample // 8
    block_align = num_channels * bytes_per_sample
    byte_rate = sample_rate * block_align
    chunk_size = 36 + data_size

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        chunk_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )
    return header + audio_data


def generate_tts(
    text: str,
    *,
    voice_name: str = DEFAULT_VOICE,
    model: str = DEFAULT_TTS_MODEL,
    output_prefix: str = "tts_output",
    output_dir: str = "outputs/audio",
    api_key: Optional[str] = None,
) -> List[str]:
    """Sinh audio từ văn bản bằng Google GenAI TTS (streaming).

    Trả về danh sách đường dẫn các file đã lưu (mỗi chunk một file).
    """
    client = _get_client(api_key)

    contents = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=text)],
        )
    ]

    config = types.GenerateContentConfig(
        temperature=1,
        response_modalities=["audio"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
            )
        ),
    )

    saved_paths: List[str] = []
    file_index = 0

    max_attempts = 3
    attempt = 1
    while attempt <= max_attempts:
        try:
            for chunk in client.models.generate_content_stream(
                model=model,
                contents=contents,
                config=config,
            ):
                if (
                    not chunk.candidates
                    or not chunk.candidates[0].content
                    or not chunk.candidates[0].content.parts
                ):
                    continue

                part = chunk.candidates[0].content.parts[0]

                if getattr(part, "inline_data", None) and part.inline_data.data:
                    inline_data = part.inline_data
                    data_buffer: Union[bytes, bytearray] = inline_data.data
                    file_ext = mimetypes.guess_extension(inline_data.mime_type) or ".wav"

                    if file_ext == ".wav":
                        # Khi không đoán được đuôi, ép sang WAV bằng header PCM
                        data_buffer = convert_to_wav(bytes(data_buffer), inline_data.mime_type)

                    filename = f"{output_prefix}_{file_index}{file_ext}"
                    file_index += 1
                    full_path = str(Path(output_dir) / filename)
                    save_binary_file(full_path, bytes(data_buffer))
                    saved_paths.append(full_path)
                else:
                    # Một số chunk có thể chứa text (log/thông tin) – in ra để debug
                    if getattr(chunk, "text", None):
                        print(chunk.text)

            break  # thành công, thoát vòng lặp retry
        except Exception as exc:
            if attempt < max_attempts:
                wait_seconds = 2 ** (attempt - 1)
                print(
                    f"Xảy ra lỗi khi tạo TTS: {exc}. Thử lại ({attempt}/{max_attempts}) sau {wait_seconds}s..."
                )
                try:
                    time.sleep(wait_seconds)
                except Exception:
                    pass
                attempt += 1
                continue
            print(f"Tạo TTS thất bại sau {max_attempts} lần thử.\nLỗi cuối: {exc}")
            raise

    return saved_paths


# generate_tts(text = "Chào bạn, hôm nay bạn thế nào?")

