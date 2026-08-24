import streamlit as st
import os
import json
import subprocess
import shutil
import tempfile
from pathlib import Path

import yt_dlp
from faster_whisper import WhisperModel
from google import genai
from google.genai import types


st.set_page_config(
    page_title="AutoClipper AI",
    page_icon="✂️",
    layout="wide"
)

st.title("✂️ AutoClipper AI — Gerador de Cortes Inteligentes")

st.markdown(
    "Cole o link do YouTube e gere cortes verticais (9:16) automaticamente com IA."
)


# ============================================================
# GEMINI
# ============================================================

GEMINI_API_KEY = st.secrets.get(
    "GEMINI_API_KEY",
    os.getenv("GEMINI_API_KEY", "")
)

with st.sidebar:

    st.header("⚙️ Configurações")

    num_clips = st.slider(
        "Quantidade de cortes",
        min_value=1,
        max_value=5,
        value=2
    )

    if GEMINI_API_KEY:

        api_key = GEMINI_API_KEY

        st.success("🔑 Chave de API conectada!")

    else:

        api_key = st.text_input(
            "Gemini API Key (Google AI Studio)",
            type="password"
        )


# ============================================================
# URL
# ============================================================

video_url = st.text_input(
    "🔗 Cole o link do YouTube:",
    placeholder="https://www.youtube.com/watch?v=..."
)


# ============================================================
# DIRETÓRIO
# ============================================================

BASE_DIR = Path("autoclipper_jobs")

BASE_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# FFMPEG
# ============================================================

def check_ffmpeg():

    path = shutil.which("ffmpeg")

    if not path:

        raise Exception(
            "FFmpeg não foi encontrado."
        )

    return path


# ============================================================
# DENO
# ============================================================

def check_deno():

    path = shutil.which("deno")

    if path:

        return path

    try:

        import deno

        if hasattr(deno, "find_deno_bin"):

            path = deno.find_deno_bin()

            if path and os.path.exists(path):

                return path

    except Exception:

        pass

    return None


# ============================================================
# PROGRESSO DO DOWNLOAD
# ============================================================

def download_progress(data):

    status = data.get("status")

    if status == "downloading":

        percent = data.get(
            "_percent_str",
            ""
        )

        speed = data.get(
            "_speed_str",
            ""
        )

        eta = data.get(
            "_eta_str",
            ""
        )

        st.write(
            f"📥 Download: {percent} "
            f"| Velocidade: {speed} "
            f"| ETA: {eta}"
        )

    elif status == "finished":

        st.write(
            "✅ Download do vídeo concluído."
        )


# ============================================================
# DOWNLOAD YOUTUBE
# ============================================================

def download_youtube_video(
    url,
    output_dir
):

    output_dir = Path(output_dir)

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    deno_path = check_deno()

    if not deno_path:

        raise Exception(
            "Deno não foi encontrado."
        )

    st.write(
        f"✅ Deno encontrado: `{deno_path}`"
    )

    output_template = str(
        output_dir / "%(id)s.%(ext)s"
    )

    # ========================================================
    # CONFIGURAÇÃO SIMPLIFICADA
    # ========================================================

    ydl_opts = {

        # IMPORTANTE:
        # Primeiro tenta um único MP4.
        # Isso evita baixar vídeo + áudio separadamente.
        "format": (
            "best[ext=mp4]"
            "/best"
        ),

        "outtmpl": output_template,

        "noplaylist": True,

        "overwrites": True,

        "retries": 3,

        "fragment_retries": 3,

        "extractor_retries": 3,

        "socket_timeout": 30,

        "quiet": False,

        "no_warnings": False,

        "ignoreerrors": False,

        # Deno
        "js_runtimes": {
            "deno": {
                "path": deno_path
            }
        },

        # EJS
        "remote_components": {
            "ejs": "github"
        },

        # Mostrar progresso
        "progress_hooks": [
            download_progress
        ]
    }

    try:

        st.write(
            "🔎 Consultando o YouTube..."
        )

        with yt_dlp.YoutubeDL(
            ydl_opts
        ) as ydl:

            info = ydl.extract_info(
                url,
                download=True
            )

            if not info:

                raise Exception(
                    "O YouTube não retornou dados."
                )

            video_id = info.get(
                "id",
                "video"
            )

            title = info.get(
                "title",
                "Vídeo"
            )

            st.write(
                f"🎬 Vídeo: **{title}**"
            )

            # Procurar arquivo
            files = list(
                output_dir.glob(
                    f"{video_id}.*"
                )
            )

            files = [
                f for f in files
                if not f.name.endswith(".part")
            ]

            if not files:

                raise Exception(
                    "O yt-dlp terminou, "
                    "mas o arquivo não foi encontrado."
                )

            # Priorizar MP4
            mp4_files = [
                f for f in files
                if f.suffix.lower() == ".mp4"
            ]

            if mp4_files:

                return str(
                    mp4_files[0]
                )

            return str(
                files[0]
            )

    except Exception as e:

        raise Exception(
            "Falha no download do YouTube:\n\n"
            + str(e)
        )


# ============================================================
# WHISPER
# ============================================================

@st.cache_resource
def load_whisper():

    return WhisperModel(
        "tiny",
        device="cpu",
        compute_type="int8"
    )


def transcribe_video(
    video_path
):

    model = load_whisper()

    segments, info = model.transcribe(
        video_path,
        word_timestamps=True
    )

    blocks = []

    for segment in segments:

        text = segment.text.strip()

        if not text:

            continue

        blocks.append(
            f"[{segment.start:.2f}s - "
            f"{segment.end:.2f}s] "
            f"{text}"
        )

    transcript = "\n".join(
        blocks
    )

    if not transcript:

        raise Exception(
            "Whisper não encontrou fala."
        )

    return transcript


# ============================================================
# GEMINI
# ============================================================

def get_viral_clips(
    transcript,
    gemini_key,
    count
):

    client = genai.Client(
        api_key=gemini_key
    )

    prompt = f"""
Você é um editor profissional de vídeos virais
para TikTok, Instagram Reels e YouTube Shorts.

Analise a transcrição abaixo.

Escolha exatamente {count} melhores momentos.

Cada corte deve ter entre 20 e 50 segundos.

Priorize:

- curiosidade
- emoção
- surpresa
- opinião forte
- ensinamento
- história
- conflito
- informação útil

Não comece no meio de uma frase.

Não invente timestamps.

Retorne SOMENTE JSON:

[
  {{
    "title": "Título chamativo",
    "start": 10.5,
    "end": 42.0,
    "hook": "Frase de impacto inicial",
    "reason": "Por que esse trecho tem potencial"
  }}
]

TRANSCRIÇÃO:

{transcript}
"""

    response = client.models.generate_content(

        model="gemini-2.5-flash",

        contents=prompt,

        config=types.GenerateContentConfig(
            response_mime_type="application/json"
        )
    )

    if not response.text:

        raise Exception(
            "Gemini não retornou resposta."
        )

    clips = json.loads(
        response.text
    )

    valid = []

    for clip in clips:

        try:

            start = float(
                clip["start"]
            )

            end = float(
                clip["end"]
            )

            duration = end - start

            if 20 <= duration <= 50:

                valid.append(
                    {
                        "title": clip.get(
                            "title",
                            f"Corte {len(valid)+1}"
                        ),
                        "start": start,
                        "end": end,
                        "hook": clip.get(
                            "hook",
                            ""
                        ),
                        "reason": clip.get(
                            "reason",
                            ""
                        )
                    }
                )

        except Exception:

            continue

    if not valid:

        raise Exception(
            "Nenhum corte válido foi encontrado."
        )

    return valid


# ============================================================
# DURAÇÃO
# ============================================================

def get_video_duration(
    video_file
):

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        video_file
    ]

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    try:

        return float(
            result.stdout.strip()
        )

    except Exception:

        return None


# ============================================================
# RENDER
# ============================================================

def render_vertical_clip(
    video_file,
    start,
    end,
    output_file
):

    duration = end - start

    cmd = [

        "ffmpeg",

        "-y",

        "-ss",
        str(start),

        "-i",
        video_file,

        "-t",
        str(duration),

        "-vf",
        (
            "scale=1080:1920:"
            "force_original_aspect_ratio=increase,"
            "crop=1080:1920"
        ),

        "-c:v",
        "libx264",

        "-preset",
        "veryfast",

        "-crf",
        "20",

        "-pix_fmt",
        "yuv420p",

        "-c:a",
        "aac",

        "-b:a",
        "192k",

        "-movflags",
        "+faststart",

        output_file
    ]

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if result.returncode != 0:

        raise Exception(
            result.stderr[-5000:]
        )


# ============================================================
# BOTÃO
# ============================================================

if st.button(
    "🚀 Gerar Cortes com IA",
    type="primary",
    use_container_width=True
):

    if not video_url:

        st.error(
            "❌ Cole o link do YouTube."
        )

        st.stop()

    if not api_key:

        st.error(
            "❌ Configure a chave Gemini."
        )

        st.stop()

    # ========================================================
    # JOB
    # ========================================================

    job_dir = Path(
        tempfile.mkdtemp(
            prefix="job_",
            dir=BASE_DIR
        )
    )

    original_dir = (
        job_dir / "original"
    )

    clips_dir = (
        job_dir / "cortes"
    )

    original_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    clips_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    status = st.status(
        "🚀 Processando...",
        expanded=True
    )

    try:

        # ====================================================
        # FFMPEG
        # ====================================================

        status.write(
            "🔧 Verificando FFmpeg..."
        )

        check_ffmpeg()

        status.write(
            "✅ FFmpeg encontrado."
        )


        # ====================================================
        # DENO
        # ====================================================

        status.write(
            "🔧 Verificando Deno..."
        )

        deno_path = check_deno()

        if not deno_path:

            raise Exception(
                "Deno não encontrado."
            )

        status.write(
            f"✅ Deno encontrado: `{deno_path}`"
        )


        # ====================================================
        # DOWNLOAD
        # ====================================================

        status.write(
            "📥 1. Baixando automaticamente "
            "o vídeo do YouTube..."
        )

        video_file = download_youtube_video(
            video_url,
            original_dir
        )

        size_mb = (
            os.path.getsize(
                video_file
            ) / 1024 / 1024
        )

        status.write(
            f"✅ Vídeo baixado: "
            f"{size_mb:.1f} MB"
        )


        # ====================================================
        # WHISPER
        # ====================================================

        status.write(
            "🎙️ 2. Transcrevendo áudio..."
        )

        transcript = transcribe_video(
            video_file
        )

        status.write(
            "✅ Transcrição concluída."
        )


        # ====================================================
        # GEMINI
        # ====================================================

        status.write(
            "🧠 3. IA identificando "
            "os melhores momentos..."
        )

        clips = get_viral_clips(
            transcript,
            api_key,
            num_clips
        )

        status.write(
            f"✅ {len(clips)} cortes encontrados."
        )


        # ====================================================
        # RENDER
        # ====================================================

        status.write(
            "✂️ 4. Gerando cortes verticais..."
        )

        rendered = []

        for i, clip in enumerate(
            clips
        ):

            output_file = (
                clips_dir /
                f"corte_{i+1}.mp4"
            )

            status.write(
                f"🎬 Renderizando "
                f"{i+1}/{len(clips)}..."
            )

            render_vertical_clip(
                video_file,
                clip["start"],
                clip["end"],
                str(output_file)
            )

            rendered.append(
                (
                    clip,
                    str(output_file)
                )
            )


        # ====================================================
        # FINAL
        # ====================================================

        status.update(
            label="✅ Cortes finalizados!",
            state="complete",
            expanded=False
        )


        st.divider()

        st.subheader(
            "🎉 Seus Cortes Prontos"
        )

        cols = st.columns(
            len(rendered)
        )

        for i, (
            clip,
            output_file
        ) in enumerate(
            rendered
        ):

            with cols[i]:

                st.markdown(
                    f"### {clip['title']}"
                )

                st.caption(
                    f"⏱️ "
                    f"{clip['start']:.1f}s → "
                    f"{clip['end']:.1f}s"
                )

                if clip["hook"]:

                    st.write(
                        f"**🎯 Gancho:** "
                        f"*{clip['hook']}*"
                    )

                if clip["reason"]:

                    st.write(
                        f"**💡 Motivo:** "
                        f"{clip['reason']}"
                    )

                st.video(
                    output_file
                )

                with open(
                    output_file,
                    "rb"
                ) as f:

                    st.download_button(
                        f"⬇️ Baixar Corte {i+1}",
                        f,
                        file_name=f"corte_{i+1}.mp4",
                        mime="video/mp4",
                        key=f"download_{i}"
                    )


    except Exception as e:

        status.update(
            label="❌ Erro durante o processamento",
            state="error",
            expanded=True
        )

        st.error(
            "Erro durante o processamento:"
        )

        st.code(
            str(e)
        )
