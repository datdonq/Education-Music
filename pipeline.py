import argparse
from typing import Dict, List, Optional
import json
from call_llm import LLMContentGenerator
from video_generator import generate_videos
from image_generator import generate_images
from tts_generator import generate_tts
from video_editor import merge_audio_to_video, concat_videos, extract_last_frame_to_image_cv2
SCRIPT_PROMPT = f"""
Bạn là nhà viết kịch bản cho các video học tập cho trẻ em
Bạn sẽ nhận được:  
1. Sơ lược về kịch bản
2. Ngôn ngữ của video
3. Hình ảnh nhân vật chính
# Lưu ý: 
- Phải có mở đầu giới thiệu và kết thúc chào tạm biệt
- Nhân vật chính phải luôn xuất hiện trong mọi frame của video
- Hạn chế chữ xuất hiện trên video 
- Không cần mô tả chi tiết nhân vật chính
- Prompt video phải được viết bằng tiếng Anh, chỉ giữ lại các script bằng ngôn ngữ của video
- Độ dài của mỗi scene là 8 giây, vì vậy script phải được viết sao cho phù hợp với độ dài của scene không dài hơn cũng không ngắn hơn
Output format must be JSON: 
{{
    "scence_script":[
    {{
        "script": Script lời thoại của cảnh này
        "prompt_image": Prompt chi tiết về frame đầu tiên của cảnh này
        "prompt_video": Prompt chi tiết để tạo video cho cảnh này bao (không gồm cả script và âm thanh của cảnh này)
    }},
    ... 
    ],
    "music_prompt": Prompt chi tiết để tạo bài hát cho video
}}
"""
SCRIPT_PROMPT_veo3= f"""
Bạn là nhà viết kịch bản cho các video học tập cho trẻ em
Bạn sẽ nhận được:  
1. Sơ lược về kịch bản
2. Ngôn ngữ của video
3. Hình ảnh nhân vật chính
# Lưu ý: 
- Nhân vật chính phải luôn xuất hiện trong video
- Hạn chế chữ xuất hiện trên video 
- Không cần mô tả chi tiết nhân vật chính
- Prompt video phải được viết bằng tiếng Anh, chỉ giữ lại các script bằng ngôn ngữ của video
- Độ dài của mỗi scene là 8 giây, vì vậy script phải được viết sao cho phù hợp với độ dài của scene không dài hơn cũng không ngắn hơn
Output format must be JSON: 
{{
    "scence_script":[
    {{
        "prompt_image": Prompt chi tiết về frame đầu tiên của cảnh này
        "prompt_video": Prompt chi tiết để tạo video cho cảnh này bao (gồm cả script và âm thanh của cảnh này)
    }},
    ... 
    ],
    "music_prompt": Prompt chi tiết để tạo bài hát cho video
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
        images = generate_images(prompt = prompt_image + ", Use image reference ", images_path = images_path)
        script = scene["script"]
        audio_path = generate_tts(text = script)
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
pipeline(summary = "Video học tập 4 chữ cái A, B, C, D cho trẻ em", language = "Tiếng Việt", images_path = "1.jpg")