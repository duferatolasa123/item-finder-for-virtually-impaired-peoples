import { useState, useRef, useEffect } from "react";
import axios from "axios";
import './App.css'

function App() {
  const [recording, setRecording] = useState(false);
  const [text, setText] = useState("Click 'Start Recording' to begin.");
  const [status, setStatus] = useState("Initializing...");
  const [volumeLevel, setVolumeLevel] = useState(0);
  const [audioDevices, setAudioDevices] = useState([]);
  const [selectedMic, setSelectedMic] = useState("");
  
  const mediaRecorder = useRef(null);
  const audioChunks = useRef([]);
  const audioStream = useRef(null);
  const audioContext = useRef(null);
  const analyser = useRef(null);
  const animationId = useRef(null);

  // Check backend on load
  useEffect(() => {
    checkBackend();
    getAudioDevices();
    
    // Clean up on unmount
    return () => {
      if (audioContext.current) {
        audioContext.current.close();
      }
      if (animationId.current) {
        cancelAnimationFrame(animationId.current);
      }
      if (audioStream.current) {
        audioStream.current.getTracks().forEach(track => track.stop());
      }
    };
  }, []);

  const getAudioDevices = async () => {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const mics = devices.filter(device => device.kind === 'audioinput');
      setAudioDevices(mics);
      
      if (mics.length > 0) {
        setSelectedMic(mics[0].deviceId);
      }
    } catch (error) {
      console.log("Could not get audio devices:", error);
    }
  };

  const checkBackend = async () => {
    try {
      setStatus("Checking backend...");
      const response = await axios.get("http://127.0.0.1:5000/api/test", {
        timeout: 5000
      });
      
      if (response.data.model_loaded) {
        setStatus("✅ Backend & model ready!");
        setText("Ready to record. Click the button below.");
      } else {
        setStatus("⚠️ Backend running but model not loaded");
        setText("Model issue. Check backend logs.");
      }
    } catch (error) {
      setStatus("❌ Cannot connect to backend");
      setText("Make sure Flask is running: python app.py");
      console.error("Backend check failed:", error.message);
    }
  };

  const startVolumeMonitoring = (stream) => {
    if (!audioContext.current) {
      audioContext.current = new AudioContext();
    }
    
    const source = audioContext.current.createMediaStreamSource(stream);
    analyser.current = audioContext.current.createAnalyser();
    analyser.current.fftSize = 256;
    source.connect(analyser.current);
    
    const dataArray = new Uint8Array(analyser.current.frequencyBinCount);
    
    const updateVolume = () => {
      if (!analyser.current) return;
      
      analyser.current.getByteFrequencyData(dataArray);
      const average = dataArray.reduce((a, b) => a + b) / dataArray.length;
      setVolumeLevel(average);
      
      // Give real-time feedback
      if (recording) {
        if (average < 20) {
          setText(prev => prev.includes("🔈") ? prev : "🎤 Recording... Speak louder! 🔈");
        } else if (average > 180) {
          setText(prev => prev.includes("🔊") ? prev : "🎤 Recording... Too loud! 🔊");
        }
      }
      
      animationId.current = requestAnimationFrame(updateVolume);
    };
    
    updateVolume();
  };

  const startRecording = async () => {
    try {
      setText("Setting up microphone for optimal recording...");
      
      // Stop any existing stream
      if (audioStream.current) {
        audioStream.current.getTracks().forEach(track => track.stop());
      }
      
      const constraints = {
        audio: {
          deviceId: selectedMic ? { exact: selectedMic } : undefined,
          sampleRate: 44100,  // Higher sample rate for better quality
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        }
      };
      
      const stream = await navigator.mediaDevices.getUserMedia(constraints);
      audioStream.current = stream;
      
      // Start volume monitoring
      startVolumeMonitoring(stream);
      
      // Try different mimeTypes
      const options = { 
        mimeType: 'audio/webm;codecs=opus'
      };
      
      if (!MediaRecorder.isTypeSupported(options.mimeType)) {
        options.mimeType = 'audio/webm';
      }
      
      mediaRecorder.current = new MediaRecorder(stream, options);
      audioChunks.current = [];

      mediaRecorder.current.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunks.current.push(event.data);
        }
      };

      mediaRecorder.current.onstop = async () => {
        setText("Processing audio with enhanced features...");
        
        if (audioChunks.current.length === 0) {
          setText("No audio was recorded.");
          return;
        }

        const audioBlob = new Blob(audioChunks.current, { 
          type: mediaRecorder.current.mimeType 
        });
        
        await sendAudioToBackend(audioBlob);
        
        // Stop volume monitoring
        if (animationId.current) {
          cancelAnimationFrame(animationId.current);
        }
        setVolumeLevel(0);
      };

      mediaRecorder.current.start(100); // Collect data every 100ms
      setRecording(true);
      setText("🎤 Recording... Speak clearly at normal volume.");
      
    } catch (error) {
      console.error("Recording error:", error);
      if (error.name === "NotAllowedError") {
        setText("❌ Microphone access denied. Please allow microphone permission.");
      } else if (error.name === "NotFoundError") {
        setText("❌ No microphone found.");
      } else {
        setText(`❌ Error: ${error.message}`);
      }
    }
  };

  const sendAudioToBackend = async (audioBlob) => {
    try {
      const formData = new FormData();
      formData.append("audio", audioBlob, "voice_recording.webm");

      const response = await axios.post(
        "http://127.0.0.1:5000/api/voice", 
        formData,
        {
          headers: { 
            "Content-Type": "multipart/form-data" 
          },
          timeout: 60000 // 60 seconds for processing
        }
      );
      if (response.data.error) {
        setText(`Server error: ${response.data.error}`);
      } else {
        const transcribedText = response.data.text;
        const confidence = response.data.confidence || "";
        const duration = response.data.duration || "";
        
        setText(`✅ Transcribed (${confidence}, ${duration}): ${transcribedText}`);
      }
    } catch (error) {
      console.error("Backend request error:", error);
      
      let errorMessage = "Unknown error";
      if (error.response) {
        errorMessage = `Server error ${error.response.status}: ${error.response.data?.error || 'Unknown'}`;
      } else if (error.request) {
        errorMessage = "No response from server. Check if Flask is running.";
      } else {
        errorMessage = error.message;
      }
      
      setText(`❌ ${errorMessage}`);
    }
  };

  const stopRecording = () => {
    if (mediaRecorder.current && mediaRecorder.current.state === "recording") {
      mediaRecorder.current.stop();
      setRecording(false);
      
      // Stop volume monitoring
      if (animationId.current) {
        cancelAnimationFrame(animationId.current);
      }
      setVolumeLevel(0);
    }
  };

  const getVolumeColor = () => {
    if (volumeLevel < 20) return "#f44336"; // Red - too quiet
    if (volumeLevel > 180) return "#f44336"; // Red - too loud
    if (volumeLevel > 40 && volumeLevel <= 150) return "#4CAF50"; // Green - good
    return "#ff9800"; // Yellow - okay
  };

  return (
    <div className="container">
      <h1>WEBAPP THAT CAN CONVERT VOICE TO TEXT AND SEND THAT TEXT TO ARDUINO VIA BLUETOOTH COMMUNICATION </h1>
         <h1>IT IS DEVELOPED BY SECTION 1 PEER_GROUP 1 MEMBERS STUDENTS TO USE IT FOR CBTP PHASE 4</h1>
      
      <div className="status-box">
        <h3>System Status:</h3>
        <p className={status.includes('✅') ? 'status-good' : 'status-bad'}>
          {status}
        </p>
        
        {/* Microphone Selection */}
        {audioDevices.length > 0 && (
          <div className="mic-selection">
            <label>Select Microphone:</label>
            <select 
              value={selectedMic} 
              onChange={(e) => setSelectedMic(e.target.value)}
              disabled={recording}
            >
              {audioDevices.map((device, index) => (
                <option key={device.deviceId} value={device.deviceId}>
                  {device.label || `Microphone ${index + 1}`}
                </option>
              ))}
            </select>
          </div>
        )}
        
        <div className="button-group">
          <button onClick={checkBackend} className="check-btn">
            🔄 Check Backend
          </button>
        </div>
      </div>

      <div className="recording-section">
        <h3>Recording Controls:</h3>
        <div className="button-group">
          {!recording ? (
            <button 
              onClick={startRecording}
              disabled={!status.includes('✅')}
              className={`record-btn ${!status.includes('✅') ? 'disabled' : ''}`}
            >
              CLICK HERE AND SPEAK CLEARLY TO MICROPHONE
            </button>
          ) : (
            <button onClick={stopRecording} className="stop-btn">
              ⏹️ Stop Recording
            </button>
          )}
        </div>
        
        {/* Volume Meter */}
        {recording && (
          <div className="volume-meter-container">
            <div className="volume-label">
              Volume Level: <span style={{color: getVolumeColor()}}>{volumeLevel.toFixed(0)}</span>
              {volumeLevel < 20 && " (Too quiet - speak louder)"}
              {volumeLevel > 180 && " (Too loud - move back)"}
              {(volumeLevel >= 20 && volumeLevel <= 180) && " (Good volume)"}
            </div>
            <div className="volume-bar">
              <div 
                className="volume-fill"
                style={{
                  width: `${Math.min(100, (volumeLevel / 255) * 100)}%`,
                  backgroundColor: getVolumeColor()
                }}
              ></div>
            </div>
          </div>
        )}
        
        <div className="recording-status">
          <p className={recording ? 'recording-active' : 'recording-inactive'}>
            {recording ? '🔴 LIVE RECORDING - Speak clearly into microphone' : '✅ Ready to record'}
          </p>
        </div>
      </div>

      <div className="output-section">
        <h3>Transcription Result:</h3>
        <div className="text-output">
          <textarea 
            value={text}
            readOnly
            rows={8}
            placeholder="Transcribed text will appear here..."
          />
        </div>
      </div>
    </div>
  );
}

export default App;