# 만약 번역 하는곳이 $ 같은거 있으면 번역 잘 안됩니다 언젠간 고칠게요

import os
import re
import logging
from flask import Flask, render_template, request, send_file, jsonify
from google.cloud import translate_v2 as translate
from dotenv import load_dotenv

# .env 파일 로드 (환경 변수 설정)
load_dotenv()

# 구글 클라우드 번역 API 클라이언트 전역 생성
translate_client = translate.Client()

# 토큰($...$) 보존: 토큰을 임시 플레이스홀더로 치환
def preserve_tokens(text):
    token_pattern = re.compile(r'(\$[^$]+\$)')
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
        
        # 키-값 쌍 파싱 (예: cheat_category:0 "텍스트")
        match = re.match(r'^([^:]+:\s*\d+\s*)"(.+)"', line)
        if match:
            key_part = match.group(1)
            value_text = match.group(2)
            key = key_part.strip()
            result[language_code][key] = f'"{value_text}"'
    
    return result

# 파라독스 로컬라이제이션 파일 번역 (각 항목의 따옴표 내부 텍스트만 번역)
def translate_paradox_file(file_path, target_language, progress_callback):
    data = load_paradox_localization_file(file_path)
    total_items = sum(len(lang_data) for lang_data in data.values())
    translation_progress = 0

    # 번역할 항목 수집: (lang_code, key, original_text, text_to_translate, placeholders)
    tasks = []
    result = {}
    for lang_code, lang_data in data.items():
        result.setdefault(lang_code, {})
        for key, value in lang_data.items():
            if isinstance(value, str) and value.startswith('"') and value.endswith('"'):
                original_text = value.strip('"')
                text_to_translate, placeholders = preserve_tokens(original_text)
                tasks.append((lang_code, key, original_text, text_to_translate, placeholders))
            else:
                result[lang_code][key] = value

    # 배치 번역: 텍스트 목록을 API 최대 128개 제한에 맞게 배치 분할
    batch_size = 128
    translated_results = []
    texts_to_translate = [task[3] for task in tasks if task[3].strip()]
    for i in range(0, len(texts_to_translate), batch_size):
        batch_texts = texts_to_translate[i:i+batch_size]
        try:
            batch_results = translate_client.translate(batch_texts, target_language=target_language)
        except Exception as e:
            logging.error(f"번역 API 호출 실패: {e}")
            batch_results = []
            for text in batch_texts:
                try:
                    batch_results.append(translate_client.translate(text, target_language=target_language))
                except Exception as ex:
                    logging.error(f"개별 번역 실패: {ex}")
                    batch_results.append({'translatedText': text})
        translated_results.extend(batch_results)

    # 번역 결과를 각 항목에 적용
    translation_index = 0
    for task in tasks:
        lang_code, key, original_text, text_to_translate, placeholders = task
        if text_to_translate.strip():
            translated_text = translated_results[translation_index]['translatedText']
            translation_index += 1
            translated_text = restore_tokens(translated_text, placeholders)
            result[lang_code][key] = f'"{translated_text}"'
        else:
            result[lang_code][key] = f'"{original_text}"'
        translation_progress += 1
        if progress_callback:
            progress_callback(translation_progress, total_items)
    
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

# 진행률 저장을 위한 전역 변수 (단일 파일 기준; 여러 파일은 개별 진행률은 별도 구현 필요)
translation_progress = {"current": 0, "total": 100, "current_count": 0, "total_count": 100}

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
    download_urls = []
    
    # 파일마다 개별적으로 번역 처리 (순차적으로 처리)
    for file in files:
        if file.filename == '':
            continue
        
        os.makedirs('uploads', exist_ok=True)
        file_path = os.path.join('uploads', file.filename)
        file.save(file_path)
        
        # 진행률 초기화 (단일 파일 기준)
        translation_progress = {"current": 0, "total": 100, "current_count": 0, "total_count": 100}
        
        def progress_callback(processed, total):
            global translation_progress
            translation_progress["current"] = int((processed / total) * 100)
            translation_progress["current_count"] = processed
            translation_progress["total_count"] = total
            logging.info(f"[{file.filename}] 번역 진행률: {processed}/{total} ({translation_progress['current']}%)")
        
        try:
            if file.filename.endswith('.yml'):
                translated_data = translate_paradox_file(file_path, target_language, progress_callback)
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
        "total_count": translation_progress["total_count"]
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
