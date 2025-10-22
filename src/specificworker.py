#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
#    Copyright (C) 2025 by YOUR NAME HERE
#
#    This file is part of RoboComp
#
#    RoboComp is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    RoboComp is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with RoboComp.  If not, see <http://www.gnu.org/licenses/>.
#

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from rich.console import Console
from genericworker import *
import interfaces as ifaces
import time
import sys
import queue
import tempfile
import webrtcvad
import os
from dotenv import load_dotenv
from openai import OpenAI

from pathlib import Path

import sounddevice as sd
import soundfile as sf

sys.path.append('/opt/robocomp/lib')
console = Console(highlight=False)


# If RoboComp was compiled with Python bindings you can use InnerModel in Python
# import librobocomp_qmat
# import librobocomp_osgviewer
# import librobocomp_innermodel


class SpecificWorker(GenericWorker):
    def __init__(self, proxy_map, startup_check=False):
        super(SpecificWorker, self).__init__(proxy_map)
        self.Period = 2000
        self.NUM_LEDS = 54
        
        load_dotenv()
        self.openai_client = OpenAI()
        
        if startup_check:
            self.startup_check()
        else:
            self.timer.timeout.connect(self.compute)
            self.timer.start(self.Period)

    def __del__(self):
        """Destructor"""

    def setParams(self, params):
        # try:
        #	self.innermodel = InnerModel(params["InnerModelPath"])
        # except:
        #	traceback.print_exc()
        #	print("Error reading config params")
        return True

    def set_all_LEDS_colors(self, red=0, green=0, blue=0, white=0):
        pixel_array = {i: ifaces.RoboCompLEDArray.Pixel(red=red, green=green, blue=blue, white=white) for i in
                       range(self.NUM_LEDS)}
        self.ledarray_proxy.setLEDArray(pixel_array)
    
    # Enciende LEDs para informacion visual de que está escuchando
    def led_listening_on(self):
        try:
            self.set_all_LEDS_colors(red = 70, green=255)
        except Exception as e:
            print(f"[LED] No se pudo encender LEDs: {e}", file=sys.stderr)
    
    # Apaga los LEDs
    def led_listening_off(self):
        try:
            self.set_all_LEDS_colors(0, 0, 0, 0)
        except Exception as e:
            print(f"[LED] No se pudo apagar LEDs: {e}", file=sys.stderr)
            
    def record_wav_until_silence(self,
                                 max_duration_s: float = 12.0,
                                 max_silence_s: float = 0.8,
                                 samplerate: int = 16_000,
                                 channels: int = 1,
                                 frame_ms: int = 30,
                                 vad_aggressiveness: int = 2) -> str:

        if frame_ms not in (10, 20, 30):
            raise ValueError("frame_ms debe ser 10, 20 o 30 para webrtcvad")
        if channels != 1:
            raise ValueError("webrtcvad requiere mono; usa channels=1")
        if samplerate not in (8000, 16000, 32000, 48000):
            raise ValueError("webrtcvad admite 8000/16000/32000/48000 Hz")

        q = queue.Queue()

        def _callback(indata, frames, _time, status):
            if status:
                print(f"[AUDIO] {status}", file=sys.stderr)
            q.put(indata.copy())

        # Fichero temporal .wav
        tmp = tempfile.NamedTemporaryFile(prefix="ebo_asr_", suffix=".wav", delete=False)
        wav_path = Path(tmp.name)
        tmp.close()

        vad = webrtcvad.Vad(vad_aggressiveness)
        blocksize = int(samplerate * frame_ms / 1000)

        self.led_listening_on()
        start_time = time.time()
        last_voice_time = None
        heard_any_speech = False

        try:
            with sf.SoundFile(str(wav_path), mode='w',
                              samplerate=samplerate,
                              channels=channels,
                              subtype='PCM_16') as wav, \
                 sd.InputStream(samplerate=samplerate,
                                channels=channels,
                                dtype='int16',
                                blocksize=blocksize,
                                callback=_callback):

                print(f"[AUDIO] Escuchando (VAD), máx {max_duration_s:.1f}s → {wav_path}")
                while True:
                    # Salida por timeout total
                    now = time.time()
                    if (now - start_time) >= max_duration_s:
                        break

                    chunk = q.get()  # forma: (blocksize, 1)
                    wav.write(chunk)

                    # VAD (bytes PCM16 little-endian)
                    chunk_bytes = chunk.tobytes()
                    is_speech = vad.is_speech(chunk_bytes, samplerate)

                    if is_speech:
                        heard_any_speech = True
                        last_voice_time = now
                    else:
                        if heard_any_speech and last_voice_time is not None:
                            if (now - last_voice_time) >= max_silence_s:
                                # silencio suficiente tras haber oído voz
                                break
        finally:
            self.led_listening_off()

        return str(wav_path)

    def transcribe_with_whisper(self, wav_path: str,
                                model: str = "whisper-1",
                                language: str | None = None) -> str:
        p = Path(wav_path)
        if not p.exists() or p.stat().st_size == 0:
            return ""

        with open(wav_path, "rb") as f:
            resp = self.openai_client.audio.transcriptions.create(
                model=model,
                file=f,
                language=language,
                response_format="text",  # devuelve str directamente
            )
        return resp if isinstance(resp, str) else getattr(resp, "text", "")

    
    @QtCore.Slot()
    def compute(self):

        return True

    def startup_check(self):
        print(f"Testing RoboCompLEDArray.Pixel from ifaces.RoboCompLEDArray")
        test = ifaces.RoboCompLEDArray.Pixel()
        QTimer.singleShot(200, QApplication.instance().quit)



    # =============== Methods for Component Implements ==================
    # ===================================================================

    #
    # IMPLEMENTATION of listenandtranscript method from EboASR interface
    #
    
    # Función que ordena a EBO escuchar, enciende luces para indicar la escucha, y devuelve el resultado transcrito
    def EboASR_listenandtranscript(self):
        ret = str()
        wav_path = None
        try:
            # 1) Escuchar hasta silencio o timeout
            wav_path = self.record_wav_until_silence(
                max_duration_s=12.0,
                max_silence_s=0.8,
                samplerate=16_000,
                channels=1,
                frame_ms=30,
                vad_aggressiveness=2
            )
            # 2) Transcribir con Whisper
            ret = self.transcribe_with_whisper(wav_path, model="whisper-1", language="es")
            return ret.strip()
        
        finally:
            # 3) Borrar el WAV temporal
            try:
                if wav_path:
                    Path(wav_path).unlink(missing_ok=True)
            except Exception:
                pass

    # ===================================================================
    # ===================================================================


    ######################
    # From the RoboCompLEDArray you can call this methods:
    # self.ledarray_proxy.getLEDArray(...)
    # self.ledarray_proxy.setLEDArray(...)

    ######################
    # From the RoboCompLEDArray you can use this types:
    # RoboCompLEDArray.Pixel


