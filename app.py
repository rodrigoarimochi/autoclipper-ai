import streamlit as st
import os
import json
import subprocess
import requests
from faster_whisper import WhisperModel
from google import genai
from google.genai import types
import yt_dlp

st.set_page_config(page_title="AutoClipper AI", page_icon="✂️", layout="wide")

st.title("✂️ AutoClipper AI — Gerador de Cortes Inteligentes")
st.markdown("Cole apenas o link do YouTube e gere cortes verticais (9:16) automaticamente com IA.")

# Barra lateral para configurações
with st.sidebar:
    st.header("⚙️ Configurações")
    api_key = st.text_input("Gemini API Key (Google AI Studio)", type="password", help="Pegue gratuitamente em aistudio.google.com")
    num_clips = st.slider("Quantidade de cortes", min_value=1, max_value=5, value=2)

video_url = st.text_input("🔗 Cole o link do YouTube:", placeholder="https://www.youtube.com/watch?v=...")

def download_video_robust(url, output_path="input_video.mp4"):
    """
    Bypass anti-bloqueio 403 do YouTube para servidores em nuvem.
    """
    # 1. Tentativa via API de túnel aberta
    try:
        cobalt_instances = [
            "https://api.cobalt.tools/api/json",
            "https://cobalt-api.kwiatekm.pl/api/json",
            "https://api.hyper.lol/api/json"
        ]
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0"
        }
        payload = {
            "url": url,
            "vQuality": "720",
            "vCodec": "h264"
        }
        for instance in cobalt_instances:
            try:
                res = requests.post(instance, json=payload, headers=headers, timeout=8)
                if res.status_code == 200:
                    data = res.json()
                    direct_url = data.get("url")
                    if direct_url:
                        v_res = requests.get(direct_url, stream=True, timeout=60)
                        if v_res.status_code == 200:
                            with open(output_path, "wb") as f:
                                for chunk in v_res.iter_content(chunk_size=8192):
                                    f.write(chunk)
                            return output_path
            except Exception:
                continue
    except Exception:
        pass

    # 2. Fallback via yt-dlp emulando iOS/Mobile
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': output_path,
        'overwrites': True,
        'quiet': True,
        'no_warnings': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'mweb', 'android']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1'
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
    if not video_url:
        st.error("Por favor, cole o link do YouTube.")
    elif not api_key:
        st.error("Por favor, insira sua chave gratuita do Gemini na barra lateral.")
    else:
        status = st.status("Processando vídeo do YouTube...", expanded=True)
        try:
            video_file = "downloaded_video.mp4"
            
            status.write("📥 1. Baixando vídeo com bypass automático...")
            download_video_robust(video_url, video_file)
            
            status.write("🎙️ 2. Transcrevendo áudio com Whisper...")
            transcript = transcribe_audio(video_file)
            
            status.write("🧠 3. IA identificando os momentos virais...")
            clips = get_viral_clips(transcript, api_key, count=num_clips)
            
            status.write(f"✂️ 4. Renderizando {len(clips)} cortes em 9:16...")
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
