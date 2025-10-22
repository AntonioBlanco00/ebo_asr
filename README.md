# ebo_asr

Speech-to-Text (ASR) component for the EBO robot. It **listens until silence or a timeout**, turns LEDs on while listening, **transcribes with OpenAI Whisper**, and **deletes the temporary WAV**. It returns a clean `str` you can pass to your LLM.

## What it does
1. Turns LEDs (cyan/green) on to indicate the robot is listening.  
2. Records from the microphone **until voice stops** (VAD) or a **max timeout** is reached.  
3. Sends the WAV to **OpenAI Whisper** and retrieves the transcription.  
4. **Deletes** the temporary file and **returns** the text.

## System requirements
- Python 3.10+  
- PortAudio / ALSA (for `sounddevice`)  
- libsndfile (for `soundfile`)  
- Internet connectivity (Whisper on OpenAI)  
- RoboComp installed with a working `LEDArray` proxy

## Python dependencies (no requirements.txt)
Install these packages:
```bash
pip install "sounddevice>=0.4.6" "soundfile>=0.12.1" "webrtcvad>=2.0.10" "openai>=1.40.0" "python-dotenv>=1.0.1"
```
> If `sounddevice` fails to build, install PortAudio and libsndfile from your distro (e.g., `sudo apt install portaudio19-dev libsndfile1`).

## Configure the API Key (`.env`)
Create a file named **`.env`** at the **repository root** with:
```
OPENAI_API_KEY=YOUR_OPENAI_API_KEY_HERE
```
The code loads this file with `python-dotenv` (`load_dotenv()`), and the OpenAI SDK uses that env var.  
> `.env` is included in `.gitignore`, so it will **not** be committed.

### Quick check
```bash
python - << 'PY'
from dotenv import load_dotenv; import os
load_dotenv()
print("OK" if os.getenv("OPENAI_API_KEY") else "FAIL: OPENAI_API_KEY missing")
PY
```

## Configuration parameters
As any RoboComp component, *ebo_asr* needs a config file to start. In
```
etc/config
```
you can find an example config. Adjust it to your deployment (endpoints, proxies, etc.). Typical fields to review:
- **LEDArray proxy** (host/port of the LEDs component).
- Ports/endpoints for this component.

*(Place your actual config example here if you have a final version; this project does not edit `etc/config`.)*

## Starting the component
To avoid editing `etc/config` in the repo, copy it and edit the local copy:
```bash
cd <path_to_ebo_asr>
cp etc/config config
```

### Option A — Run directly with Python (recommended during development)
```bash
python src/ebo_asr.py --Ice.Config=etc/config
```

### Option B — Run the generated binary (if your environment produces `bin/ebo_asr`)
```bash
bin/ebo_asr etc/config
```

During testing you should see the transcription printed after each **listen → transcribe → delete WAV** cycle.

## Useful parameters (`src/specificworker.py`)
- `max_duration_s`: maximum recording duration.  
- `max_silence_s`: silence after speech to stop recording.  
- `samplerate`: 16000 Hz (recommended for Whisper).  
- `vad_aggressiveness`: 0–3 (higher = stricter VAD).  
- LEDs during listen: adjust `led_listening_on()` (green/cyan) and `led_listening_off()`.

## Repository layout (summary)
```
ebo_asr/
├── .gitignore
├── etc/
│   └── config
├── IDSL/
│   └── EboASR.idsl
├── src/
│   ├── ebo_asr.py
│   ├── specificworker.py
│   ├── genericworker.py
│   ├── interfaces.py
│   ├── eboasrI.py
│   ├── CommonBehavior.ice
│   ├── LEDArray.ice
│   └── EboASR.ice
├── ebo_asr.cdsl
└── statemachine.smdsl
```

## Troubleshooting
- **Microphone / ALSA / PortAudio**  
  List devices:
  ```bash
  python -c "import sounddevice as sd; print(sd.query_devices())"
  ```
  Select a specific input in code:
  ```python
  import sounddevice as sd
  sd.default.device = (INPUT_INDEX, None)
  ```
- **429 / network issues with Whisper**: reduce recording duration, add retries, or limit concurrency.
- **LEDs not changing**: check `ledarray_proxy` connectivity and `NUM_LEDS` value.

## License
GPL-3.0 (as indicated in the project headers).
