import os
import sys

# ============================================================
#  DESACTIVAR POR COMPLETO TORCHCODEC (causa de tu error)
# ============================================================
os.environ["TORCH_AUDIO_DISABLE_TORCHCODECS"] = "1"
os.environ["TORCHCODEC_DISABLE"] = "1"
os.environ["USE_TORCHCODEC"] = "0"
os.environ["DISABLE_TORCHCODEC"] = "1"

# Evitar que FFmpeg interno de torchaudio interfiera
os.environ["TORCHAUDIO_USE_FFMPEG"] = "0"

# ============================================================
#  FORZAR BACKEND DE AUDIO A "soundfile" (100% compatible)
# ============================================================
os.environ["DEMucs_AUDIO_BACKEND"] = "soundfile"
os.environ["AUDIO_BACKEND"] = "soundfile"

# ============================================================
#  EJECUTAR DEMUCS CON BACKEND SOUNDOSLO/SOUNDFILE
# ============================================================
def main():
    try:
        import demucs.separate

        # Construir argumentos (los mismos que venían de Flask)
        args = sys.argv[1:]

        print("============================================")
        print(" Ejecutando Demucs usando backend 'soundfile'")
        print(" TorchCodec desactivado completamente")
        print("============================================")

        # Ejecutar separación con backend seguro
        # NOTA: No pasamos --audio-backend como argumento porque Demucs no lo reconoce en CLI.
        # Ya está configurado por variables de entorno arriba.
        demucs.separate.main(args)

    except Exception as e:
        print("============================================")
        print("         ERROR EN RUN_DEMUCS_WRAPPER        ")
        print("============================================")
        print(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
