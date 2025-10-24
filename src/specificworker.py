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
from collections import deque


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
        
        self._is_listening = False
        
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
                                end_silence_s: float = 0.7,
                                samplerate: int = 16_000,
                                channels: int = 1,
                                frame_ms: int = 30,
                                vad_aggressiveness: int = 3,
                                pre_roll_s: float = 0.3,
                                activation_speech_ms: int = 200,
                                post_speech_max_duration_s: float = 12.0) -> str:

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
            
            # Solo ponemos datos en la cola si estamos escuchando
            if self._is_listening: 
                 q.put(indata.copy())
            

        tmp = tempfile.NamedTemporaryFile(prefix="ebo_asr_", suffix=".flac", delete=False)
        wav_path = Path(tmp.name)
        tmp.close()

        vad = webrtcvad.Vad(vad_aggressiveness)
        blocksize = int(samplerate * frame_ms / 1000)

        # Buffer circular para conservar pre-roll
        pre_frames = max(0, int(round(pre_roll_s * 1000 / frame_ms)))
        pre_buffer = deque(maxlen=pre_frames)

        # La luz de escucha se enciende si la bandera está activa al inicio
        should_run = self._is_listening 
        if should_run:
            self.led_listening_on()

        started = False
        speech_streak_ms = 0
        last_voice_time = None
        speech_start_time = None

        try:
            with sf.SoundFile(str(wav_path), mode='w',
                            samplerate=samplerate,
                            channels=channels,
                            format='FLAC',
                            subtype='PCM_16') as wav, \
                sd.InputStream(samplerate=samplerate,
                                channels=channels,
                                dtype='int16',
                                blocksize=blocksize,
                                callback=_callback):

                print(f"[AUDIO] Waiting for voice (infinite). activation>={activation_speech_ms}ms, "
                    f"end_silence={end_silence_s:.2f}s, post_limit={post_speech_max_duration_s:.1f}s → {wav_path}")

                # El bucle revisa continuamente la bandera de interrupción
                while self._is_listening:
                    # Usamos timeout=0.1s para poder revisar la bandera self._is_listening
                    try:
                        chunk = q.get(timeout=0.1) 
                    except queue.Empty:
                        if not self._is_listening:
                            break # Salir si el timeout expira y la bandera es False
                        continue
                        
                    now = time.time()
                    is_speech = vad.is_speech(chunk.tobytes(), samplerate)
                    
                    # Revisión de interrupción tras obtener chunk
                    if not self._is_listening:
                        break 

                    if not started:
                        # Antes de activar: rellenamos pre-buffer y exigimos racha de voz
                        pre_buffer.append(chunk)
                        if is_speech:
                            speech_streak_ms += frame_ms
                            if speech_streak_ms >= activation_speech_ms:
                                # ACTIVACIÓN: volcamos el pre-roll (incluye el chunk actual) y arrancamos
                                for b in pre_buffer:
                                    wav.write(b)
                                pre_buffer.clear()
                                started = True
                                speech_start_time = now
                                last_voice_time = now
                        else:
                            speech_streak_ms = 0
                        continue

                    # Ya activado: escribimos todo
                    wav.write(chunk)

                    if is_speech:
                        last_voice_time = now
                    else:
                        if last_voice_time is not None and (now - last_voice_time) >= end_silence_s:
                            break

                    # Límite duro tras empezar voz
                    if (now - speech_start_time) >= post_speech_max_duration_s:
                        break

        finally:
            # Apagamos los LEDs SÓLO si entramos en el bucle
            if should_run:
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
        
        # PASO 1: Establecer la bandera de inicio
        self._is_listening = True 
        
        try:
            # 1) Escuchar hasta silencio o timeout (o interrupción)
            wav_path = self.record_wav_until_silence(
                end_silence_s=0.7,              # silencio para cortar
                samplerate=16_000,
                channels=1,
                frame_ms=30,
                vad_aggressiveness=3,           # más estricto reduce falsos positivos
                pre_roll_s=0.3,                 # audio previo que se guarda
                activation_speech_ms=200,       # exige 200 ms de voz consecutiva para activar
                post_speech_max_duration_s=12.0 # límite duro tras empezar voz
            )

            # 2) Transcribir con Whisper, SÓLO si la bandera sigue activa (no se ha pedido parar)
            if self._is_listening and wav_path and Path(wav_path).exists() and Path(wav_path).stat().st_size > 0:
                ret = self.transcribe_with_whisper(wav_path, model="gpt-4o-mini-transcribe", language="es")
                return ret.strip()
            else:
                 # Si se interrumpió, devolvemos vacío.
                 return ""
        
        finally:
            # 3) Bandera de limpieza y borrado del WAV
            self._is_listening = False # Asegura que la bandera se resetee al terminar
            try:
                if wav_path:
                    Path(wav_path).unlink(missing_ok=True)
            except Exception:
                pass

    #
    # IMPLEMENTATION of stopListening method from EboASR interface
    #
    
    # Función para detener la escucha de forma cooperativa.
    def EboASR_stopListening(self):
        if self._is_listening:
            self._is_listening = False
            print("[EboASR] Señal de stopListening recibida. Forzando salida.")
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



