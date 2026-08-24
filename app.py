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
st.markdown("Transforme vídeos em cortes virais verticais (9:16) automaticamente com IA.")

# Barra lateral para configurações
with st.sidebar:
    st.header("⚙️ Configurações")
    api_key = st.text_input("Gemini API Key (Google AI Studio)", type="password", help="Pegue gratuitamente em aistudio.google.com")
    num_clips = st.slider("Quantidade de cortes", min_value=1, max_value=5, value=2)
    st.info("Dica: Se o YouTube bloquear algum link, use a aba de upload direto.")

# Abas de entrada: Link ou Upload direto
tab1, tab2 = st.tabs(["🔗 Link do YouTube", "📁 Upload de Arquivo MP4"])

with tab1:
    video_url = st.text_input("Cole o link do YouTube:", placeholder="https://www.youtube.com/watch?v=...")

with tab2:
    uploaded_file = st.file_uploader("Ou envie um vídeo do seu computador/celular:", type=["mp4", "mov", "mkv"])

def download_video(url, output_path="input_video.mp4"):
    # Configuração de bypass para contornar o erro 403 Forbidden do YouTube
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': output_path,
        'overwrites': True,
        'quiet': True,
        'no_warnings': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        }
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    return output_path

def transcribe_audio(video_path):
    model = WhisperModel("tiny", device="cpu", compute_type="int8")
    segments, info = model.transcribe(video_path, word_timestamps=True)
    
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

def render_vertical_clip(input_video, start, end, output_file):
    duration = end - start
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", input_video,
        "-t", str(duration),
        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
        "-c:a", "aac", "-b:a", "128k",
        output_file
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

if st.button("🚀 Gerar Cortes com IA", type="primary", use_container_width=True):
    if not api_key:
        st.error("Por favor, insira sua chave gratuita do Gemini na barra lateral.")
    elif not video_url and not uploaded_file:
        st.error("Por favor, insira o link do YouTube ou faça upload de um vídeo.")
    else:
        status = st.status("Processando vídeo...", expanded=True)
        try:
            video_file = "downloaded_video.mp4"
            
            if uploaded_file is not None:
                status.write("📥 1. Carregando vídeo enviado...")
                with open(video_file, "wb") as f:
                    f.write(uploaded_file.getbuffer())
            else:
                status.write("📥 1. Baixando vídeo do YouTube com bypass de segurança...")
                download_video(video_url, video_file)
            
            status.write("🎙️ 2. Transcrevendo áudio com Whisper...")
            transcript = transcribe_audio(video_file)
            
            status.write("🧠 3. IA analisando ganchos e momentos virais...")
            clips = get_viral_clips(transcript, api_key, count=num_clips)
            
            status.write(f"✂️ 4. Renderizando {len(clips)} cortes verticais em 9:16...")
            os.makedirs("cortes", exist_ok=True)
            
            status.update(label="✅ Todos os cortes foram finalizados com sucesso!", state="complete", expanded=False)
            
            st.divider()
            st.subheader("🎉 Seus Cortes Prontos:")
            
            cols = st.columns(len(clips))
            for i, clip in enumerate(clips):
                out_path = f"cortes/corte_{i+1}.mp4"
                render_vertical_clip(video_file, clip["start"], clip["end"], out_path)
                
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
