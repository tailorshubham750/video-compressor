import time
import threading
import os
import subprocess
from flask import Flask, render_template, request, jsonify, send_from_directory, make_response

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 1000 * 1024 * 1024  # 1000MB upload limit

UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "outputs"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

progress_status = {}
progress_lock = threading.Lock()

# ===== UTIL =====
def get_size(path):
    return round(os.path.getsize(path) / (1024 * 1024), 2)

def get_duration(input_path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration", "-of",
         "default=noprint_wrappers=1:nokey=1", input_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )
    return float(result.stdout)


# ===== CLEANUP =====
def cleanup_old_files(folder, max_age_seconds=3600):
    now = time.time()

    for filename in os.listdir(folder):
        file_path = os.path.join(folder, filename)

        if os.path.isfile(file_path):
            file_age = now - os.path.getmtime(file_path)

            if file_age > max_age_seconds:
                try:
                    os.remove(file_path)
                    print(f"Deleted old file: {filename}")
                except Exception as e:
                    print(f"Error deleting {filename}: {e}")


# ===== COMPRESS =====
def compress_video(input_path, output_path, filename, target_size_mb):
    duration = get_duration(input_path)

    target_size_bits = target_size_mb * 1024 * 1024 * 8
    total_bitrate = target_size_bits / duration

    audio_bitrate = 128000
    video_bitrate = max(50000, int(total_bitrate - audio_bitrate))

    command = [
        "ffmpeg",
        "-i", input_path,
        "-b:v", str(video_bitrate),
        "-maxrate", str(video_bitrate),
        "-bufsize", str(video_bitrate),
        "-vcodec", "libx264",
        "-preset", "medium",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-acodec", "aac",
        "-b:a", "128k",
        "-progress", "pipe:1",
        "-nostats",
        "-y",
        output_path
    ]

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    for line in process.stdout:
        if "out_time_ms" in line:
            try:
                time_ms = int(line.split("=")[1])
                current_time = time_ms / 1000000
                percent = min(100, (current_time / duration) * 100)
                with progress_lock:
                    progress_status[filename] = round(percent, 2)
            except (ValueError, IndexError):
                pass

    process.wait()


# ===== BACKGROUND PROCESS =====
def process_video(input_path, output_path, filename, target_size):
    before_size = get_size(input_path)

    compress_video(input_path, output_path, filename, target_size)

    after_size = get_size(output_path)

    saved = round(before_size - after_size, 2)
    percent = round((saved / before_size) * 100, 2) if before_size > 0 else 0

    with progress_lock:
        progress_status[filename] = {
            "completed": 100,
            "before": before_size,
            "after": after_size,
            "saved": saved,
            "compression_percent": percent
        }


# ===== ERROR HANDLER =====
@app.errorhandler(413)
def too_large(e):
    return jsonify({"error": "File too large. Maximum upload size is 1000MB."}), 413


# ===== ROUTES =====

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload():
    cleanup_old_files(UPLOAD_FOLDER)
    cleanup_old_files(OUTPUT_FOLDER)

    files = request.files.getlist("videos")
    target_size = int(request.form.get("size", 10))

    results = []

    for file in files:
        filename = file.filename

        input_path = os.path.join(UPLOAD_FOLDER, filename)

        output_filename = f"compressed_{int(time.time())}_{filename}"
        output_path = os.path.join(OUTPUT_FOLDER, output_filename)

        file.save(input_path)

        with progress_lock:
            progress_status[filename] = 0

        threading.Thread(
            target=process_video,
            args=(input_path, output_path, filename, target_size),
            daemon=True
        ).start()

        results.append({
            "name": filename,
            "output": output_filename
        })

    return jsonify(results)


@app.route("/progress/<filename>")
def progress(filename):
    with progress_lock:
        data = progress_status.get(filename, 0)

    if isinstance(data, dict):
        return jsonify(data)

    return jsonify({
        "completed": data,
        "remaining": 100 - data
    })


@app.route("/outputs/<filename>")
def download_file(filename):
    def delete_file():
        try:
            time.sleep(30)
            file_path = os.path.join(OUTPUT_FOLDER, filename)
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"Deleted after download: {filename}")
        except Exception as e:
            print(f"Error deleting file: {e}")

    threading.Thread(target=delete_file, daemon=True).start()

    response = make_response(send_from_directory(OUTPUT_FOLDER, filename, as_attachment=False))
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


# ===== RUN =====
if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
