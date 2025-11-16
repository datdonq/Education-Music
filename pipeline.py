import argparse
from typing import Dict, List, Optional
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from gemini_service.call_llm import LLMContentGenerator
from gemini_service.video_generator import generate_videos
from yescale_service.yescale_video_gen import generate_yescale_video
from gemini_service.image_generator import generate_images
from gemini_service.tts_generator import generate_tts
from utils.video_editor import merge_audio_to_video, concat_videos, burn_subtitle_text, add_background_audio_to_video
from utils.prompt import SCRIPT_PROMPT, SCRIPT_PROMPT_VEO3
import uuid
from yescale_service.music_generator import generate_music
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
                "model": "gemini-2.5-flash",
                "retry": 3,
                "temperature": 1.5,
                "top_k": 40,
                "top_p": 0.95,
                "thinking_budget": 10000,
            }
        ],
        json=True,
    )
    return response
def pipeline(summary: str, language: str, images_path: str = None) -> Dict:
    """
    Pipeline sinh kịch bản cho video học tập cho trẻ em
    """
    try:
        output_path = f"outputs/videos/{uuid.uuid4()}.mp4"
        script = generate_script(summary = summary, language = language, images_path = images_path)
        scenes = script["scence_script"]
        music_prompt = script["music_prompt"]
        num_scenes = len(scenes)
        video_paths_by_index: List[Optional[str]] = [None] * num_scenes

        def process_scene(scene_index: int, scene_item: Dict) -> (int, str):
            prompt_image = scene_item["prompt_image"]
            prompt_video = scene_item["prompt_video"]
            images = generate_images(
                prompt=prompt_image + ", Use image reference, must not change the image style or character clothes ",
                images_path=images_path,
                output_path=f"outputs/images/image_{scene_index}.png",
            )
            scene_script = scene_item["script"]
            video_path = f"outputs/videos/{uuid.uuid4()}.mp4"
            audio_path = generate_tts(
                text=scene_script, output_path=f"outputs/audio/tts_output_{scene_index}.wav"
            )
            generate_yescale_video(
                prompt=prompt_video + ", Use image reference ", first_image=images[0], output_path=video_path
            )
            
            merged_path = video_path.replace(".mp4", "_audio.mp4")
            merge_audio_to_video(video_path=video_path, audio_path=audio_path[0], output_path=merged_path)
            subtitled_video = burn_subtitle_text(video_path = merged_path, text = scenes[scene_index]["main_content"], output_path = video_path.replace(".mp4", "_sub.mp4"), position = "bottom", margin_y = 80, font_name = "DejaVu Sans", font_size = 20, box_opacity = 0.0)
            return scene_index, subtitled_video

        # Chạy song song từng scene với số worker giới hạn để tránh quá tải GPU/CPU
        max_workers = 6
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(process_scene, idx, scene) for idx, scene in enumerate(scenes)]
            for future in as_completed(futures):
                scene_idx, merged_video_path = future.result()
                video_paths_by_index[scene_idx] = merged_video_path

        # Đảm bảo giữ nguyên thứ tự cảnh khi nối video
        video_paths = [path for path in video_paths_by_index if path is not None]
        concat_videos(video_paths = video_paths, output_path = output_path)
        
        # Generate background music
        background_music_path = f"outputs/music/background_{uuid.uuid4()}.mp3"
        generate_music(prompt = music_prompt, output_path = background_music_path, timeout = 180)
        add_background_audio_to_video(video_path = output_path, bg_audio_path = background_music_path, output_path = output_path.replace(".mp4", "_final.mp4"))
        return output_path.replace(".mp4", "_final.mp4")
    except Exception as e:
        print(f"Error: {e}")
        return None

if __name__ == "__main__":
    pipeline(summary = "Video học tập 4 chữ cái A, B, C, D cho trẻ em", language = "Tiếng Việt", images_path = "2.jpg")