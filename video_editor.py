import os
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import Iterable, List, Optional


def _ensure_ffmpeg() -> None:
    """Đảm bảo hệ thống có sẵn lệnh ffmpeg."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "Không tìm thấy 'ffmpeg'. Hãy cài đặt ffmpeg và đảm bảo lệnh 'ffmpeg' khả dụng trong PATH."
        )


def _probe_duration_sec(video_path: str) -> float:
    """Lấy thời lượng video (giây) bằng ffprobe."""
    cmd: List[str] = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    completed = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"ffprobe thất bại khi đọc duration: {completed.stderr}")
    try:
        return float(completed.stdout.strip())
    except ValueError as exc:
        raise RuntimeError(f"Không parse được duration từ ffprobe: {completed.stdout}") from exc


def extract_last_frame_to_image_cv2(
    video_path: str,
    output_image_path: str,
    *,
    quality: Optional[int] = None,
) -> str:
    """Fallback: Trích xuất khung hình cuối bằng OpenCV (không cần gọi ffmpeg CLI)."""
    try:
        import cv2  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "OpenCV chưa được cài, không thể dùng fallback. Hãy cài 'opencv-python-headless'."
        ) from exc

    Path(Path(output_image_path).parent).mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Không mở được video bằng OpenCV: {video_path}")

    frame = None
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if frame_count > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(frame_count - 1, 0))
        ok, fr = cap.read()
        if ok:
            frame = fr

    # Fallback đọc tuần tự đến cuối nếu seek trực tiếp không thành công
    if frame is None:
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        while True:
            ok, fr = cap.read()
            if not ok:
                break
            frame = fr

    cap.release()

    if frame is None:
        raise RuntimeError("Không đọc được khung hình cuối bằng OpenCV.")

    params: List[int] = []
    out_lower = output_image_path.lower()
    if out_lower.endswith((".jpg", ".jpeg")):
        # Ánh xạ quality: nếu người dùng truyền thang ffmpeg (2..31), quy đổi sang JPEG (1..100)
        if quality is not None:
            q = int(quality)
            if 1 <= q <= 100:
                cv_q = q
            elif 2 <= q <= 31:
                # q=2 (tốt nhất) ~ 100, q=31 (tệ) ~ 10
                cv_q = max(1, min(100, int(round((31 - q) / 29 * 90 + 10))))
            else:
                cv_q = 95
            params = [int(cv2.IMWRITE_JPEG_QUALITY), cv_q]
    elif out_lower.endswith(".png"):
        # Không dùng quality của ffmpeg cho PNG; có thể đặt nén mặc định
        pass

    ok = cv2.imwrite(output_image_path, frame, params)
    if not ok:
        raise RuntimeError(f"Lưu ảnh thất bại (OpenCV): {output_image_path}")

    return output_image_path


def merge_audio_to_video(
    video_path: str,
    audio_path: str,
    output_path: str,
    *,
    audio_offset_sec: float = 0.0,
    volume: Optional[float] = None,
    reencode: bool = False,
) -> str:
    """
    Ghép audio vào video bằng ffmpeg.

    - Mặc định copy stream hình ảnh để nhanh (không tái mã hóa). Nếu cần tái mã hóa đặt reencode=True.
    - Có thể dịch audio một khoảng thời gian (audio_offset_sec) và chỉnh âm lượng (volume).
    - Kết quả sẽ cắt theo track ngắn hơn nhờ -shortest.
    """
    _ensure_ffmpeg()
    Path(Path(output_path).parent).mkdir(parents=True, exist_ok=True)

    cmd: List[str] = [
        "ffmpeg",
        "-y",
        "-i",
        video_path,
        "-i",
        audio_path,
    ]

    filter_steps: List[str] = []
    current_label = "[1:a]"  # audio input

    if audio_offset_sec and audio_offset_sec > 0:
        delay_ms = int(audio_offset_sec * 1000)
        filter_steps.append(f"{current_label}adelay={delay_ms}|{delay_ms}[a_del]")
        current_label = "[a_del]"

    if volume is not None:
        filter_steps.append(f"{current_label}volume={volume}[a_vol]")
        current_label = "[a_vol]"

    if filter_steps:
        filter_complex = ";".join(filter_steps)
        cmd += [
            "-filter_complex",
            filter_complex,
            "-map",
            "0:v:0",
            "-map",
            current_label.strip("[]"),
        ]
    else:
        cmd += ["-map", "0:v:0", "-map", "1:a:0"]

    if reencode:
        cmd += [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
        ]
    else:
        cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k"]

    cmd += ["-shortest", output_path]

    completed = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"ffmpeg merge_audio_to_video thất bại: {completed.stderr}")

    return output_path


def add_background_audio_to_video(
    video_path: str,
    bg_audio_path: str,
    output_path: str,
    *,
    bg_volume: float = 0.5,
    main_volume: Optional[float] = None,
    bg_offset_sec: float = 0.0,
    loop_bg: bool = True,
    reencode_video: bool = False,
) -> str:
    """
    Thêm nhạc nền vào audio của video đầu vào và xuất ra video mới.

    - `bg_volume`: hệ số âm lượng cho background (1.0 = 100%, mặc định 0.5 = 50%).
    - `main_volume`: nếu cung cấp, hệ số âm lượng cho audio gốc của video.
    - `bg_offset_sec`: trễ background so với audio gốc (giây, >= 0).
    - `loop_bg`: lặp background để đủ dài theo audio gốc.
    - `reencode_video`: nếu True sẽ tái mã hóa video (libx264). Mặc định copy stream hình ảnh.
    """
    _ensure_ffmpeg()
    Path(Path(output_path).parent).mkdir(parents=True, exist_ok=True)

    if bg_volume < 0:
        raise ValueError("bg_volume phải >= 0")
    if main_volume is not None and main_volume < 0:
        raise ValueError("main_volume phải >= 0 nếu cung cấp")
    if bg_offset_sec < 0:
        raise ValueError("bg_offset_sec phải >= 0")

    cmd: List[str] = [
        "ffmpeg",
        "-y",
        "-i",
        video_path,
    ]

    if loop_bg:
        cmd += ["-stream_loop", "-1"]
    cmd += ["-i", bg_audio_path]

    filter_steps: List[str] = []
    main_label = "[0:a]"
    bg_label = "[1:a]"

    current_bg = bg_label
    if bg_offset_sec and bg_offset_sec > 0:
        delay_ms = int(bg_offset_sec * 1000)
        filter_steps.append(f"{current_bg}adelay={delay_ms}|{delay_ms}[bg_del]")
        current_bg = "[bg_del]"

    if bg_volume != 1.0:
        filter_steps.append(f"{current_bg}volume={bg_volume}[bg_vol]")
        current_bg = "[bg_vol]"

    current_main = main_label
    if main_volume is not None and main_volume != 1.0:
        filter_steps.append(f"{current_main}volume={main_volume}[main_vol]")
        current_main = "[main_vol]"

    filter_steps.append(
        f"{current_main}{current_bg}amix=inputs=2:duration=first:dropout_transition=0[mix]"
    )

    filter_complex = ";".join(filter_steps)

    cmd += [
        "-filter_complex",
        filter_complex,
        "-map",
        "0:v:0",
        "-map",
        "[mix]",
    ]

    if reencode_video:
        cmd += [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
        ]
    else:
        cmd += ["-c:v", "copy"]

    cmd += ["-c:a", "aac", "-b:a", "192k"]
    cmd += ["-shortest", output_path]

    completed = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"ffmpeg add_background_audio_to_video thất bại: {completed.stderr}")

    return output_path


def concat_videos(
    video_paths: Iterable[str],
    output_path: str,
    *,
    reencode: bool = True,
) -> str:
    """
    Nối nhiều video theo thứ tự. Mặc định tái mã hóa để đảm bảo tương thích.
    - Nếu chắc chắn tất cả video cùng codec/container, có thể đặt reencode=False để dùng concat demuxer + copy streams.
    """
    _ensure_ffmpeg()
    Path(Path(output_path).parent).mkdir(parents=True, exist_ok=True)

    videos = [str(Path(p)) for p in video_paths]
    if len(videos) == 0:
        raise ValueError("Danh sách video rỗng")

    if reencode:
        # Dùng concat filter (tái mã hóa) để an toàn với codec khác nhau
        # Xây dựng chuỗi 'concat' động cho CẢ video và audio
        inputs: List[str] = ["ffmpeg", "-y"]
        for v in videos:
            inputs += ["-i", v]
        # Tạo filter concat: n=<len>
        n = len(videos)
        # Nối cả video và audio: [0:v][0:a][1:v][1:a]... concat=n=<n>:v=1:a=1 [vout][aout]
        va_labels = "".join([f"[{i}:v][{i}:a]" for i in range(n)])
        filter_str = f"{va_labels}concat=n={n}:v=1:a=1[vout][aout]"
        cmd = inputs + [
            "-filter_complex",
            filter_str,
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            output_path,
        ]
        completed = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if completed.returncode != 0:
            raise RuntimeError(f"ffmpeg concat_videos (reencode) thất bại: {completed.stderr}")
        return output_path

    # Concat demuxer (copy stream) – yêu cầu codec/container đồng nhất
    with tempfile.TemporaryDirectory() as td:
        list_file = Path(td) / "concat.txt"
        with open(list_file, "w", encoding="utf-8") as f:
            for v in videos:
                # -safe 0 cho phép absolute path
                f.write(f"file '{Path(v).as_posix()}'\n")

        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            output_path,
        ]
        completed = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if completed.returncode != 0:
            raise RuntimeError(f"ffmpeg concat_videos (copy) thất bại: {completed.stderr}")
    return output_path


def extract_last_frame_to_image(
    video_path: str,
    output_image_path: str,
    *,
    quality: Optional[int] = None,
) -> str:
    """
    Trích xuất khung hình cuối (last frame) của video thành ảnh tĩnh.

    - Dùng tìm kiếm ngược '-sseof -0.001' để lấy khung gần sát cuối (thực tế là khung cuối).
    - Nếu xuất JPEG, có thể chỉnh 'quality' (2 là tốt nhất, 31 thấp hơn). PNG bỏ qua tham số này.
    """
    # Nếu không có ffmpeg, fallback sang OpenCV ngay từ đầu
    try:
        _ensure_ffmpeg()
    except Exception:
        return extract_last_frame_to_image_cv2(
            video_path,
            output_image_path,
            quality=quality,
        )
    Path(Path(output_image_path).parent).mkdir(parents=True, exist_ok=True)

    # Cách 1: Dùng -sseof để seek từ cuối
    cmd: List[str] = [
        "ffmpeg",
        "-y",
        "-sseof",
        "-0.001",
        "-i",
        video_path,
        "-frames:v",
        "1",
    ]

    if quality is not None:
        cmd += ["-q:v", str(quality)]

    cmd.append(output_image_path)

    completed = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode == 0:
        return output_image_path

    # Cách 2 (fallback): Dùng ffprobe lấy duration rồi seek chính xác tới gần cuối
    try:
        duration = _probe_duration_sec(video_path)
    except Exception as err:
        # Fallback tiếp sang OpenCV nếu không lấy được duration/ffprobe lỗi
        try:
            return extract_last_frame_to_image_cv2(
                video_path,
                output_image_path,
                quality=quality,
            )
        except Exception as cv2_err:
            raise RuntimeError(
                f"ffmpeg -sseof thất bại và không lấy được duration: {completed.stderr}\nNguyên nhân: {err}\n"
                f"OpenCV fallback cũng thất bại: {cv2_err}"
            ) from cv2_err

    # Lùi 0.05s so với thời điểm kết thúc để tránh rơi đúng điểm EOF
    seek_pos = max(duration - 0.05, 0.0)

    cmd2: List[str] = [
        "ffmpeg",
        "-y",
        "-i",
        video_path,
        "-ss",
        f"{seek_pos:.3f}",
        "-frames:v",
        "1",
    ]
    if quality is not None:
        cmd2 += ["-q:v", str(quality)]
    cmd2.append(output_image_path)

    completed2 = subprocess.run(cmd2, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed2.returncode != 0:
        # Thử OpenCV như là bước fallback cuối
        try:
            return extract_last_frame_to_image_cv2(
                video_path,
                output_image_path,
                quality=quality,
            )
        except Exception as cv2_err:
            raise RuntimeError(
                "extract_last_frame_to_image vẫn thất bại sau mọi phương án.\n"
                f"Lỗi 1 (ffmpeg -sseof): {completed.stderr}\n"
                f"Lỗi 2 (ffmpeg -ss gần cuối): {completed2.stderr}\n"
                f"Lỗi 3 (OpenCV): {cv2_err}"
            ) from cv2_err

    return output_image_path

#concat_videos(video_paths = [f"outputs/videos/{index}.mp4" for index in range(6)], output_path = "outputs/videos/final.mp4")
#extract_last_frame_to_image_cv2(video_path = "outputs/videos/veo_20251031_020031_0_audio.mp4", output_image_path = "outputs/images/last_frame.png")

add_background_audio_to_video(video_path = "outputs/videos/veo2_2.mp4", bg_audio_path = "music.mp3", output_path = "outputs/videos/final_veo_2.mp4")