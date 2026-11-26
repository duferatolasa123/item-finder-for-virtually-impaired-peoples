from flask import Flask, request, jsonify
from flask_cors import CORS
from transformers import WhisperForConditionalGeneration, WhisperProcessor
import torch
import numpy as np
import io
import tempfile
import os
import sys
from scipy import signal  # Added for audio filtering

# Try to import optional libraries
try:
    import librosa
    LIBROSA_AVAILABLE = True
except ImportError:
    LIBROSA_AVAILABLE = False
    print("⚠️ librosa not available, will try other methods")

try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    print("⚠️ pydub not available")

try:
    import soundfile as sf
    SOUNDFILE_AVAILABLE = True
except ImportError:
    SOUNDFILE_AVAILABLE = False
    print("⚠️ soundfile not available")

app = Flask(__name__)
CORS(app)

MODEL_PATH = r"C:\Users\hp\Desktop\VIPH\backend\model"

# Initialize model variables
processor = None
model = None

try:
    print(f"📁 Attempting to load model from: {MODEL_PATH}")
    processor = WhisperProcessor.from_pretrained(MODEL_PATH)
    model = WhisperForConditionalGeneration.from_pretrained(MODEL_PATH)
    model.eval()
    print("✅ Whisper model loaded successfully!")
except Exception as e:
    print(f"❌ Error loading model: {e}")
    print("Make sure the model files are in the directory")
    # ========== BLUETOOTH SETUP ==========
BT_PORT = "COM6"      # ⚠️ change to your HC-05 COM port
BT_BAUD = 9600

try:
    bt = serial.Serial(BT_PORT, BT_BAUD, timeout=1)
    time.sleep(2)
    print("✅ Bluetooth connected on", BT_PORT)
except Exception as e:
    bt = None
    print("❌ Bluetooth error:", e)


def send_to_arduino(text):
    if bt is None:
        print("❌ Bluetooth not available")
        return
    bt.write((text + "\n").encode())
    print("📤 Sent to Arduino:", text)

# =============== AUDIO ENHANCEMENT FUNCTIONS ===============
def enhance_audio_quality(audio_data, sr):
    """
    Apply audio enhancement techniques to improve transcription accuracy
    """
    enhanced = audio_data.copy()
    
    # 1. Remove DC offset (center around zero)
    enhanced = enhanced - np.mean(enhanced)
    
    # 2. Apply bandpass filter for speech frequencies (300Hz - 3400Hz)
    # This removes low-frequency noise and high-frequency hiss
    nyquist = sr / 2
    low = 300 / nyquist
    high = 3400 / nyquist
    b, a = signal.butter(4, [low, high], btype='band')
    enhanced = signal.filtfilt(b, a, enhanced)
    print("✅ Applied bandpass filter (300Hz-3400Hz)")
    
    # 3. Normalize volume to optimal level (80% of max)
    max_val = np.max(np.abs(enhanced))
    if max_val > 0:
        target_peak = 0.8  # 80% of max volume
        gain = target_peak / max_val
        enhanced = enhanced * gain
        print(f"✅ Normalized audio (gain: {gain:.2f}x)")
    
    # 4. Simple noise gate to remove very quiet parts
    threshold = 0.01  # Adjust based on your environment
    enhanced[np.abs(enhanced) < threshold] = 0
    print("✅ Applied noise gate")
    
    return enhanced

def remove_silence_parts(audio_data, sr):
    """
    Remove prolonged silence from beginning and end
    """
    if len(audio_data) == 0:
        return audio_data
    
    threshold = 0.02
    abs_audio = np.abs(audio_data)
    
    # Find where audio actually starts (non-silence)
    start_idx = 0
    for i in range(len(abs_audio)):
        if abs_audio[i] > threshold:
            start_idx = max(0, i - int(0.05 * sr))  # Keep 50ms before
            break
    
    # Find where audio ends
    end_idx = len(abs_audio)
    for i in range(len(abs_audio)-1, -1, -1):
        if abs_audio[i] > threshold:
            end_idx = min(len(abs_audio), i + int(0.05 * sr))  # Keep 50ms after
            break
    
    if end_idx > start_idx:
        trimmed_audio = audio_data[start_idx:end_idx]
        original_len = len(audio_data) / sr
        trimmed_len = len(trimmed_audio) / sr
        print(f"✅ Trimmed silence: {trimmed_len:.2f}s remaining (from {original_len:.2f}s)")
        return trimmed_audio
    
    return audio_data
@app.post("/api/test-bt")
def test_bt():
    data = request.json
    send_to_arduino(data["text"])
    return {"status": "sent"}

@app.route("/api/test", methods=["GET"])
def test():
    return jsonify({
        "message": "Backend is running!",
        "model_loaded": model is not None,
        "librosa": LIBROSA_AVAILABLE,
        "pydub": PYDUB_AVAILABLE,
        "soundfile": SOUNDFILE_AVAILABLE
    })

@app.route("/api/voice", methods=["POST"])
def transcribe():
    try:
        if model is None or processor is None:
            return jsonify({"error": "Model not loaded"}), 500
            
        if "audio" not in request.files:
            return jsonify({"error": "No audio file provided"}), 400
            
        audio_file = request.files["audio"]
        
        if audio_file.filename == '':
            return jsonify({"error": "No selected file"}), 400
        
        # Read the file bytes
        audio_bytes = audio_file.read()
        
        if len(audio_bytes) == 0:
            return jsonify({"error": "Empty audio file"}), 400
        
        # Try different methods to read audio
        audio_data = None
        sr = None
        
        # Method 1: Try librosa (supports many formats)
        if LIBROSA_AVAILABLE:
            try:
                audio_data, sr = librosa.load(io.BytesIO(audio_bytes), sr=16000)
                print(f"✅ Loaded with librosa: {len(audio_data)} samples, {sr} Hz")
            except Exception as e:
                print(f"⚠️ librosa failed: {e}")
        
        # Method 2: Try pydub
        if audio_data is None and PYDUB_AVAILABLE:
            try:
                audio_segment = AudioSegment.from_file(io.BytesIO(audio_bytes))
                # Convert to mono and 16kHz
                audio_segment = audio_segment.set_channels(1).set_frame_rate(16000)
                samples = np.array(audio_segment.get_array_of_samples())
                # Normalize to float32
                if audio_segment.sample_width == 2:
                    audio_data = samples.astype(np.float32) / 32768.0
                elif audio_segment.sample_width == 4:
                    audio_data = samples.astype(np.float32) / 2147483648.0
                else:
                    audio_data = samples.astype(np.float32) / 32768.0
                sr = 16000
                print(f"✅ Loaded with pydub: {len(audio_data)} samples, {sr} Hz")
            except Exception as e:
                print(f"⚠️ pydub failed: {e}")
        
        # Method 3: Try soundfile
        if audio_data is None and SOUNDFILE_AVAILABLE:
            try:
                # Save to temp file
                with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as tmp:
                    tmp.write(audio_bytes)
                    tmp_path = tmp.name
                
                # Try to read with soundfile
                audio_data, sr = sf.read(tmp_path)
                
                # Convert to mono if stereo
                if len(audio_data.shape) > 1:
                    audio_data = np.mean(audio_data, axis=1)
                
                # Resample to 16kHz if needed
                if sr != 16000:
                    if LIBROSA_AVAILABLE:
                        import librosa
                        audio_data = librosa.resample(audio_data, orig_sr=sr, target_sr=16000)
                    sr = 16000

                print(f"✅ Loaded with soundfile: {len(audio_data)} samples, {sr} Hz")
                
                # Clean up temp file
                os.unlink(tmp_path)
                
            except Exception as e:
                print(f"⚠️ soundfile failed: {e}")
        
        # Method 4: Try wave module (for WAV files)
        if audio_data is None:
            try:
                import wave
                import struct
                with io.BytesIO(audio_bytes) as f:
                    wav = wave.open(f, 'rb')
                    sr = wav.getframerate()
                    n_frames = wav.getnframes()
                    audio_bytes = wav.readframes(n_frames)
                    wav.close()
                
                # Convert bytes to numpy array
                if wav.getsampwidth() == 2:
                    audio_data = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
                elif wav.getsampwidth() == 4:
                    audio_data = np.frombuffer(audio_bytes, dtype=np.int32).astype(np.float32) / 2147483648.0
                else:
                    audio_data = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
                
                # Convert to mono if needed
                if wav.getnchannels() > 1:
                    audio_data = audio_data.reshape(-1, wav.getnchannels())
                    audio_data = np.mean(audio_data, axis=1)
                
                # Resample if needed
                if sr != 16000 and LIBROSA_AVAILABLE:
                    import librosa
                    audio_data = librosa.resample(audio_data, orig_sr=sr, target_sr=16000)
                    sr = 16000
                
                print(f"✅ Loaded with wave: {len(audio_data)} samples, {sr} Hz")
            except Exception as e:
                print(f"⚠️ wave failed: {e}")
        
        if audio_data is None:
            return jsonify({"error": "Could not read audio file. No suitable library found. Please install: pip install librosa pydub soundfile"}), 400
        
        # =============== AUDIO ENHANCEMENT ===============
        print("🔧 Enhancing audio quality for better accuracy...")
        
        # Apply audio enhancement
        audio_data = enhance_audio_quality(audio_data, sr)
        
        # Remove silence from beginning and end
        audio_data = remove_silence_parts(audio_data, sr)
        
        # Check audio quality metrics
        rms_volume = np.sqrt(np.mean(audio_data**2))
        print(f"📊 Audio RMS volume: {rms_volume:.4f}")
        
        # Check if audio is too quiet
        if rms_volume < 0.005:
            return jsonify({"error": "Audio too quiet. Please speak louder and closer to microphone."}), 400
        
        # Check audio length after processing
        duration = len(audio_data) / sr
        print(f"📊 Processed audio duration: {duration:.2f} seconds")
        
        if duration < 0.8:  # Increased minimum duration
            return jsonify({"error": f"Audio too short after processing: {duration:.2f} seconds (speak for at least 1 second)"}), 400
        
        # =============== IMPROVED INFERENCE ===============
        print("🎯 Processing with optimized parameters...")
        
        # Prepare input features
        input_features = processor(
            audio_data, 
            sampling_rate=sr, 
            return_tensors="pt"
        ).input_features
        
        # Generate transcription with BETTER PARAMETERS
        with torch.no_grad():
            # Use beam search for better accuracy (instead of greedy)
            predicted_ids = model.generate(
                input_features,
                max_length=448,          # Maximum tokens
                num_beams=3,             # Beam search width (3-5 is good)
                temperature=0.0,         # Deterministic output
                early_stopping=True,     # Stop when done
                length_penalty=1.0,      # Encourage appropriate length
                # Optional: Add repetition penalty if you get repeating words
                # repetition_penalty=1.2,
                # no_repeat_ngram_size=3,
            )
            
            text = processor.batch_decode(predicted_ids, skip_special_tokens=True)[0]
        
        # Post-process the text
        text = text.strip()
        if not text:
            text = "[No speech detected]"
        
        print(f"✅ Transcription: {text}")
        send_to_arduino(text)
        
    # Return with additional quality info
        return jsonify({
            "text": text,
            "confidence": "high",
            "duration": f"{duration:.2f}s",
            "volume_level": f"{rms_volume:.4f}",
            "processing": "enhanced"
        })
       
    except Exception as e:
        print(f"❌ Error in transcription: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    print("=" * 50)
    print("🚀 ENHANCED WHISPER BACKEND STARTING")
    print("📈 Features: Audio enhancement + Beam search")
    print("=" * 50)
    print("📡 Test endpoint: http://127.0.0.1:5000/api/test")
    print(f"🔧 Available libraries: librosa={LIBROSA_AVAILABLE}")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=True)