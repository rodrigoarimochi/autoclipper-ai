import streamlit as st
import os
import json
import subprocess
from faster_whisper import WhisperModel
from google import genai
from google.genai import types
import yt_dlp

st.set_page_config(page_title="AutoClipper AI", page_icon="✂️", layout="wide")

st.title("✂️ AutoClipper AI — Gerador de Cortes Inteligentes")
st.markdown("Cole o link do YouTube e gere cortes verticais (9:16) automaticamente com IA.")

# Carrega a chave dos Secrets ou permite digitar manualmente
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", ""))

with st.sidebar:
    st.header("⚙️ Configurações")
    num_clips = st.slider("Quantidade de cortes", min_value=1, max_value=5, value=2)
    if not GEMINI_API_KEY:
        api_key = st.text_input("Gemini API Key (Google AI Studio)", type="password")
    else:
        api_key = GEMINI_API_KEY
        st.success("🔑 Chave de API conectada!")

video_url = st.text_input("🔗 Cole o link do YouTube:", placeholder="https://www.youtube.com/watch?v=...")

def download_audio_only(url, output_path="audio_temp.m4a"):
    """
    Baixa o stream de áudio disponível com seletor universal resiliente.
    """
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output_path,
        'overwrites': True,
        'quiet': True,
        'no_warnings': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web']
            }
        }
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    return output_path

def get_direct_video_stream(url):
    """
    Obtém a URL do stream de vídeo/áudio direto para o FFmpeg cortar.
    """
    ydl_opts = {
        'format': 'bestvideo+bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web']
            }
        }
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if 'url' in info:
            return info['url']
        elif 'formats' in info and len(info['formats']) > 0:
            return info['formats'][-1]['url']
        raise Exception("Não foi possível resolver o stream direto deste vídeo.")

def transcribe_audio(audio_path):
    model = WhisperModel("tiny", device="cpu", compute_type="int8")
    segments, info = model.transcribe(audio_path, word_timestamps=True)
    
    formatted_blocks = []
    for seg in segments:
        formatted_blocks.append(f"[{seg.start:.2f}s - {seg.end:.2f}s] {seg.text.strip()}")
    return "\n".join(formatted_blocks)

def get_viral_clips(transcript, gemini_key, count=2):
    client = genai.Client(api_key=gemini_key)
    prompt = f"""
    Você é um editor sênior de cortes virais para TikTok, Reels e Shorts.
    Analise a transcrição com marcações de tempo e encontre os {count} melhores momentos (entre 20 e 50 segundos).
    
    Retorne ESTRITAMENTE um JSON com esta estrutura:
    [
      {{
        "title": "Título chamativo",
        "start": 10.5,
        "end": 42.0,
        "hook": "Frase de impacto inicial",
        "reason": "Por que esse corte vai prender a atenção"
      }}
    ]
    
    Transcrição:
    {transcript}
    """
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json")
    )
    return json.loads(response.text)

def render_vertical_clip_from_stream(stream_url, start, end, output_file):
    duration = end - start
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", stream_url,
        "-t", str(duration),
        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
        "-c:a", "aac", "-b:a", "128k",
        output_file
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

if st.button("🚀 Gerar Cortes com IA", type="primary", use_container_width=True):
    if not video_url:
        st.error("Por favor, cole o link do YouTube.")
    elif not api_key:
        st.error("Por favor, insira sua chave do Gemini na barra lateral ou configure nos Secrets.")
    else:
        status = st.status("Processando vídeo do YouTube...", expanded=True)
        try:
            status.write("📥 1. Extraindo áudio do vídeo...")
            audio_file = "audio_temp.m4a"
            download_audio_only(video_url, audio_file)
            
            status.write("🎙️ 2. Transcrevendo áudio com Whisper...")
            transcript = transcribe_audio(audio_file)
            
            status.write("🧠 3. IA identificando os melhores momentos virais...")
            clips = get_viral_clips(transcript, api_key, count=num_clips)
            
            status.write("🌐 4. Obtendo stream de vídeo...")
            stream_url = get_direct_video_stream(video_url)
            
            status.write(f"✂️ 5. Renderizando {len(clips)} cortes verticais em 9:16...")
            os.makedirs("cortes", exist_ok=True)
            
            status.update(label="✅ Todos os cortes foram finalizados com sucesso!", state="complete", expanded=False)
            
            st.divider()
            st.subheader("🎉 Seus Cortes Prontos:")
            
            cols = st.columns(len(clips))
            for i, clip in enumerate(clips):
                out_path = f"cortes/corte_{i+1}.mp4"
                render_vertical_clip_from_stream(stream_url, clip["start"], clip["end"], out_path)
                
                with cols[i]:
                    st.markdown(f"### {clip['title']}")
                    st.caption(f"⏱️ {clip['start']}s até {clip['end']}s")
                    hook_text = clip.get('hook', '')
                    st.write(f"**Gancho:** *{hook_text}*")
                    st.write(f"**Motivo:** {clip.get('reason', '')}")
                    if os.path.exists(out_path):
                        st.video(out_path)
                        with open(out_path, "rb") as f:
                            st.download_button(
                                label=f"⬇️ Baixar Corte {i+1}",
                                data=f,
                                file_name=f"corte_{i+1}.mp4",
                                mime="video/mp4",
                                key=f"btn_dl_{i}"
                            )
        except Exception as e:
            status.update(label="❌ Erro durante o processamento", state="error")
            st.error(f"Ocorreu um erro: {e}")
