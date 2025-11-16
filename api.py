from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
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
    os.makedirs("outputs/music", exist_ok=True)


ensure_output_dirs()

app = FastAPI(title="Educational Music Pipeline API")

# Serve static files to access generated outputs via /static/...
app.mount("/static", StaticFiles(directory="outputs"), name="static")


@app.get("/health")
def healthcheck():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def playground():
    return """
<!DOCTYPE html>
<html lang="vi">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Educational Music Pipeline Playground</title>
    <style>
      :root {
        font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        background: #f5f5f5;
        color: #1d1d1f;
      }
      body {
        margin: 0;
        padding: 32px 16px;
        display: flex;
        justify-content: center;
      }
      .card {
        background: #fff;
        border-radius: 16px;
        box-shadow: 0 24px 60px rgba(15, 23, 42, 0.15);
        padding: 32px;
        width: min(720px, 100%);
        display: flex;
        flex-direction: column;
        gap: 20px;
      }
      h1 {
        font-size: 24px;
        margin: 0;
      }
      p {
        margin: 0;
        color: #475467;
      }
      label {
        font-weight: 600;
        margin-bottom: 6px;
        display: inline-block;
      }
      input,
      textarea,
      select {
        border: 1px solid #d0d5dd;
        border-radius: 10px;
        padding: 10px 12px;
        width: 100%;
        font-size: 15px;
        font-family: inherit;
        box-sizing: border-box;
      }
      textarea {
        min-height: 140px;
        resize: vertical;
      }
      .field {
        display: flex;
        flex-direction: column;
        gap: 6px;
      }
      button {
        background: #2563eb;
        color: #fff;
        border: none;
        border-radius: 999px;
        padding: 12px 22px;
        font-size: 16px;
        font-weight: 600;
        cursor: pointer;
        transition: transform 0.2s ease;
      }
      button:disabled {
        opacity: 0.6;
        cursor: not-allowed;
      }
      button:not(:disabled):hover {
        transform: translateY(-1px);
      }
      #status {
        min-height: 24px;
        color: #334155;
      }
      .result {
        border: 1px solid #ecf0f4;
        background: #fafdff;
        border-radius: 12px;
        padding: 16px;
      }
      .result a {
        color: #2563eb;
        font-weight: 600;
        word-break: break-all;
      }
    </style>
  </head>
  <body>
    <main class="card">
      <div>
        <h1>Test API tạo video giáo dục</h1>
        <p>Nhập nội dung mô tả, chọn ngôn ngữ và (tuỳ chọn) tải lên ảnh tham chiếu.</p>
      </div>
      <form id="generate-form">
        <div class="field">
          <label for="summary">Tóm tắt nội dung</label>
          <textarea id="summary" name="summary" placeholder="Ví dụ: Bài hát dạy trẻ em thuộc bảng chữ cái..." required></textarea>
        </div>
        <div class="field">
          <label for="language">Ngôn ngữ</label>
          <select id="language" name="language" required>
            <option value="vi" selected>Tiếng Việt</option>
            <option value="en">Tiếng Anh</option>
            <option value="es">Tiếng Tây Ban Nha</option>
          </select>
        </div>
        <div class="field">
          <label for="image">Ảnh tham chiếu (tuỳ chọn)</label>
          <input id="image" name="image" type="file" accept="image/*" />
        </div>
        <button type="submit">Sinh video</button>
      </form>
      <div id="status"></div>
      <section id="result" class="result" hidden>
        <strong>Video đã tạo:</strong>
        <p>
          <a id="video-link" href="#" target="_blank" rel="noopener noreferrer" download="generated-video.mp4">
            Đang tải...
          </a>
        </p>
        <button id="copy-btn" type="button">Copy URL</button>
      </section>
    </main>
    <script>
      const form = document.getElementById("generate-form");
      const statusBox = document.getElementById("status");
      const resultBox = document.getElementById("result");
      const linkEl = document.getElementById("video-link");
      const copyBtn = document.getElementById("copy-btn");

      const setStatus = (message, isError = false) => {
        statusBox.textContent = message;
        statusBox.style.color = isError ? "#dc2626" : "#334155";
      };

      const triggerDownload = async (url) => {
        try {
          setStatus("⬇️ Đang tải video xuống máy...");
          const absoluteUrl = new URL(url, window.location.origin).toString();
          const response = await fetch(absoluteUrl);
          if (!response.ok) {
            throw new Error("Không thể tải file video.");
          }
          const blob = await response.blob();
          const objectUrl = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = objectUrl;
          a.download = `educational-video-${Date.now()}.mp4`;
          document.body.appendChild(a);
          a.click();
          a.remove();
          URL.revokeObjectURL(objectUrl);
          setStatus("✅ Video đã được tải về máy.");
        } catch (error) {
          console.error(error);
          setStatus("Tạo video xong nhưng không tải được tự động. Vui lòng dùng link bên dưới.", true);
        }
      };

      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const formData = new FormData(form);
        form.querySelector("button[type='submit']").disabled = true;
        setStatus("⏳ Đang gửi yêu cầu...");
        resultBox.hidden = true;

        try {
          const response = await fetch("/api/generate", {
            method: "POST",
            body: formData,
          });

          const payload = await response.json().catch(() => ({}));
          if (!response.ok || !payload.ok) {
            const detail = payload.detail || payload.message || "Không rõ nguyên nhân.";
            throw new Error(detail);
          }

          const videoUrl = payload.video_url;
          linkEl.href = videoUrl;
          linkEl.textContent = `${window.location.origin}${videoUrl}`;
          resultBox.hidden = false;
          setStatus("✅ Tạo video thành công!");
          triggerDownload(videoUrl);
        } catch (error) {
          console.error(error);
          setStatus(`❌ Lỗi: ${error.message}`, true);
        } finally {
          form.querySelector("button[type='submit']").disabled = false;
        }
      });

      copyBtn.addEventListener("click", async () => {
        if (linkEl.href === "#") {
          setStatus("Chưa có URL để copy.", true);
          return;
        }
        try {
          await navigator.clipboard.writeText(linkEl.href);
          setStatus("📋 Đã copy URL video.");
        } catch {
          setStatus("Không thể copy URL, vui lòng copy thủ công.", true);
        }
      });
    </script>
  </body>
</html>
    """


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

