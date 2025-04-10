# 버전 2.1.2
# 작성일: 2025-04-10
import os
import re
import logging
import time
import json
import requests
from flask import Flask, render_template, request, send_file, jsonify
from google.cloud import translate_v2 as translate
from dotenv import load_dotenv
import openai

# .env 파일 로드 (환경 변수 설정)
load_dotenv()

# 구글 클라우드 번역 API 클라이언트 전역 생성
translate_client = translate.Client()

# 토큰($...$) 보존: 토큰을 임시 플레이스홀더로 치환
def preserve_tokens(text):
    token_pattern = re.compile(r'(\$[^$]*\$)')
    tokens = token_pattern.findall(text)
    placeholders = {}
    for i, token in enumerate(tokens):
        placeholder = f"__TOKEN_{i}__"
        placeholders[placeholder] = token
        text = text.replace(token, placeholder)
    return text, placeholders

# 치환된 토큰 복원
def restore_tokens(text, placeholders):
    for ph, token in placeholders.items():
        text = text.replace(ph, token)
    return text

# 파라독스 로컬라이제이션 파일 로드 및 파싱
def load_paradox_localization_file(file_path):
    with open(file_path, 'r', encoding='utf-8-sig') as file:
        content = file.read()
    
    # 언어 코드 추출 (예: l_english)
    language_match = re.search(r'(l_\w+):', content)
    language_code = language_match.group(1) if language_match else 'l_english'
    
    # 키-값 쌍 추출
    result = {language_code: {}}
    lines = content.split('\n')
    
    for line in lines:
        line = line.strip()
        # 주석, 빈 줄, 혹은 언어 헤더(l_*)는 건너뜀
        if not line or line.startswith('#') or re.match(r'l_\w+:', line):
            continue
        #match = re.match(r'^([^:]+:\s*\d*\s*)"(.+)"', line)
        # 키-값 쌍 파싱 (예: cheat_category:0 "텍스트")
        match = re.match(r'^([^:]+:\s*\d*\s*)"(.+)"', line)
        if match:
            key_part = match.group(1)
            value_text = match.group(2)
            key = key_part.strip()
            result[language_code][key] = f'"{value_text}"'
    
    return result

# OpenAI API를 사용한 텍스트 번역
def translate_with_openai(text, target_language, api_key, model="gpt-3.5-turbo"):
    if not text.strip():
        return text
    
    openai.api_key = api_key
    
    # 언어 코드를 전체 언어 이름으로 변환
    language_names = {
        'ko': 'Korean', 'en': 'English', 'ja': 'Japanese', 
        'zh': 'Chinese', 'es': 'Spanish', 'fr': 'French',
        'de': 'German', 'ru': 'Russian', 'it': 'Italian', 'pt': 'Portuguese'
    }
    target_lang_name = language_names.get(target_language, target_language)
    
    try:
        response = openai.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": f"""You are a professional game localization translator. Your task is to translate the following text into {target_lang_name} accurately and naturally.

Important instructions:
1. DO NOT translate anything between $ symbols (e.g., $PARAM$, $VALUE$). Keep these exactly as they are.
2. These $ tokens are game variables that should remain untouched.
3. Translate the rest of the text naturally and in a game-appropriate style.
4. Preserve any formatting in the text.
5. Do not add any additional commentary or explanations."""},
                {"role": "user", "content": text}
            ],
            temperature=0.3,
            max_tokens=1024
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"OpenAI API 번역 오류: {e}")
        return text

# Ollama API를 사용한 텍스트 번역
def translate_with_ollama(text, target_language, endpoint="http://localhost:11434", model="llama2"):
    if not text.strip():
        return text
    
    # 언어 코드를 전체 언어 이름으로 변환
    language_names = {
        'ko': 'Korean', 'en': 'English', 'ja': 'Japanese', 
        'zh': 'Chinese', 'es': 'Spanish', 'fr': 'French',
        'de': 'German', 'ru': 'Russian', 'it': 'Italian', 'pt': 'Portuguese'
    }
    target_lang_name = language_names.get(target_language, target_language)
    
    try:
        response = requests.post(
            f"{endpoint}/api/generate",
            headers={"Content-Type": "application/json"},
            json={
                "model": model,
                "prompt": f"""You are a professional game localization translator. Your task is to translate the following text into {target_lang_name} accurately and naturally.

Important instructions:
1. DO NOT translate anything between $ symbols (e.g., $PARAM$, $VALUE$). Keep these exactly as they are.
2. These $ tokens are game variables that should remain untouched.
3. Translate the rest of the text naturally and in a game-appropriate style.
4. Preserve any formatting in the text.
5. Do not add any additional commentary or explanations.

Text to translate: \"{text}\"

Translation:""",
                "stream": False
            }
        )
        
        if response.status_code == 200:
            result = response.json()
            # Ollama의 응답에서 번역된 텍스트 추출
            translated_text = result.get('response', '').strip()
            # 따옴표로 둘러싸인 텍스트 추출 시도
            match = re.search(r'"([^"]+)"', translated_text)
            if match:
                return match.group(1)
            return translated_text
        else:
            logging.error(f"Ollama API 오류: {response.status_code} - {response.text}")
            return text
    except Exception as e:
        logging.error(f"Ollama API 번역 오류: {e}")
        return text

# 구글 클라우드 번역 API를 사용한 번역
def translate_with_google(text, target_language):
    if not text.strip():
        return text
    
    # 구글 번역의 경우 토큰 보존을 위해 플레이스홀더 처리
    text_to_translate, placeholders = preserve_tokens(text)
    
    try:
        result = translate_client.translate(text_to_translate, target_language=target_language)
        translated_text = result['translatedText']
        # 토큰 복원
        translated_text = restore_tokens(translated_text, placeholders)
        return translated_text
    except Exception as e:
        logging.error(f"Google 번역 API 오류: {e}")
        return text

# 파라독스 로컬라이제이션 파일 번역 (각 항목의 따옴표 내부 텍스트만 번역)
def translate_paradox_file(file_path, target_language, translation_api="google", api_settings=None, progress_callback=None):
    data = load_paradox_localization_file(file_path)
    total_items = sum(len(lang_data) for lang_data in data.values())
    translation_progress = 0

    # 번역할 항목 수집: (lang_code, key, original_text)
    tasks = []
    result = {}
    for lang_code, lang_data in data.items():
        result.setdefault(lang_code, {})
        for key, value in lang_data.items():
            if isinstance(value, str) and value.startswith('"') and value.endswith('"'):
                original_text = value.strip('"')
                tasks.append((lang_code, key, original_text))
            else:
                result[lang_code][key] = value

    # 번역 처리
    if translation_api == "google":
        # 구글 번역: 배치 처리
        batch_size = 128
        translated_results = []
        texts_to_translate = [task[2] for task in tasks if task[2].strip()]
        for i in range(0, len(texts_to_translate), batch_size):
            batch_texts = texts_to_translate[i:i+batch_size]
            try:
                batch_results = []
                for text in batch_texts:
                    # 각 항목마다 개별적으로 토큰 처리 및 번역
                    translated_text = translate_with_google(text, target_language)
                    batch_results.append({'translatedText': translated_text})
            except Exception as e:
                logging.error(f"번역 API 호출 실패: {e}")
                batch_results = []
                for text in batch_texts:
                    try:
                        translated_text = translate_with_google(text, target_language)
                        batch_results.append({'translatedText': translated_text})
                    except Exception as ex:
                        logging.error(f"개별 번역 실패: {ex}")
                        batch_results.append({'translatedText': text})
            translated_results.extend(batch_results)

        # 번역 결과를 각 항목에 적용
        translation_index = 0
        for task in tasks:
            lang_code, key, original_text = task
            if original_text.strip():
                translated_text = translated_results[translation_index]['translatedText']
                translation_index += 1
                result[lang_code][key] = f'"{translated_text}"'
            else:
                result[lang_code][key] = f'"{original_text}"'
            translation_progress += 1
            if progress_callback:
                progress_callback(translation_progress, total_items, key)
    else:
        # AI 번역 (OpenAI 또는 Ollama): 항목별 개별 처리
        for task in tasks:
            lang_code, key, original_text = task
            
            # 현재 번역 중인 항목 정보 업데이트
            if progress_callback:
                progress_callback(translation_progress, total_items, key)
            
            if original_text.strip():
                # API에 따라 번역 함수 선택 (AI 번역에서는 토큰 처리를 별도로 하지 않음)
                if translation_api == "openai":
                    api_key = api_settings.get("openai_api_key", "")
                    model = api_settings.get("openai_model", "gpt-3.5-turbo")
                    translated_text = translate_with_openai(original_text, target_language, api_key, model)
                elif translation_api == "ollama":
                    endpoint = api_settings.get("ollama_endpoint", "http://localhost:11434")
                    model = api_settings.get("ollama_model", "llama2")
                    translated_text = translate_with_ollama(original_text, target_language, endpoint, model)
                else:
                    # 기본값은 구글 번역
                    translated_text = translate_with_google(original_text, target_language)
                
                result[lang_code][key] = f'"{translated_text}"'
            else:
                result[lang_code][key] = f'"{original_text}"'
            
            translation_progress += 1
            if progress_callback:
                progress_callback(translation_progress, total_items, key)
            
            # AI 번역은 속도 제한을 위해 간격 추가
            if translation_api != "google":
                time.sleep(0.5)  # 0.5초 간격으로 API 호출
    
    return result

# 번역된 데이터를 파라독스 로컬라이제이션 파일 형식으로 저장 (원본 파일명 유지)
def save_paradox_localization(translated_data, original_filename):
    os.makedirs('downloads', exist_ok=True)
    output_path = os.path.join('downloads', original_filename)
    
    with open(output_path, 'w', encoding='utf-8-sig') as file:
        for lang_code, lang_data in translated_data.items():
            file.write(f"{lang_code}:\n")
            for key, value in lang_data.items():
                file.write(f" {key} {value}\n")
    
    return output_path

# Flask 웹 애플리케이션 설정
app = Flask(__name__)

# 진행률 저장을 위한 전역 변수
translation_progress = {
    "current": 0, 
    "total": 100, 
    "current_count": 0, 
    "total_count": 100,
    "current_item": ""
}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    global translation_progress
    # 여러 파일 업로드 처리
    files = request.files.getlist('file')
    if not files or len(files) == 0:
        return jsonify({"error": "파일이 선택되지 않았습니다."})
    
    target_language = request.form['language']
    translation_api = request.form.get('translationApi', 'google')
    
    # API 설정 정보 수집
    api_settings = {}
    if translation_api == "openai":
        api_settings = {
            "openai_api_key": request.form.get('openaiApiKey', ''),
            "openai_model": request.form.get('openaiModel', 'gpt-3.5-turbo')
        }
        if not api_settings["openai_api_key"]:
            return jsonify({"error": "OpenAI API 키가 필요합니다."})
    elif translation_api == "ollama":
        api_settings = {
            "ollama_endpoint": request.form.get('ollamaEndpoint', 'http://localhost:11434'),
            "ollama_model": request.form.get('ollamaModel', 'llama2')
        }
    
    download_urls = []
    
    # 파일마다 개별적으로 번역 처리 (순차적으로 처리)
    for file in files:
        if file.filename == '':
            continue
        
        os.makedirs('uploads', exist_ok=True)
        file_path = os.path.join('uploads', file.filename)
        file.save(file_path)
        
        # 진행률 초기화
        translation_progress = {"current": 0, "total": 100, "current_count": 0, "total_count": 100, "current_item": ""}
        
        def progress_callback(processed, total, current_key=""):
            global translation_progress
            translation_progress["current"] = int((processed / total) * 100)
            translation_progress["current_count"] = processed
            translation_progress["total_count"] = total
            translation_progress["current_item"] = current_key
            logging.info(f"[{file.filename}] 번역 진행률: {processed}/{total} ({translation_progress['current']}%) - {current_key}")
        
        try:
            if file.filename.endswith('.yml'):
                translated_data = translate_paradox_file(
                    file_path, 
                    target_language,
                    translation_api,
                    api_settings,
                    progress_callback
                )
                output_file_path = save_paradox_localization(translated_data, file.filename)
                download_url = f"/download/{file.filename}"
                download_urls.append(download_url)
            else:
                logging.error(f"{file.filename}은(는) 지원하지 않는 파일 형식입니다.")
        except Exception as e:
            logging.error(f"{file.filename} 번역 처리 중 오류 발생: {e}")
    
    if not download_urls:
        return jsonify({"error": "번역할 수 있는 파일이 없습니다."})
    
    # 여러 파일이면 리스트로, 단일 파일이면 단일 URL 반환
    return jsonify({"download_urls": download_urls})

@app.route('/progress')
def get_progress():
    global translation_progress
    return jsonify({
        "progress": translation_progress["current"],
        "current_count": translation_progress["current_count"],
        "total_count": translation_progress["total_count"],
        "current_item": translation_progress["current_item"]
    })

@app.route('/download/<filename>')
def download_file(filename):
    output_path = os.path.join('downloads', filename)
    return send_file(output_path, as_attachment=True)

if __name__ == "__main__":
    if not os.path.exists('uploads'):
        os.makedirs('uploads')
    
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    app.run(debug=True)
