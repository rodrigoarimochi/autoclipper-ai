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
# CONFIGURAÇÃO DO STREAMLIT
# ============================================================

st.set_page_config(
    page_title="AutoClipper AI",
    page_icon="✂️",
    layout="wide"
)


# ============================================================
# TÍTULO
# ============================================================

st.title("✂️ AutoClipper AI — Gerador de Cortes Inteligentes")

st.markdown(
    "Cole o link do YouTube e gere cortes verticais (9:16) automaticamente com IA."
)


# ============================================================
# CHAVE GEMINI
# ============================================================

GEMINI_API_KEY = st.secrets.get(
    "GEMINI_API_KEY",
    os.getenv("GEMINI_API_KEY", "")
)


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.header("⚙️ Configurações")

    num_clips = st.slider(
        "Quantidade de cortes",
        min_value=1,
        max_value=5,
        value=2
    )

    if not GEMINI_API_KEY:

        api_key = st.text_input(
            "Gemini API Key (Google AI Studio)",
            type="password"
        )

    else:

        api_key = GEMINI_API_KEY

        st.success("🔑 Chave de API conectada!")


# ============================================================
# URL DO YOUTUBE
# ============================================================

video_url = st.text_input(
    "🔗 Cole o link do YouTube:",
    placeholder="https://www.youtube.com/watch?v=..."
)


# ============================================================
# DIRETÓRIO TEMPORÁRIO
# ============================================================

BASE_DIR = Path("autoclipper_jobs")

BASE_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# VERIFICAR FFMPEG
# ============================================================

def check_ffmpeg():

    ffmpeg_path = shutil.which("ffmpeg")

    if not ffmpeg_path:

        raise Exception(
            "FFmpeg não foi encontrado no servidor. "
            "Verifique o arquivo packages.txt."
        )

    return ffmpeg_path


# ============================================================
# VERIFICAR DENO
# ============================================================

def check_deno():

    deno_path = shutil.which("deno")

    if deno_path:

        return deno_path

    try:

        import deno

        deno_path = deno.find_deno_bin()

        if deno_path and os.path.exists(deno_path):

            return deno_path

    except Exception:
        pass

    return None


# ============================================================
# MOSTRAR VERSÕES
# ============================================================

def show_environment():

    try:

        yt_dlp_version = yt_dlp.version.__version__

    except Exception:

        yt_dlp_version = "desconhecida"

    deno_path = check_deno()

    ffmpeg_path = shutil.which("ffmpeg")

    st.write(
        f"**yt-dlp:** `{yt_dlp_version}`"
    )

    if deno_path:

        try:

            result = subprocess.run(
                [deno_path, "--version"],
                capture_output=True,
                text=True,
                timeout=15
            )

            deno_version = result.stdout.strip()

        except Exception:

            deno_version = "instalado"

        st.write(
            f"**Deno:** `{deno_version}`"
        )

    else:

        st.warning(
            "⚠️ Deno não foi encontrado."
        )

    if ffmpeg_path:

        st.write(
            f"**FFmpeg:** `{ffmpeg_path}`"
        )

    else:

        st.warning(
            "⚠️ FFmpeg não foi encontrado."
        )


# ============================================================
# DOWNLOAD DO YOUTUBE
# ============================================================

def download_youtube_video(
    url,
    output_dir
):

    """
    Baixa automaticamente o vídeo do YouTube
    para o servidor.

    O usuário NÃO precisa fazer upload.

    O vídeo é baixado na melhor qualidade disponível
    e fica localmente no servidor para Whisper + FFmpeg.
    """

    output_dir = Path(output_dir)

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    output_template = str(
        output_dir / "%(id)s.%(ext)s"
    )

    deno_path = check_deno()

    if not deno_path:

        raise Exception(
            "Deno não foi encontrado. "
            "O yt-dlp atual precisa de um runtime JavaScript "
            "para o suporte completo ao YouTube."
        )

    st.write(
        "🔧 Deno encontrado. Preparando yt-dlp..."
    )

    # --------------------------------------------------------
    # Configuração principal
    # --------------------------------------------------------

    ydl_opts = {

        # Melhor vídeo + melhor áudio.
        #
        # Se MP4 estiver disponível:
        #   melhor vídeo MP4 + melhor áudio M4A
        #
        # Caso não exista:
        #   usa o melhor formato disponível.
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

        # Deno é informado explicitamente.
        "js_runtimes": {
            "deno": deno_path
        },

        # Não forçamos android/web.
        #
        # O yt-dlp atual escolhe os clientes
        # apropriados.
        "extractor_args": {
            "youtube": {
                "player_client": [
                    "default"
                ]
            }
        }
    }

    # --------------------------------------------------------
    # Download
    # --------------------------------------------------------

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

            # Arquivo esperado após download/merge
            expected_file = (
                output_dir /
                f"{video_id}.mp4"
            )

            # ------------------------------------------------
            # Procurar o arquivo caso o yt-dlp tenha usado
            # outra extensão durante o processo.
            # ------------------------------------------------

            if expected_file.exists():

                return str(
                    expected_file
                )

            possible_files = list(
                output_dir.glob(
                    f"{video_id}.*"
                )
            )

            # Remover arquivos parciais
            possible_files = [
                f
                for f in possible_files
                if not f.name.endswith(
                    ".part"
                )
            ]

            if not possible_files:

                raise Exception(
                    "O yt-dlp informou que o download "
                    "foi concluído, mas o arquivo não "
                    "foi encontrado no servidor."
                )

            # Priorizar MP4
            mp4_files = [
                f
                for f in possible_files
                if f.suffix.lower() == ".mp4"
            ]

            if mp4_files:

                return str(
                    mp4_files[0]
                )

            return str(
                possible_files[0]
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

    model = WhisperModel(
        "tiny",
        device="cpu",
        compute_type="int8"
    )

    return model


def transcribe_video(
    video_path
):

    model = load_whisper()

    segments, info = model.transcribe(
        video_path,
        word_timestamps=True
    )

    formatted_blocks = []

    for segment in segments:

        text = segment.text.strip()

        if not text:

            continue

        formatted_blocks.append(
            f"[{segment.start:.2f}s - "
            f"{segment.end:.2f}s] "
            f"{text}"
        )

    transcript = "\n".join(
        formatted_blocks
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

Escolha exatamente {count} cortes.

REGRAS:

1. Cada corte deve ter entre 20 e 50 segundos.

2. O corte deve começar em um momento interessante.

3. Evite começar no meio de uma frase.

4. O corte deve possuir uma ideia completa.

5. Priorize:
   - curiosidade
   - emoção
   - surpresa
   - opinião forte
   - ensinamento
   - história
   - conflito
   - frase de impacto
   - informação útil

6. Os cortes não devem ser excessivamente parecidos.

7. Use os timestamps presentes na transcrição.

8. Não invente timestamps.

9. O campo start deve ser menor que end.

RETORNE SOMENTE JSON.

Formato obrigatório:

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
            "O Gemini não retornou uma resposta."
        )

    try:

        clips = json.loads(
            response.text
        )

    except json.JSONDecodeError as e:

        raise Exception(
            "O Gemini retornou um JSON inválido:\n\n"
            + response.text
        ) from e

    if not isinstance(
        clips,
        list
    ):

        raise Exception(
            "O Gemini não retornou uma lista de cortes."
        )

    valid_clips = []

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

            if duration < 15:

                continue

            if duration > 60:

                continue

            valid_clips.append(
                {
                    "title": str(
                        clip.get(
                            "title",
                            f"Corte {len(valid_clips) + 1}"
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

    if not valid_clips:

        raise Exception(
            "Nenhum corte válido foi retornado pelo Gemini."
        )

    return valid_clips


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
# RENDERIZA CORTE VERTICAL
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
            "Duração inválida do corte."
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

        # ----------------------------------------------------
        # FORMATO VERTICAL 9:16
        # ----------------------------------------------------

        "-vf",
        (
            "scale=1080:1920:"
            "force_original_aspect_ratio=increase,"
            "crop=1080:1920"
        ),

        # ----------------------------------------------------
        # VÍDEO
        # ----------------------------------------------------

        "-c:v",
        "libx264",

        "-preset",
        "veryfast",

        "-crf",
        "20",

        "-pix_fmt",
        "yuv420p",

        # ----------------------------------------------------
        # ÁUDIO
        # ----------------------------------------------------

        "-c:a",
        "aac",

        "-b:a",
        "192k",

        # ----------------------------------------------------
        # COMPATIBILIDADE WEB
        # ----------------------------------------------------

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

        error_message = result.stderr

        if len(error_message) > 5000:

            error_message = (
                error_message[-5000:]
            )

        raise Exception(
            "FFmpeg encontrou um erro:\n\n"
            + error_message
        )


# ============================================================
# LIMPEZA
# ============================================================

def cleanup_job(
    job_dir
):

    try:

        shutil.rmtree(
            job_dir,
            ignore_errors=True
        )

    except Exception:

        pass


# ============================================================
# BOTÃO PRINCIPAL
# ============================================================

if st.button(
    "🚀 Gerar Cortes com IA",
    type="primary",
    use_container_width=True
):

    # --------------------------------------------------------
    # VALIDAÇÕES
    # --------------------------------------------------------

    if not video_url:

        st.error(
            "❌ Cole o link do YouTube."
        )

        st.stop()

    if not api_key:

        st.error(
            "❌ Configure sua chave da API Gemini."
        )

        st.stop()

    # --------------------------------------------------------
    # CRIAR JOB INDIVIDUAL
    # --------------------------------------------------------

    job_dir = Path(
        tempfile.mkdtemp(
            prefix="job_",
            dir=BASE_DIR
        )
    )

    download_dir = (
        job_dir /
        "original"
    )

    output_dir = (
        job_dir /
        "cortes"
    )

    download_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    status = st.status(
        "🚀 Iniciando processamento...",
        expanded=True
    )

    try:

        # ====================================================
        # ETAPA 0
        # ====================================================

        status.write(
            "🔧 Verificando FFmpeg e Deno..."
        )

        check_ffmpeg()

        deno_path = check_deno()

        if not deno_path:

            raise Exception(
                "Deno não está instalado corretamente."
            )

        status.write(
            "✅ FFmpeg encontrado."
        )

        status.write(
            "✅ Deno encontrado."
        )


        # ====================================================
        # ETAPA 1
        # ====================================================

        status.write(
            "📥 1. Baixando automaticamente "
            "o vídeo do YouTube..."
        )

        video_file = download_youtube_video(
            video_url,
            download_dir
        )

        if not os.path.exists(
            video_file
        ):

            raise Exception(
                "O arquivo do vídeo não foi encontrado."
            )

        file_size = (
            os.path.getsize(
                video_file
            )
            / (1024 * 1024)
        )

        status.write(
            f"✅ Vídeo baixado: "
            f"`{Path(video_file).name}` "
            f"({file_size:.1f} MB)"
        )


        # ====================================================
        # ETAPA 2
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
        # ETAPA 3
        # ====================================================

        status.write(
            "🧠 3. Gemini analisando os "
            "melhores momentos..."
        )

        clips = get_viral_clips(
            transcript,
            api_key,
            num_clips
        )

        status.write(
            f"✅ {len(clips)} momentos encontrados."
        )


        # ====================================================
        # VALIDAR DURAÇÃO
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

                if clip["end"] <= clip["start"]:

                    clip["end"] = min(
                        video_duration,
                        clip["start"] + 30
                    )


        # ====================================================
        # ETAPA 4
        # ====================================================

        status.write(
            f"✂️ 4. Renderizando "
            f"{len(clips)} cortes verticais 9:16..."
        )

        rendered_clips = []

        for index, clip in enumerate(
            clips
        ):

            output_file = (
                output_dir /
                f"corte_{index + 1}.mp4"
            )

            status.write(
                f"🎬 Renderizando corte "
                f"{index + 1}/{len(clips)}..."
            )

            render_vertical_clip(
                video_file,
                clip["start"],
                clip["end"],
                str(output_file)
            )

            if not output_file.exists():

                raise Exception(
                    f"O corte {index + 1} "
                    "não foi criado."
                )

            rendered_clips.append(
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
            len(rendered_clips)
        )

        for index, (
            clip,
            output_file
        ) in enumerate(
            rendered_clips
        ):

            with cols[index]:

                st.markdown(
                    f"### {clip['title']}"
                )

                st.caption(
                    f"⏱️ "
                    f"{clip['start']:.1f}s → "
                    f"{clip['end']:.1f}s"
                )

                hook = clip.get(
                    "hook",
                    ""
                )

                reason = clip.get(
                    "reason",
                    ""
                )

                if hook:

                    st.write(
                        f"**🎯 Gancho:** "
                        f"*{hook}*"
                    )

                if reason:

                    st.write(
                        f"**💡 Motivo:** "
                        f"{reason}"
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
                        f"⬇️ Baixar Corte {index + 1}",

                        data=file,

                        file_name=
                        f"corte_{index + 1}.mp4",

                        mime="video/mp4",

                        key=
                        f"download_{index}"
                    )


    except Exception as error:

        status.update(
            label="❌ Erro durante o processamento",
            state="error",
            expanded=True
        )

        st.error(
            "Ocorreu um erro durante o processamento:"
        )

        st.code(
            str(error)
        )

        st.warning(
            "Se o erro for HTTP 403 do YouTube, "
            "o próximo passo será analisar o log "
            "completo do yt-dlp para identificar "
            "se o bloqueio ocorre na extração "
            "ou no download do formato."
        )
