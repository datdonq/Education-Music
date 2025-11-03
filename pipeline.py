import argparse
from typing import Dict, List, Optional
import json
from call_llm import LLMContentGenerator
from video_generator import generate_videos
from image_generator import generate_images
from tts_generator import generate_tts
from video_editor import merge_audio_to_video, concat_videos, extract_last_frame_to_image_cv2, burn_subtitle_text
SCRIPT_PROMPT = """
Bạn là nhà viết kịch bản cho các video học tập cho trẻ em.

Bạn sẽ nhận được:
1) Sơ lược về kịch bản
2) Ngôn ngữ của video
3) Hình ảnh nhân vật chính (ảnh tham chiếu) — luôn dùng ảnh này để giữ nhất quán ngoại hình nhân vật

# Yêu cầu nội dung
- Nội dung đúng ngôn ngữ được chỉ định (toàn bộ phần "script" phải dùng đúng ngôn ngữ đó).
- Ngắn gọn, dễ hiểu, phù hợp lứa tuổi thiếu nhi; tránh khái niệm trừu tượng/nhạy cảm.
- Cấu trúc logic, có mở đầu giới thiệu và kết thúc chào tạm biệt.
- Mỗi cảnh (scene) có độ dài 8 giây; kịch bản lời thoại cần khớp thời lượng 8 giây (không dài/không ngắn hơn cảm nhận).
- Nhân vật chính xuất hiện trong mọi cảnh và luôn khớp với ảnh tham chiếu (màu sắc, dáng vẻ, trang phục tổng quát).
- Tránh chữ/biển hiệu trong khung hình; không chèn text overlay.
- Không cần mô tả chi tiết vi mô của nhân vật; chỉ mô tả đủ để AI giữ nhất quán theo ảnh tham chiếu.
- Tránh thương hiệu, bản quyền, bạo lực, người lớn, hoặc nội dung gây sợ hãi.

# Yêu cầu thị giác và chuyển động (cho hệ sinh video)
- prompt_image: mô tả khung hình đầu của cảnh (bằng tiếng Anh), rõ ràng, không chứa hội thoại.
- prompt_video: mô tả chuyển động/video (bằng tiếng Anh), không chứa hội thoại/âm thanh; dùng thì hiện tại tiếp diễn, mô tả 1-2 hành động mượt, camera đơn giản (ví dụ: slight pan/slow zoom), ánh sáng rõ, màu sắc tươi sáng cho thiếu nhi.
- Không yêu cầu text xuất hiện trong cảnh; giữ hậu cảnh gọn gàng, phù hợp chủ đề học tập.
- Tỉ lệ khung hình 16:9, phong cách hoạt hình/đáng yêu phù hợp trẻ em.

# Yêu cầu cho phụ đề học tập
- main_content: một câu ngắn (≤ 80 ký tự), tóm ý học tập chính của cảnh, không emoji, không ký tự đặc biệt, không dấu ngoặc kép.

# Định dạng đầu ra
- Trả về JSON THUẦN (không markdown, không giải thích, không bình luận).
- JSON phải hợp lệ, không thừa dấu phẩy, không thêm trường ngoài yêu cầu trừ khi thực sự cần thiết.

Output JSON schema:
{{
  "scence_script": [
    {
      "script": "Lời thoại của cảnh, đúng ngôn ngữ video, độ dài phù hợp ~8s",
      "prompt_image": "English. First frame visual description. No dialogue.",
      "prompt_video": "English. Motion/camera/lighting/style for 8s. No dialogue.",
      "main_content": "Thông điệp học tập ngắn gọn (<=80 ký tự)"
    }
    // lặp cho các cảnh tiếp theo
  ],
  "music_prompt": "English. Mood, tempo (BPM), key/scale, instruments, structure to fit total duration; cheerful, kid-friendly; no vocals/lyrics."
}}
"""
def generate_script(summary: str, language: str, images_path: str = None) -> Dict:
    """
    Sinh kịch bản cho video học tập cho trẻ em
    """
    prompt = f"""
    Sơ lược về kịch bản: {summary}
    Ngôn ngữ của video: {language}
    """
    response, token_count = LLMContentGenerator().completion(
        system_prompt=SCRIPT_PROMPT,
        user_prompt=prompt,
        providers=[
            {
                "name": "gemini",
                "model": "gemini-2.5-pro",
                "retry": 3,
                "temperature": 1.5,
                "top_k": 40,
                "top_p": 0.95,
                "thinking_budget": 10000,
            }
        ],
        json=True,
        media_urls=[images_path],
    )
    return response
def pipeline(summary: str, language: str, images_path: str = None) -> Dict:
    """
    Pipeline sinh kịch bản cho video học tập cho trẻ em
    """
    script = generate_script(summary = summary, language = language, images_path = images_path)
    # Save script to json file
    last_script = script
    with open("script.json", "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False)
    scenes = script["scence_script"]
    music_prompt = script["music_prompt"]
    video_paths = []
    last_frame = None
    index = 0
    # Veo2
    for scene in scenes:
        prompt_image = scene["prompt_image"]
        prompt_video = scene["prompt_video"]
        images = generate_images(prompt = prompt_image + ", Use image reference ", images_path = images_path, output_path = f"outputs/images/image_{index}.png")
        script = scene["script"]
        audio_path = generate_tts(text = script, output_path = f"outputs/audio/tts_output_{index}.wav")
        if index == 0:
            video_path = generate_videos(prompt = prompt_video + ", Use image reference ", images_path = images[0])
        else:
            video_path = generate_videos(prompt = prompt_video + ", Use image reference ", images_path = last_frame)
        # Merge audio and video
        merge_audio_to_video(video_path = video_path[0], audio_path = audio_path[0], output_path = video_path[0].replace(".mp4", "_audio.mp4"))
        # Cut last frame from video
        last_frame = extract_last_frame_to_image_cv2(video_path = video_path[0].replace(".mp4", "_audio.mp4"), output_image_path = "outputs/images/last_frame.png")
        video_paths.append(video_path[0].replace(".mp4", "_audio.mp4"))
        index += 1

    # Veo3
    # for scene in scenes:
    #     prompt_image = scene["prompt_image"]
    #     prompt_video = scene["prompt_video"]
    #     images = generate_images(prompt = prompt_image + ", Use image reference ", images_path = images_path)
    #     video_path = generate_videos(prompt = prompt_video + ", Use image reference ", images_path = images[0])
    #     video_paths.append(video_path[0])
    concat_videos(video_paths = video_paths, output_path = "outputs/videos/final.mp4")
def pipeline_last_frame(summary: str, language: str, images_path: str = None) -> Dict:
    """
    Pipeline sinh kịch bản cho video học tập cho trẻ em
    """
    script = generate_script(summary = summary, language = language, images_path = images_path)
    # Save script to json file
    last_script = script
    with open("script.json", "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False)
    scenes = script["scence_script"]
    music_prompt = script["music_prompt"]
    video_paths = []
    first_frames_paths = []
    audio_paths = []
    video_prompts = {}
    # Veo2
    index = 0
    for scene in scenes:
        prompt_image = scene["prompt_image"]
        images = generate_images(prompt = prompt_image + ", Use image reference ", images_path = images_path, output_path = f"outputs/images/image_{index}.png")
        script = scene["script"]
        audio_path = generate_tts(text = script, output_path = f"outputs/audio/tts_output_{index}.wav")
        first_frames_paths.append(images[0])
        audio_paths.append(audio_path[0])
        video_prompts[index] = scene["prompt_video"]
        index += 1
    for index, video_prompt in video_prompts.items():
        video_path = generate_videos(prompt = video_prompt + ", Use image reference ", images_path = first_frames_paths[index], last_frame_path = first_frames_paths[index+1] if index+1 < len(first_frames_paths) else None)
        # Merge audio and video
        merged_video = merge_audio_to_video(video_path = video_path[0], audio_path = audio_paths[index], output_path = video_path[0].replace(".mp4", "_audio.mp4"))
        # Burn main_content as subtitle over the whole scene
        subtitled_video = burn_subtitle_text(video_path = merged_video, text = scenes[index]["main_content"], output_path = merged_video.replace("_audio.mp4", "_sub.mp4"), position = "bottom", margin_y = 80, font_name = "DejaVu Sans", font_size = 20, box_opacity = 0.0)
        # Cut last frame from video (after subtitle burn)
        video_paths.append(video_path[0])
    concat_videos(video_paths = video_paths, output_path = "outputs/videos/final.mp4")
pipeline(summary = "Video học tập 4 chữ cái A, B, C, D cho trẻ em", language = "Tiếng Việt", images_path = "2.jpg")