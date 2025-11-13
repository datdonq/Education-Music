from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from typing import Optional
import os
import uuid
import shutil

from pipeline import pipeline as run_pipeline


def ensure_output_dirs() -> None:
    os.makedirs("outputs/videos", exist_ok=True)
    os.makedirs("outputs/images", exist_ok=True)
    os.makedirs("outputs/audio", exist_ok=True)
    os.makedirs("outputs/uploads", exist_ok=True)


ensure_output_dirs()

app = FastAPI(title="Educational Music Pipeline API")

# Serve static files to access generated outputs via /static/...
app.mount("/static", StaticFiles(directory="outputs"), name="static")


@app.get("/health")
def healthcheck():
    return {"status": "ok"}


@app.post("/api/generate")
async def generate_video(
    summary: str = Form(...),
    language: str = Form(...),
    image: Optional[UploadFile] = File(None),
):
    """
    Sinh video học tập cho trẻ em từ 'summary', 'language' và (tùy chọn) ảnh tham chiếu upload.
    Trả về đường dẫn file và URL tĩnh để tải/xem.
    """
    ensure_output_dirs()

    image_path: Optional[str] = None
    if image is not None:
        # Lưu ảnh upload vào outputs/uploads
        try:
            file_ext = os.path.splitext(image.filename or "")[1] or ".png"
            upload_name = f"{uuid.uuid4()}{file_ext}"
            image_path = os.path.join("outputs", "uploads", upload_name)
            with open(image_path, "wb") as f:
                shutil.copyfileobj(image.file, f)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Lỗi lưu ảnh upload: {e}")

    try:
        output_path = run_pipeline(summary=summary, language=language, images_path=image_path)
        if not output_path or not os.path.exists(output_path):
            raise HTTPException(status_code=500, detail="Pipeline không trả về video hợp lệ.")
        # Chuẩn bị URL tĩnh
        rel_path = os.path.relpath(output_path, "outputs")
        video_url = f"/static/{rel_path}"
        return JSONResponse(
            {
                "ok": True,
                "video_path": output_path,
                "video_url": video_url,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi chạy pipeline: {e}")


# Chạy: uvicorn api:app --host 0.0.0.0 --port 8000

