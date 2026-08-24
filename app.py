import streamlit as st
import os
import json
import subprocess
import requests
import re
from faster_whisper import WhisperModel
from google import genai
from google.genai import types

st.set_page_config(page_title="AutoClipper AI", page_icon="✂️", layout="wide")

st.title("✂️ AutoClipper AI — Gerador de Cortes Inteligentes")
st.markdown("Cole o link do YouTube e gere cortes verticais (9:16) automaticamente com IA.")

# Barra lateral para configurações
with st.sidebar:
    st.header("⚙️ Configurações")
    api_key = st.text_input("Gemini API Key (Google AI Studio)", type="password", help="Pegue gratuitamente em aistudio.google.com")
    num_clips = st.slider("Quantidade de cortes", min_value=1, max_value=5, value=2)

video_url = st.text_input("🔗 Cole o link do YouTube:", placeholder="https://www.youtube.com/watch?v=...")

def extract_video_id(url):
    pattern = r'(?:v=|/|youtu\.be/)([0-9A-Za-z_-]{11})'
    match = re.search(pattern, url)
    return match.group(1) if match else None

def download_youtube_via_proxy(url, output_path="input_video.mp4"):
    """
    Bypass anti-bloqueio 403 usando streams diretos de CDN.
    """
    video_id = extract_video_id(url)
    if not video_id:
        raise Exception("ID do vídeo inválido. Verifique o link fornecido.")

    instances = [
        f"https://api.piped.privacydev.net/streams/{video_id}",
        f"https://pipedapi.kavin.rocks/streams/{video_id}",
        f"https://api.piped.yt/streams/{video_id}",
        f"https://inv.tux.pizza/api/v1/videos/{video_id}",
        f"https://invidious.nerdvpn.de/api/v1/videos/{video_id}"
    ]

    download_stream_url = None

    for api_endpoint in instances:
        try:
            r = requests.get(api_endpoint, timeout=6)
            if r.status_code == 200:
                data = r.json()
                
                # Resolução Piped API
                if "videoStreams" in data:
                    for s in data["videoStreams"]:
                        if s.get("format") == "MPEG_4" and s.get("videoOnly") is False:
                            download_stream_url = s.get("url")
                            break
                    if not download_stream_url and len(data["videoStreams"]) > 0:
                        download_stream_url = data["videoStreams"][0].get("url")

                # Resolução Invidious API
                elif "formatStreams" in data:
                    for s in data["formatStreams"]:
                        if "video/mp4" in s.get("type", ""):
                            download_stream_url = s.get("url")
                            break
                
                if download_stream_url:
                    break
        except Exception:
            continue

    if not download_stream_url:
        import yt_dlp
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': output_path,
            'overwrites': True,
            'quiet': True,
            'extractor_args': {'youtube': {'player_client': ['tv_embedded', 'android']}}
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return output_path

    # Baixa o fluxo sem restrição de IP
    stream_res = requests.get(download_stream_url, stream=True, timeout=120)
    if stream_res.status_code == 200:
        with open(output_path, "wb") as f:
            for chunk in stream_res.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
        return output_path
    else:
        raise Exception(f"Falha ao baixar vídeo pela CDN (Status: {stream_res.status_code})")

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
    if not video_url:
        st.error("Por favor, cole o link do YouTube.")
    elif not api_key:
        st.error("Por favor, insira sua chave gratuita do Gemini na barra lateral.")
    else:
        status = st.status("Processando vídeo do YouTube...", expanded=True)
        try:
            video_file = "downloaded_video.mp4"
            
            status.write("📥 1. Baixando vídeo via stream direto...")
            download_youtube_via_proxy(video_url, video_file)
            
            status.write("🎙️ 2. Transcrevendo áudio com Whisper...")
            transcript = transcribe_audio(video_file)
            
            status.write("🧠 3. IA identificando os momentos virais...")
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
