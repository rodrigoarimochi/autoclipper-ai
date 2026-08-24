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


# ============================================================
# CONFIGURAÇÃO
# ============================================================

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
# DIRETÓRIO DOS JOBS
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
            "FFmpeg não foi encontrado no servidor."
        )

    return path


# ============================================================
# DENO
# ============================================================

def check_deno():

    # Primeiro tenta PATH
    path = shutil.which("deno")

    if path:
        return path

    # Depois tenta o pacote Python deno
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
# DOWNLOAD DO YOUTUBE
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
    # CONFIGURAÇÃO DO YT-DLP
    # ========================================================

    ydl_opts = {

        # Melhor vídeo + melhor áudio
        "format": (
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]"
            "/bestvideo+bestaudio"
            "/best[ext=mp4]"
            "/best"
        ),

        "outtmpl": output_template,

        "merge_output_format": "mp4",

        "noplaylist": True,

        "overwrites": True,

        "retries": 10,

        "fragment_retries": 10,

        "file_access_retries": 5,

        "extractor_retries": 5,

        "concurrent_fragment_downloads": 1,

        "quiet": False,

        "no_warnings": False,

        "ignoreerrors": False,

        # ====================================================
        # DENO
        # ====================================================

        "js_runtimes": {
            "deno": {
                "path": deno_path
            }
        },

        # ====================================================
        # EJS
        # ====================================================

        "remote_components": {
            "ejs": "github"
        }
    }

    # ========================================================
    # EXECUTAR DOWNLOAD
    # ========================================================

    try:

        with yt_dlp.YoutubeDL(
            ydl_opts
        ) as ydl:

            info = ydl.extract_info(
                url,
                download=True
            )

            if not info:

                raise Exception(
                    "O YouTube não retornou informações do vídeo."
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
                f"🎬 Vídeo encontrado: **{title}**"
            )

            # =================================================
            # PROCURAR ARQUIVO FINAL
            # =================================================

            expected_mp4 = (
                output_dir /
                f"{video_id}.mp4"
            )

            if expected_mp4.exists():

                return str(
                    expected_mp4
                )

            files = list(
                output_dir.glob(
                    f"{video_id}.*"
                )
            )

            files = [
                f
                for f in files
                if not f.name.endswith(".part")
            ]

            if not files:

                raise Exception(
                    "O download foi iniciado, "
                    "mas nenhum arquivo foi encontrado."
                )

            # Prioriza MP4
            mp4_files = [
                f
                for f in files
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
            "Falha ao baixar o vídeo do YouTube:\n\n"
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
            "O Whisper não encontrou fala no vídeo."
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

REGRAS:

- Cada corte deve ter entre 20 e 50 segundos.
- Não comece no meio de uma frase.
- O trecho deve possuir uma ideia completa.
- Priorize emoção, curiosidade, surpresa,
  opinião forte, ensinamento, história,
  conflito ou informação útil.
- Evite cortes muito parecidos.
- Use SOMENTE os timestamps existentes.
- Não invente timestamps.
- start precisa ser menor que end.

Retorne SOMENTE JSON.

Formato:

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
            "O Gemini não retornou resposta."
        )

    try:

        clips = json.loads(
            response.text
        )

    except json.JSONDecodeError:

        raise Exception(
            "O Gemini retornou JSON inválido:\n\n"
            + response.text
        )

    if not isinstance(
        clips,
        list
    ):

        raise Exception(
            "Resposta do Gemini não é uma lista."
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

            if end <= start:
                continue

            duration = end - start

            if duration < 20:
                continue

            if duration > 50:
                continue

            valid.append(
                {
                    "title": str(
                        clip.get(
                            "title",
                            f"Corte {len(valid) + 1}"
                        )
                    ),
                    "start": start,
                    "end": end,
                    "hook": str(
                        clip.get(
                            "hook",
                            ""
                        )
                    ),
                    "reason": str(
                        clip.get(
                            "reason",
                            ""
                        )
                    )
                }
            )

        except (
            KeyError,
            TypeError,
            ValueError
        ):

            continue

    if not valid:

        raise Exception(
            "O Gemini não encontrou cortes válidos."
        )

    return valid


# ============================================================
# DURAÇÃO DO VÍDEO
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

    if result.returncode != 0:

        return None

    try:

        return float(
            result.stdout.strip()
        )

    except ValueError:

        return None


# ============================================================
# RENDERIZA CORTE
# ============================================================

def render_vertical_clip(
    video_file,
    start,
    end,
    output_file
):

    duration = end - start

    if duration <= 0:

        raise Exception(
            "Duração inválida."
        )

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

        error = result.stderr

        if len(error) > 5000:

            error = error[-5000:]

        raise Exception(
            "FFmpeg falhou:\n\n"
            + error
        )


# ============================================================
# BOTÃO PRINCIPAL
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
            "❌ Configure sua chave do Gemini."
        )

        st.stop()

    # ========================================================
    # JOB INDIVIDUAL
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
        # 1. VERIFICAÇÃO
        # ====================================================

        status.write(
            "🔧 Verificando FFmpeg..."
        )

        check_ffmpeg()

        status.write(
            "✅ FFmpeg encontrado."
        )

        status.write(
            "🔧 Verificando Deno..."
        )

        deno_path = check_deno()

        if not deno_path:

            raise Exception(
                "Deno não foi encontrado."
            )

        status.write(
            f"✅ Deno encontrado: `{deno_path}`"
        )


        # ====================================================
        # 2. DOWNLOAD
        # ====================================================

        status.write(
            "📥 1. Baixando automaticamente "
            "o vídeo do YouTube..."
        )

        video_file = download_youtube_video(
            video_url,
            original_dir
        )

        if not os.path.exists(
            video_file
        ):

            raise Exception(
                "Arquivo de vídeo não encontrado."
            )

        size_mb = (
            os.path.getsize(
                video_file
            ) / 1024 / 1024
        )

        status.write(
            f"✅ Download concluído: "
            f"{size_mb:.1f} MB"
        )


        # ====================================================
        # 3. WHISPER
        # ====================================================

        status.write(
            "🎙️ 2. Transcrevendo com Whisper..."
        )

        transcript = transcribe_video(
            video_file
        )

        status.write(
            "✅ Transcrição concluída."
        )


        # ====================================================
        # 4. GEMINI
        # ====================================================

        status.write(
            "🧠 3. Gemini analisando "
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
        # 5. AJUSTAR TIMESTAMPS
        # ====================================================

        video_duration = get_video_duration(
            video_file
        )

        if video_duration:

            for clip in clips:

                if clip["start"] >= video_duration:

                    clip["start"] = max(
                        0,
                        video_duration - 30
                    )

                if clip["end"] > video_duration:

                    clip["end"] = video_duration


        # ====================================================
        # 6. RENDER
        # ====================================================

        status.write(
            f"✂️ 4. Renderizando "
            f"{len(clips)} cortes em 9:16..."
        )

        rendered = []

        for i, clip in enumerate(
            clips
        ):

            output_file = (
                clips_dir /
                f"corte_{i + 1}.mp4"
            )

            status.write(
                f"🎬 Corte "
                f"{i + 1}/{len(clips)}..."
            )

            render_vertical_clip(
                video_file,
                clip["start"],
                clip["end"],
                str(output_file)
            )

            if not output_file.exists():

                raise Exception(
                    f"Corte {i + 1} não foi criado."
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
            label="✅ Todos os cortes foram finalizados!",
            state="complete",
            expanded=False
        )


        # ====================================================
        # RESULTADOS
        # ====================================================

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
                ) as file:

                    st.download_button(
                        label=
                        f"⬇️ Baixar Corte {i + 1}",
                        data=file,
                        file_name=
                        f"corte_{i + 1}.mp4",
                        mime="video/mp4",
                        key=
                        f"download_{i}"
                    )


    except Exception as e:

        status.update(
            label="❌ Erro durante o processamento",
            state="error",
            expanded=True
        )

        st.error(
            "Corrigimos um erro durante o processamento:"
        )

        st.code(
            str(e)
        )
