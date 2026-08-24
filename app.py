import os
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import streamlit as st
import yt_dlp

from faster_whisper import WhisperModel
from google import genai
from google.genai import types


# ============================================================
# CONFIGURAÇÃO
# ============================================================

st.set_page_config(
    page_title="AutoClipper AI",
    page_icon="✂️",
    layout="wide"
)

st.title("✂️ AutoClipper AI")
st.caption(
    "Cole um link do YouTube e gere cortes verticais automaticamente."
)


# ============================================================
# CONFIGURAÇÕES
# ============================================================

GEMINI_API_KEY = st.secrets.get(
    "GEMINI_API_KEY",
    os.getenv("GEMINI_API_KEY", "")
)

with st.sidebar:

    st.header("⚙️ Configurações")

    num_clips = st.slider(
        "Quantidade de cortes",
        1,
        5,
        2
    )

    if GEMINI_API_KEY:
        api_key = GEMINI_API_KEY
        st.success("🔑 Gemini conectado")
    else:
        api_key = st.text_input(
            "Gemini API Key",
            type="password"
        )


video_url = st.text_input(
    "🔗 Link do YouTube",
    placeholder="https://www.youtube.com/watch?v=..."
)


# ============================================================
# DIRETÓRIOS
# ============================================================

BASE_DIR = Path("autoclipper_jobs")
BASE_DIR.mkdir(exist_ok=True)


# ============================================================
# FFMPEG
# ============================================================

def check_ffmpeg():

    ffmpeg = shutil.which("ffmpeg")

    if not ffmpeg:
        raise RuntimeError(
            "FFmpeg não encontrado no servidor."
        )

    return ffmpeg


# ============================================================
# DENO
# ============================================================

def check_deno():

    deno = shutil.which("deno")

    if deno:
        return deno

    return None


# ============================================================
# PROGRESSO
# ============================================================

def download_progress(data):

    if data["status"] == "downloading":

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
            f"📥 {percent} | "
            f"{speed} | ETA {eta}"
        )

    elif data["status"] == "finished":

        st.write(
            "✅ Download concluído."
        )


# ============================================================
# DOWNLOAD YOUTUBE
# ============================================================

def download_youtube(url, output_dir):

    output_dir = Path(output_dir)

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    deno = check_deno()

    if not deno:
        raise RuntimeError(
            "Deno não encontrado."
        )

    st.write(
        f"✅ Deno: `{deno}`"
    )

    output_template = str(
        output_dir / "%(id)s.%(ext)s"
    )

    # ========================================================
    # IMPORTANTE
    #
    # Não forçamos MP4.
    #
    # O YouTube normalmente disponibiliza:
    #
    # vídeo separado
    # +
    # áudio separado
    #
    # O FFmpeg junta os dois.
    # ========================================================

    ydl_opts = {

        "format": (
            "bestvideo*+bestaudio/"
            "best"
        ),

        "outtmpl": output_template,

        "merge_output_format": "mp4",

        "noplaylist": True,

        "overwrites": True,

        "retries": 5,

        "fragment_retries": 5,

        "extractor_retries": 5,

        "socket_timeout": 30,

        "concurrent_fragment_downloads": 1,

        "quiet": False,

        "no_warnings": False,

        "ignoreerrors": False,

        # ====================================================
        # DENO CORRETO
        # ====================================================

        "js_runtimes": {
            "deno": {
                "path": deno
            }
        },

        "remote_components": {
            "ejs": "github"
        },

        "progress_hooks": [
            download_progress
        ]
    }

    try:

        st.write(
            "🔎 Obtendo informações do vídeo..."
        )

        with yt_dlp.YoutubeDL(
            ydl_opts
        ) as ydl:

            info = ydl.extract_info(
                url,
                download=True
            )

            if not info:
                raise RuntimeError(
                    "O YouTube não retornou informações."
                )

            video_id = info["id"]

            title = info.get(
                "title",
                "Vídeo"
            )

            st.write(
                f"🎬 **{title}**"
            )

            # ------------------------------------------------
            # Procurar MP4 final
            # ------------------------------------------------

            mp4 = output_dir / (
                f"{video_id}.mp4"
            )

            if mp4.exists():
                return str(mp4)

            # ------------------------------------------------
            # Procurar qualquer arquivo baixado
            # ------------------------------------------------

            files = [
                p for p in output_dir.glob(
                    f"{video_id}.*"
                )
                if not p.name.endswith(".part")
            ]

            if not files:

                raise RuntimeError(
                    "O yt-dlp não criou nenhum arquivo."
                )

            # ------------------------------------------------
            # Se houver apenas um arquivo, usar ele.
            # ------------------------------------------------

            if len(files) == 1:
                return str(files[0])

            # ------------------------------------------------
            # Caso o merge não tenha ocorrido,
            # localizar vídeo e áudio.
            # ------------------------------------------------

            video_files = [
                p for p in files
                if p.suffix.lower()
                in [".mp4", ".webm", ".mkv"]
            ]

            if not video_files:
                raise RuntimeError(
                    "Não foi possível localizar o vídeo baixado."
                )

            return str(video_files[0])

    except Exception as e:

        raise RuntimeError(
            "Falha no download do YouTube:\n\n"
            + str(e)
        )


# ============================================================
# WHISPER
# ============================================================

@st.cache_resource
def get_whisper():

    return WhisperModel(
        "tiny",
        device="cpu",
        compute_type="int8"
    )


def transcribe(video):

    model = get_whisper()

    segments, info = model.transcribe(
        video,
        word_timestamps=True
    )

    result = []

    for segment in segments:

        text = segment.text.strip()

        if text:

            result.append(
                f"[{segment.start:.2f}s - "
                f"{segment.end:.2f}s] "
                f"{text}"
            )

    if not result:

        raise RuntimeError(
            "Não foi possível gerar a transcrição."
        )

    return "\n".join(result)


# ============================================================
# GEMINI
# ============================================================

def find_clips(
    transcript,
    key,
    quantity
):

    client = genai.Client(
        api_key=key
    )

    prompt = f"""
Você é um editor profissional de vídeos virais.

Analise a transcrição abaixo e escolha
os {quantity} melhores cortes para:

TikTok
Instagram Reels
YouTube Shorts

REGRAS:

1. Cada corte deve ter entre 20 e 50 segundos.
2. O início deve fazer sentido.
3. O final deve completar a ideia.
4. Priorize emoção, curiosidade,
   surpresa, conflito, ensinamento
   ou opinião forte.
5. Não invente timestamps.
6. Use somente os timestamps da transcrição.

Retorne SOMENTE JSON:

[
  {{
    "title": "Título",
    "start": 10.0,
    "end": 40.0,
    "hook": "Gancho",
    "reason": "Motivo"
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
        raise RuntimeError(
            "Gemini não retornou dados."
        )

    data = json.loads(
        response.text
    )

    clips = []

    for item in data:

        try:

            start = float(
                item["start"]
            )

            end = float(
                item["end"]
            )

            duration = end - start

            if (
                duration >= 20
                and duration <= 50
                and end > start
            ):

                clips.append(
                    {
                        "title": item.get(
                            "title",
                            "Corte"
                        ),
                        "start": start,
                        "end": end,
                        "hook": item.get(
                            "hook",
                            ""
                        ),
                        "reason": item.get(
                            "reason",
                            ""
                        )
                    }
                )

        except Exception:
            continue

    if not clips:
        raise RuntimeError(
            "Nenhum corte válido foi encontrado."
        )

    return clips[:quantity]


# ============================================================
# FFMPEG
# ============================================================

def create_clip(
    source,
    start,
    end,
    destination
):

    duration = end - start

    command = [

        "ffmpeg",

        "-y",

        "-ss",
        str(start),

        "-i",
        source,

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

        str(destination)
    ]

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if result.returncode != 0:

        raise RuntimeError(
            "FFmpeg falhou:\n\n"
            + result.stderr[-5000:]
        )


# ============================================================
# EXECUÇÃO
# ============================================================

if st.button(
    "🚀 Gerar Cortes com IA",
    type="primary",
    use_container_width=True
):

    if not video_url:

        st.error(
            "Cole o link do YouTube."
        )

        st.stop()

    if not api_key:

        st.error(
            "Informe a chave do Gemini."
        )

        st.stop()

    # --------------------------------------------------------
    # Criar job
    # --------------------------------------------------------

    job = Path(
        tempfile.mkdtemp(
            prefix="job_",
            dir=BASE_DIR
        )
    )

    original = job / "original"
    cortes = job / "cortes"

    original.mkdir()
    cortes.mkdir()

    status = st.status(
        "🚀 Processando...",
        expanded=True
    )

    try:

        # ----------------------------------------------------
        # 1
        # ----------------------------------------------------

        status.write(
            "🔧 Verificando FFmpeg..."
        )

        check_ffmpeg()

        status.write(
            "✅ FFmpeg encontrado."
        )

        # ----------------------------------------------------
        # 2
        # ----------------------------------------------------

        status.write(
            "🔧 Verificando Deno..."
        )

        deno = check_deno()

        if not deno:
            raise RuntimeError(
                "Deno não encontrado."
            )

        status.write(
            f"✅ Deno encontrado: `{deno}`"
        )

        # ----------------------------------------------------
        # 3
        # ----------------------------------------------------

        status.write(
            "📥 1. Baixando vídeo do YouTube..."
        )

        video = download_youtube(
            video_url,
            original
        )

        status.write(
            "✅ Vídeo baixado com sucesso."
        )

        # ----------------------------------------------------
        # 4
        # ----------------------------------------------------

        status.write(
            "🎙️ 2. Transcrevendo com Whisper..."
        )

        transcript = transcribe(
            video
        )

        status.write(
            "✅ Transcrição concluída."
        )

        # ----------------------------------------------------
        # 5
        # ----------------------------------------------------

        status.write(
            "🧠 3. IA escolhendo os melhores cortes..."
        )

        clips = find_clips(
            transcript,
            api_key,
            num_clips
        )

        status.write(
            f"✅ {len(clips)} cortes selecionados."
        )

        # ----------------------------------------------------
        # 6
        # ----------------------------------------------------

        status.write(
            "✂️ 4. Renderizando cortes verticais..."
        )

        generated = []

        for index, clip in enumerate(
            clips
        ):

            output = (
                cortes /
                f"corte_{index + 1}.mp4"
            )

            status.write(
                f"🎬 Corte "
                f"{index + 1}/{len(clips)}..."
            )

            create_clip(
                video,
                clip["start"],
                clip["end"],
                output
            )

            generated.append(
                (
                    clip,
                    output
                )
            )

        # ----------------------------------------------------
        # FINAL
        # ----------------------------------------------------

        status.update(
            label="✅ Cortes finalizados!",
            state="complete",
            expanded=False
        )

        st.divider()

        st.subheader(
            "🎉 Seus Cortes"
        )

        columns = st.columns(
            len(generated)
        )

        for index, (
            clip,
            output
        ) in enumerate(
            generated
        ):

            with columns[index]:

                st.markdown(
                    f"### {clip['title']}"
                )

                st.caption(
                    f"{clip['start']:.1f}s → "
                    f"{clip['end']:.1f}s"
                )

                st.write(
                    f"**🎯 Gancho:** "
                    f"{clip['hook']}"
                )

                st.write(
                    f"**💡 Motivo:** "
                    f"{clip['reason']}"
                )

                st.video(
                    str(output)
                )

                with open(
                    output,
                    "rb"
                ) as file:

                    st.download_button(
                        "⬇️ Baixar corte",
                        data=file,
                        file_name=
                        f"corte_{index + 1}.mp4",
                        mime="video/mp4",
                        key=
                        f"download_{index}"
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
