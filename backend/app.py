from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from foul_words import SIMULATED_FOUL_WORDS
import moviepy.editor as mp
import speech_recognition as sr
from pydub import AudioSegment
from pydub.generators import Sine
import tempfile
import os
import io
import re
import shutil
import requests
import pytesseract
from PIL import Image, ImageFilter

app = Flask(__name__)
CORS(app)

API_BASE_URL = "http://127.0.0.1:5000"


@app.route('/api/detect', methods=['POST'])
def simulated_api_detect():
    """Acts as the third-party API for detection."""
    data = request.get_json()
    text = data.get('text', '').lower()
    words = set(re.findall(r'\b\w+\b', text))
    detected = [word for word in words if word in SIMULATED_FOUL_WORDS]
    return jsonify({'detected_foul_words': detected})

def get_foul_words_from_api(text):
    """Handles HTTP requests to the detection API."""
    try:
        response = requests.post(f"{API_BASE_URL}/api/detect", json={'text': text})
        response.raise_for_status()
        return response.json().get('detected_foul_words', [])
    except Exception as e:
        print(f"API Error: {e}")
        return []


# --- TEXT REFINEMENT --- 

def refine_text(text):
    """Replaces detected foul words with asterisks."""
    foul_words_list = get_foul_words_from_api(text)
    foul_words_set = set(word.lower() for word in foul_words_list)
    words = re.findall(r'(\b\w+\b|\W+)', text)

    refined_parts = []
    for part in words:
        if re.match(r'\b\w+\b', part):
            if part.lower() in foul_words_set:
                refined_parts.append('*' * len(part))
            else:
                refined_parts.append(part)
        else:
            refined_parts.append(part)
    return "".join(refined_parts)


# --- IMAGE REFINEMENT---

def refine_image(file_storage):
    """
    Uses OCR to detect text positions and selectively blurs
    only the regions containing foul words.
    """
    img = Image.open(file_storage.stream).convert("RGB")

    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

    for i in range(len(data['text'])):
        word = data['text'][i].strip().lower()

        if word in SIMULATED_FOUL_WORDS:
            x, y, w, h = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
            box = (x - 2, y - 2, x + w + 2, y + h + 2)
            region = img.crop(box)
            blurred_region = region.filter(ImageFilter.GaussianBlur(radius=15))
            img.paste(blurred_region, box)

    img_io = io.BytesIO()
    img_format = img.format if img.format else 'PNG'
    img.save(img_io, format=img_format)
    img_io.seek(0)
    return img_io, img_format


# --- VIDEO REFINEMENT ---

def refine_video(file_storage):
    """
    Extracts audio, gets word-level timestamps from Google Speech Recognition,
    and replaces ONLY the foul word segments with a beep. All other audio is untouched.
    """
    temp_input = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    file_storage.save(temp_input.name)
    temp_input.close()

    temp_output_path = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4").name
    temp_files_to_cleanup = [temp_input.name, temp_output_path]

    try:
        video = mp.VideoFileClip(temp_input.name)

        if video.audio is None:
            video.close()
            shutil.copy(temp_input.name, temp_output_path)
        else:
            # Step 1: Extract audio to WAV
            temp_audio_path = tempfile.NamedTemporaryFile(delete=False, suffix=".wav").name
            temp_files_to_cleanup.append(temp_audio_path)
            video.audio.write_audiofile(temp_audio_path, logger=None)

            # Step 2: Get word-level timestamps from Google
            recognizer = sr.Recognizer()
            word_timestamps = []  # (word, start_ms, end_ms)

            try:
                with sr.AudioFile(temp_audio_path) as source:
                    audio_data = recognizer.record(source)

                # show_all=True returns raw Google response with per-word timing
                result = recognizer.recognize_google(audio_data, show_all=True)

                if result and 'alternative' in result:
                    best = result['alternative'][0]
                    transcript = best.get('transcript', '').lower()
                    print(f"Transcript: {transcript}")

                    if 'words' in best:
                        # Google returned per-word timestamps — use them directly
                        for w in best['words']:
                            word = w['word'].lower().strip('.,!?"\'')
                            start_s = float(w['startTime'].replace('s', ''))
                            end_s = float(w['endTime'].replace('s', ''))
                            word_timestamps.append((word, int(start_s * 1000), int(end_s * 1000)))
                            print(f"  '{word}' {start_s}s-{end_s}s")
                    else:
                        # Fallback: evenly distribute words across audio duration
                        print("No per-word timestamps from API — estimating positions.")
                        words = [w.strip('.,!?"\'') for w in transcript.split()]
                        audio_duration_ms = len(AudioSegment.from_wav(temp_audio_path))
                        avg_ms = audio_duration_ms // max(len(words), 1)
                        for idx, word in enumerate(words):
                            word_timestamps.append((word, idx * avg_ms, (idx + 1) * avg_ms))

            except Exception as recog_err:
                print(f"Speech recognition skipped: {recog_err}")

            # Step 3: Surgically splice beep over each foul word.
            # Reverse order so earlier segment positions stay valid after each splice.
            audio = AudioSegment.from_wav(temp_audio_path)
            foul_set = set(SIMULATED_FOUL_WORDS)

            foul_segments = sorted(
                [(s, e) for word, s, e in word_timestamps if word in foul_set],
                reverse=True
            )

            for start_ms, end_ms in foul_segments:
                duration_ms = max(end_ms - start_ms, 100)
                print(f"Beeping {start_ms}ms-{end_ms}ms ({duration_ms}ms)")
                beep = Sine(1000).to_audio_segment(duration=duration_ms).apply_gain(-3)
                audio = audio[:start_ms] + beep + audio[end_ms:]

            # Step 4: Export modified audio
            temp_modified_audio = tempfile.NamedTemporaryFile(delete=False, suffix=".wav").name
            temp_files_to_cleanup.append(temp_modified_audio)
            audio.export(temp_modified_audio, format="wav")

            # Step 5: Mux audio back into video
            temp_mux_audio = tempfile.NamedTemporaryFile(delete=False, suffix=".m4a").name
            temp_files_to_cleanup.append(temp_mux_audio)

            final_audio = mp.AudioFileClip(temp_modified_audio)
            final_video = video.set_audio(final_audio)
            final_video.write_videofile(
                temp_output_path,
                codec="libx264",
                audio_codec="aac",
                logger=None,
                temp_audiofile=temp_mux_audio
            )
            video.close()
            final_audio.close()

        # Step 6: Load into BytesIO buffer for safe streaming
        with open(temp_output_path, "rb") as f:
            video_bytes = f.read()

        return io.BytesIO(video_bytes)

    finally:
        for path in temp_files_to_cleanup:
            try:
                if os.path.exists(path):
                    os.unlink(path)
            except Exception as e:
                print(f"Cleanup warning for {path}: {e}")


# --- MAIN ROUTES ---

def get_civility_score(text):
    """Calculates simulated civility score."""
    if not text:
        return 100
    foul_words = get_foul_words_from_api(text)
    total_words = len(re.findall(r'\b\w+\b', text))
    if total_words == 0:
        return 100
    penalty = (len(foul_words) / total_words) * 100
    return max(0, 100 - int(penalty))

@app.route('/check', methods=['POST'])
def check_civility():
    """Route to check text civility score."""
    data = request.get_json()
    text = data.get('text', '')
    return jsonify({'score': get_civility_score(text)})

@app.route('/refine', methods=['POST'])
def refine_and_download():
    """
    Central route for file refinement. Dispatches to image, video, or text
    logic based on the file mimetype.
    """
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['file']
    if not file:
        return jsonify({'error': 'No selected file'}), 400

    try:
        # Image refinement
        if file.mimetype.startswith('image/'):
            refined_buffer, img_ext = refine_image(file)
            return send_file(
                refined_buffer,
                as_attachment=True,
                download_name=f'refined_image.{img_ext.lower()}',
                mimetype=file.mimetype
            )

        # Video refinement
        if file.mimetype.startswith('video/'):
            refined_video_buffer = refine_video(file)
            refined_video_buffer.seek(0)
            return send_file(
                refined_video_buffer,
                as_attachment=True,
                download_name='refined_video.mp4',
                mimetype='video/mp4'
            )

        # Default: text refinement
        file_content = file.read().decode('utf-8')
        refined_content = refine_text(file_content)
        file_stream = io.BytesIO(refined_content.encode('utf-8'))

        return send_file(
            file_stream,
            as_attachment=True,
            download_name='refined_text.txt',
            mimetype='text/plain'
        )

    except Exception as e:
        app.logger.error(f"Processing error: {e}", exc_info=True)
        return jsonify({'error': 'Failed to process file'}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)