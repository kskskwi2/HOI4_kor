# 버전 3.0.5 (수정됨)
# 작성일: 2025-05-25
# 주요 개선사항: 파싱 오류 처리 개선, 잘못된 따옴표 자동 수정, 오류 복구 기능

import os
import re
import logging
import time
import json
import requests
import tempfile
import atexit
import html
import zipfile
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, send_file, jsonify
from google.cloud import translate_v2 as translate
from dotenv import load_dotenv
import openai
from werkzeug.utils import secure_filename

# .env 파일 로드 (환경 변수 설정)
load_dotenv()

# 설정 클래스
class Config:
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
    UPLOAD_FOLDER = 'uploads'
    DOWNLOAD_FOLDER = 'downloads'
    SUPPORTED_EXTENSIONS = {'.yml', '.yaml'}
    DEFAULT_BATCH_SIZE = 100
    AI_REQUEST_DELAY = 0.1  # AI 모델별 요청 간격 줄임 (0.3초 → 0.1초)
    LOG_LEVEL = logging.WARNING  # INFO → WARNING으로 변경 (로그 줄임)
    
    # 언어 코드 매핑
    LANGUAGE_NAMES = {
        'ko': 'Korean', 'en': 'English', 'ja': 'Japanese', 
        'zh': 'Chinese', 'es': 'Spanish', 'fr': 'French',
        'de': 'German', 'ru': 'Russian', 'it': 'Italian', 
        'pt': 'Portuguese', 'nl': 'Dutch', 'sv': 'Swedish',
        'no': 'Norwegian', 'da': 'Danish', 'fi': 'Finnish'
    }

# 전역 설정
config = Config()
translate_client = None

# 구글 클라우드 번역 API 클라이언트 초기화
try:
    translate_client = translate.Client()
    # 로깅 레벨 조정으로 초기화 성공 메시지 제거
except Exception as e:
    logging.error(f"Google Cloud Translate API 초기화 실패: {e}")

# 유틸리티 함수들
def get_available_ollama_models(endpoint="http://localhost:11434"):
    """Ollama에서 사용 가능한 모델 목록 조회"""
    try:
        response = requests.get(f"{endpoint}/api/tags", timeout=5)
        if response.status_code == 200:
            data = response.json()
            models = [model['name'] for model in data.get('models', [])]
            return models
        else:
            logging.warning(f"Ollama 모델 목록 조회 실패: {response.status_code}")
            return []
    except Exception as e:
        logging.warning(f"Ollama 연결 실패: {e}")
        return []

def validate_ollama_model(endpoint, model):
    """Ollama 모델이 사용 가능한지 확인"""
    available_models = get_available_ollama_models(endpoint)
    if not available_models:
        return False, "Ollama 서버에 연결할 수 없습니다."
    
    if model not in available_models:
        return False, f"모델 '{model}'을 찾을 수 없습니다. 사용 가능한 모델: {', '.join(available_models)}"
    
    return True, "사용 가능"

def clean_temporary_files():
    """임시 파일들 정리"""
    try:
        for folder in [config.UPLOAD_FOLDER, config.DOWNLOAD_FOLDER]:
            if os.path.exists(folder):
                for file in os.listdir(folder):
                    file_path = os.path.join(folder, file)
                    if os.path.isfile(file_path):
                        # 1시간 이상 된 파일들 삭제
                        if time.time() - os.path.getctime(file_path) > 3600:
                            os.remove(file_path)
    except Exception as e:
        logging.error(f"임시 파일 정리 중 오류: {e}")

def validate_file(file):
    """파일 유효성 검사"""
    if not file or not file.filename:
        raise ValueError("파일이 선택되지 않았습니다.")
    
    # 파일 확장자 검사
    _, ext = os.path.splitext(file.filename.lower())
    if ext not in config.SUPPORTED_EXTENSIONS:
        raise ValueError(f"지원하지 않는 파일 형식입니다. 지원 형식: {', '.join(config.SUPPORTED_EXTENSIONS)}")
    
    # 파일 크기 검사 (Content-Length 헤더가 있는 경우)
    if hasattr(file, 'content_length') and file.content_length:
        if file.content_length > config.MAX_FILE_SIZE:
            raise ValueError(f"파일 크기가 너무 큽니다. 최대 크기: {config.MAX_FILE_SIZE // (1024*1024)}MB")

def sanitize_text_for_ai(text):
    """AI 번역을 위한 텍스트 전처리 - 들여쓰기를 줄바꿈으로 변환"""
    if not text:
        return text
    
    # 연속된 공백이나 탭을 줄바꿈으로 변환 (4개 이상의 공백이나 탭)
    # 들여쓰기 패턴 감지 및 변환
    lines = text.split('\n')
    processed_lines = []
    
    for line in lines:
        # 줄 시작 부분의 들여쓰기 감지 (4개 이상의 공백이나 탭)
        if re.match(r'^(\s{4,}|\t{2,})', line):
            # 들여쓰기를 제거하고 이전 줄과 합치기 위해 \n 추가
            processed_line = line.lstrip()
            if processed_lines:
                processed_lines[-1] += '\\n' + processed_line
            else:
                processed_lines.append(processed_line)
        else:
            processed_lines.append(line)
    
    return '\n'.join(processed_lines)

def restore_text_formatting(text):
    """번역 후 텍스트 포맷팅 복원"""
    if not text:
        return text
    
    # \\n을 실제 줄바꿈으로 변환
    text = text.replace('\\n', '\n')
    
    # 번역된 텍스트 정리 (HTML 엔티티 등)
    text = clean_translated_text(text)
    
    return text

def clean_translated_text(text):
    """번역된 텍스트 정리"""
    if not text:
        return text
    
    # HTML 엔티티 디코딩
    text = html.unescape(text)
    
    # 일반적인 HTML 엔티티들 추가 처리
    replacements = {
        '&amp;': '&',
        '&lt;': '<',
        '&gt;': '>',
        '&nbsp;': ' ',
        '&#39;': "'",
        '&quot;': '"'
    }
    
    for entity, char in replacements.items():
        text = text.replace(entity, char)
    
    # 불필요한 공백 정리
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text

# 토큰 보존 함수들
def preserve_tokens(text):
    """토큰($...$) 보존: 토큰을 임시 플레이스홀더로 치환"""
    if not text:
        return text, {}
    
    token_pattern = re.compile(r'(\$[^$]*\$)')
    tokens = token_pattern.findall(text)
    placeholders = {}
    
    for i, token in enumerate(tokens):
        placeholder = f"__TOKEN_{i}__"
        placeholders[placeholder] = token
        text = text.replace(token, placeholder)
    
    return text, placeholders

def restore_tokens(text, placeholders):
    """치환된 토큰 복원"""
    if not text or not placeholders:
        return text
    
    for placeholder, token in placeholders.items():
        text = text.replace(placeholder, token)
    
    return text

# 파라독스 로컬라이제이션 파일 처리
def load_paradox_localization_file(file_path):
    """파라독스 로컬라이제이션 파일 로드 및 파싱"""
    try:
        with open(file_path, 'r', encoding='utf-8-sig') as file:
            content = file.read()
    except UnicodeDecodeError:
        # UTF-8로 읽기 실패 시 다른 인코딩 시도
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                content = file.read()
        except UnicodeDecodeError:
            with open(file_path, 'r', encoding='cp1252') as file:
                content = file.read()
    
    # 언어 코드 추출 (예: l_english)
    language_match = re.search(r'(l_\w+):', content)
    language_code = language_match.group(1) if language_match else 'l_english'
    
    # 키-값 쌍 추출
    result = {language_code: {}}
    lines = content.split('\n')
    parsing_errors = []
    
    for line_num, line in enumerate(lines, 1):
        original_line = line
        line = line.strip()
        
        # 주석, 빈 줄, 혹은 언어 헤더(l_*)는 건너뜀
        if not line or line.startswith('#') or re.match(r'l_\w+:', line):
            continue
        
        # 키-값 쌍 파싱 시도
        success = False
        
        # 1차 시도: 정상적인 패턴
        match = re.match(r'^\s*([^:]+:\s*\d*)\s+"(.+)"\s*$', line)
        if match:
            key_part = match.group(1)
            value_text = match.group(2)
            key = key_part.strip()
            result[language_code][key] = f'"{value_text}"'
            success = True
        else:
            # 2차 시도: 따옴표 문제 해결 (끝 따옴표 없음)
            match = re.match(r'^\s*([^:]+:\s*\d*)\s+"(.+?)\'?\s*$', line)
            if match:
                key_part = match.group(1)
                value_text = match.group(2)
                key = key_part.strip()
                # 따옴표 수정
                fixed_value = value_text.rstrip("'")  # 잘못된 작은따옴표 제거
                result[language_code][key] = f'"{fixed_value}"'
                parsing_errors.append(f"라인 {line_num}: 따옴표 오류 자동 수정 - '{original_line.strip()}' → '{key} \"{fixed_value}\"'")
                success = True
            else:
                # 3차 시도: 따옴표가 완전히 없는 경우
                match = re.match(r'^\s*([^:]+:\s*\d*)\s+(.+?)\s*$', line)
                if match and '"' not in line:
                    key_part = match.group(1)
                    value_text = match.group(2)
                    key = key_part.strip()
                    result[language_code][key] = f'"{value_text}"'
                    parsing_errors.append(f"라인 {line_num}: 따옴표 누락 자동 수정 - '{original_line.strip()}' → '{key} \"{value_text}\"'")
                    success = True
        
        # 파싱 실패한 라인 처리
        if not success and '"' in line:
            parsing_errors.append(f"라인 {line_num}: 파싱 실패 (건너뜀) - '{original_line.strip()}'")
    
    # 파싱 오류 로깅
    if parsing_errors:
        logging.warning(f"파일 '{file_path}' 파싱 중 {len(parsing_errors)}개 오류 발견:")
        for error in parsing_errors[:5]:  # 최대 5개만 로깅
            logging.warning(f"  {error}")
        if len(parsing_errors) > 5:
            logging.warning(f"  ... 그 외 {len(parsing_errors) - 5}개 오류")
    
    return result

class TranslationService:
    """번역 서비스 클래스"""
    
    def __init__(self):
        self.cache = {}  # 번역 캐시
    
    def translate_with_google(self, text, target_language):
        """구글 클라우드 번역 API를 사용한 번역"""
        if not text.strip():
            return text
        
        if not translate_client:
            raise Exception("Google Cloud Translate API가 설정되지 않았습니다.")
        
        # 캐시 확인
        cache_key = f"google_{text}_{target_language}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        # 구글 번역의 경우 토큰 보존을 위해 플레이스홀더 처리
        text_to_translate, placeholders = preserve_tokens(text)
        
        try:
            result = translate_client.translate(text_to_translate, target_language=target_language)
            translated_text = result['translatedText']
            
            # HTML 엔티티 디코딩 (&quot; → " 등)
            translated_text = html.unescape(translated_text)
            
            # 토큰 복원
            translated_text = restore_tokens(translated_text, placeholders)
            
            # 캐시 저장
            self.cache[cache_key] = translated_text
            return translated_text
            
        except Exception as e:
            logging.error(f"Google 번역 API 오류: {e}")
            return text
    
    def translate_with_openai(self, text, target_language, api_key, model="gpt-3.5-turbo"):
        """OpenAI API를 사용한 텍스트 번역"""
        if not text.strip():
            return text
        
        if not api_key:
            raise ValueError("OpenAI API 키가 필요합니다.")
        
        # 캐시 확인
        cache_key = f"openai_{text}_{target_language}_{model}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        target_lang_name = config.LANGUAGE_NAMES.get(target_language, target_language)
        
        # AI 번역을 위한 텍스트 전처리
        processed_text = sanitize_text_for_ai(text)
        
        try:
            client = openai.OpenAI(api_key=api_key)
            
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": f"""You are a professional game localization translator specializing in strategy games, RPGs, and historical simulations. Your task is to translate the following text into {target_lang_name} accurately and naturally.

CRITICAL RULES:
1. NEVER translate anything between $ symbols (e.g., $PARAM$, $VALUE$, $COUNTRY_NAME$). Keep these exactly as they are.
2. These $ tokens are game variables/placeholders that must remain untouched.

TRANSLATION GUIDELINES:
3. Use game-appropriate terminology and style for the target language.
4. Preserve all formatting: \\n for line breaks, special punctuation, numbers, dates.
5. For abbreviations/acronyms of organizations, expand to full official names:
   - NATO → North Atlantic Treaty Organization → 북대서양 조약 기구
   - USSR → Union of Soviet Socialist Republics → 소비에트 사회주의 공화국 연방
   - EU → European Union → 유럽연합
6. Use established official translations for:
   - Historical figures and places
   - Military ranks and titles
   - Political/governmental terms
   - Religious and cultural terms
7. Maintain consistency in terminology throughout the text.
8. For numbers with units, preserve the format (e.g., "50 km", "1943년").
9. Keep proper nouns (character names, place names) in their commonly accepted translated forms.
10. If uncertain about a specific term, prioritize clarity and common usage over literal translation.

OUTPUT FORMAT:
- Return ONLY the translated text
- No explanations, notes, or additional commentary
- Maintain exact same structure and formatting as input"""}, 
                    {"role": "user", "content": processed_text}
                ],
                temperature=0.1,  # 더 일관된 번역을 위해 낮춤
                max_tokens=1024
            )
            
            translated_text = response.choices[0].message.content.strip()
            
            # 텍스트 포맷팅 복원
            translated_text = restore_text_formatting(translated_text)
            
            # 캐시 저장
            self.cache[cache_key] = translated_text
            return translated_text
            
        except openai.APIError as e:
            logging.error(f"OpenAI API 오류: {e}")
            return text
        except openai.RateLimitError as e:
            logging.error(f"OpenAI API 요청 한도 초과: {e}")
            time.sleep(60)  # 1분 대기 후 원본 텍스트 반환
            return text
        except Exception as e:
            logging.error(f"OpenAI API 번역 중 예상치 못한 오류: {e}")
            return text
    
    def translate_with_ollama(self, text, target_language, endpoint="http://localhost:11434", model="llama3.1:8b"):
        """Ollama API를 사용한 텍스트 번역"""
        if not text.strip():
            return text
        
        # 캐시 확인
        cache_key = f"ollama_{text}_{target_language}_{model}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        # 모델 유효성 검사
        is_valid, message = validate_ollama_model(endpoint, model)
        if not is_valid:
            logging.error(f"Ollama 모델 검증 실패: {message}")
            # 사용 가능한 첫 번째 모델로 대체 시도
            available_models = get_available_ollama_models(endpoint)
            if available_models:
                model = available_models[0]
                logging.info(f"사용 가능한 모델로 변경: {model}")
            else:
                logging.error("사용 가능한 Ollama 모델이 없습니다.")
                return text
        
        target_lang_name = config.LANGUAGE_NAMES.get(target_language, target_language)
        
        # AI 번역을 위한 텍스트 전처리
        processed_text = sanitize_text_for_ai(text)
        
        try:
            response = requests.post(
                f"{endpoint}/api/generate",
                headers={"Content-Type": "application/json"},
                json={
                    "model": model,
                    "prompt": f"""You are a professional game localization translator specializing in strategy games, RPGs, and historical simulations. Translate the following text into {target_lang_name} accurately and naturally.

CRITICAL RULES:
1. NEVER translate anything between $ symbols (e.g., $PARAM$, $VALUE$, $COUNTRY_NAME$). Keep these exactly as they are.
2. These $ tokens are game variables/placeholders that must remain untouched.

TRANSLATION GUIDELINES:
3. Use game-appropriate terminology and style for the target language.
4. Preserve all formatting: \\n for line breaks, special punctuation, numbers, dates.
5. For abbreviations/acronyms of organizations, expand to full official names:
   - NATO → North Atlantic Treaty Organization → 북대서양 조약 기구
   - USSR → Union of Soviet Socialist Republics → 소비에트 사회주의 공화국 연방
   - EU → European Union → 유럽연합
6. Use established official translations for:
   - Historical figures and places
   - Military ranks and titles  
   - Political/governmental terms
   - Religious and cultural terms
7. Maintain consistency in terminology throughout the text.
8. For numbers with units, preserve the format (e.g., "50 km", "1943년").
9. Keep proper nouns (character names, place names) in their commonly accepted translated forms.
10. If uncertain about a specific term, prioritize clarity and common usage over literal translation.

Text to translate: "{processed_text}"

Translation:""",
                    "stream": False,
                    "options": {
                        "temperature": 0.1,  # 더 일관된 번역을 위해 낮춤
                        "top_p": 0.9,
                        "top_k": 40
                    }
                },
                timeout=60  # 60초 타임아웃
            )
            
            if response.status_code == 200:
                result = response.json()
                translated_text = result.get('response', '').strip()
                
                # 응답에서 번역된 텍스트만 추출
                # "Translation:" 다음의 텍스트나 따옴표 안의 텍스트 추출
                if 'Translation:' in translated_text:
                    translated_text = translated_text.split('Translation:')[-1].strip()
                
                # 따옴표 제거
                translated_text = translated_text.strip('"\'')
                
                # 텍스트 포맷팅 복원
                translated_text = restore_text_formatting(translated_text)
                
                # 캐시 저장
                self.cache[cache_key] = translated_text
                return translated_text
            else:
                error_msg = f"{response.status_code} - {response.text}"
                logging.error(f"Ollama API 오류: {error_msg}")
                
                # 404 오류(모델 없음)인 경우 더 구체적인 메시지
                if response.status_code == 404:
                    available_models = get_available_ollama_models(endpoint)
                    if available_models:
                        logging.error(f"사용 가능한 모델: {', '.join(available_models)}")
                    else:
                        logging.error("Ollama 서버에 설치된 모델이 없습니다.")
                
                return text
                
        except requests.RequestException as e:
            logging.error(f"Ollama API 네트워크 오류: {e}")
            return text
        except Exception as e:
            logging.error(f"Ollama API 번역 중 예상치 못한 오류: {e}")
            return text

# 번역 서비스 인스턴스
translation_service = TranslationService()

def translate_paradox_file(file_path, target_language, translation_api="google", api_settings=None, progress_callback=None):
    """파라독스 로컬라이제이션 파일 번역"""
    try:
        data = load_paradox_localization_file(file_path)
        total_items = sum(len(lang_data) for lang_data in data.values())
        translation_progress = 0

        if total_items == 0:
            raise ValueError("번역할 텍스트가 파일에서 발견되지 않았습니다.")

        # 번역할 항목 수집
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
        if translation_api == "google" and translate_client:
            # 구글 번역: 배치 처리 (개선된 방식)
            translated_results = []
            texts_to_translate = [task[2] for task in tasks if task[2].strip()]
            
            # 배치 처리
            batch_size = config.DEFAULT_BATCH_SIZE
            for i in range(0, len(texts_to_translate), batch_size):
                batch_texts = texts_to_translate[i:i+batch_size]
                batch_results = []
                
                for text in batch_texts:
                    try:
                        translated_text = translation_service.translate_with_google(text, target_language)
                        batch_results.append({'translatedText': translated_text})
                    except Exception as e:
                        logging.error(f"개별 번역 실패: {e}")
                        batch_results.append({'translatedText': text})
                
                translated_results.extend(batch_results)
                
                # 진행률 업데이트
                processed = min(i + batch_size, len(texts_to_translate))
                progress_percentage = int((processed / len(tasks)) * 100) if len(tasks) > 0 else 0
                if progress_callback:
                    progress_callback(processed, len(tasks), f"배치 {i//batch_size + 1}/{(len(texts_to_translate) + batch_size - 1)//batch_size}")

            # 번역 결과를 각 항목에 적용
            translation_index = 0
            for task_index, task in enumerate(tasks):
                lang_code, key, original_text = task
                if original_text.strip():
                    if translation_index < len(translated_results):
                        translated_text = translated_results[translation_index]['translatedText']
                        translation_index += 1
                    else:
                        translated_text = original_text
                    result[lang_code][key] = f'"{translated_text}"'
                else:
                    result[lang_code][key] = f'"{original_text}"'
                
                # 진행률 업데이트 (각 항목별)
                if progress_callback:
                    progress_callback(task_index + 1, len(tasks), key)

        else:
            # AI 번역 (OpenAI 또는 Ollama): 항목별 개별 처리
            for task_index, task in enumerate(tasks):
                lang_code, key, original_text = task
                
                # 현재 번역 중인 항목 정보 업데이트
                if progress_callback:
                    progress_callback(task_index, len(tasks), key)
                
                if original_text.strip():
                    try:
                        # API에 따라 번역 함수 선택
                        if translation_api == "openai":
                            api_key = api_settings.get("openai_api_key", "") if api_settings else ""
                            model = api_settings.get("openai_model", "gpt-3.5-turbo") if api_settings else "gpt-3.5-turbo"
                            translated_text = translation_service.translate_with_openai(original_text, target_language, api_key, model)
                        elif translation_api == "ollama":
                            endpoint = api_settings.get("ollama_endpoint", "http://localhost:11434") if api_settings else "http://localhost:11434"
                            model = api_settings.get("ollama_model", "llama3.1:8b") if api_settings else "llama3.1:8b"
                            translated_text = translation_service.translate_with_ollama(original_text, target_language, endpoint, model)
                        else:
                            # 기본값은 구글 번역
                            translated_text = translation_service.translate_with_google(original_text, target_language)
                        
                        result[lang_code][key] = f'"{translated_text}"'
                        
                    except Exception as e:
                        logging.error(f"번역 실패 - {key}: {e}")
                        result[lang_code][key] = f'"{original_text}"'
                else:
                    result[lang_code][key] = f'"{original_text}"'
                
                # AI 번역은 속도 제한을 위해 간격 추가
                if translation_api in ["openai", "ollama"]:
                    time.sleep(config.AI_REQUEST_DELAY)
        
        return result
        
    except Exception as e:
        logging.error(f"파일 번역 중 오류 발생: {e}")
        raise

def save_paradox_localization(translated_data, original_filename):
    """번역된 데이터를 파라독스 로컬라이제이션 파일 형식으로 저장"""
    os.makedirs(config.DOWNLOAD_FOLDER, exist_ok=True)
    
    # 파일명 보안 처리
    safe_filename = secure_filename(original_filename)
    output_path = os.path.join(config.DOWNLOAD_FOLDER, safe_filename)
    
    try:
        with open(output_path, 'w', encoding='utf-8-sig') as file:
            for lang_code, lang_data in translated_data.items():
                file.write(f"{lang_code}:\n")
                for key, value in lang_data.items():
                    # 값이 따옴표로 둘러싸여 있는지 확인
                    if isinstance(value, str) and value.startswith('"') and value.endswith('"'):
                        file.write(f" {key} {value}\n")
                    else:
                        # 따옴표가 없으면 추가
                        file.write(f' {key} "{value}"\n')
        
        return output_path
        
    except Exception as e:
        logging.error(f"파일 저장 중 오류: {e}")
        raise

# Flask 웹 애플리케이션 설정
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = config.MAX_FILE_SIZE

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
    """메인 페이지"""
    # HTML을 직접 반환 (템플릿 파일 불필요)
    html_content = """<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>게임 로컬라이제이션 번역기</title>
    <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
    <style>
        body { 
            font-family: 'Malgun Gothic', '맑은 고딕', sans-serif; 
            margin: 0; 
            padding: 20px; 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
        }
        .container { 
            max-width: 900px; 
            margin: 0 auto; 
            background-color: white; 
            padding: 30px; 
            border-radius: 15px; 
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        }
        h1 { 
            color: #333; 
            text-align: center; 
            margin-bottom: 10px;
            font-size: 2.5em;
            background: linear-gradient(45deg, #667eea, #764ba2);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        .subtitle {
            text-align: center;
            color: #666;
            margin-bottom: 30px;
            font-size: 1.1em;
        }
        form { margin-bottom: 20px; }
        label { 
            display: block; 
            margin-bottom: 8px; 
            font-weight: bold;
            color: #333;
        }
        select, input[type="file"], input[type="text"], input[type="password"] { 
            width: 100%; 
            padding: 12px; 
            margin-bottom: 15px; 
            border: 2px solid #e1e1e1; 
            border-radius: 8px; 
            box-sizing: border-box;
            font-size: 14px;
            transition: border-color 0.3s ease;
        }
        select:focus, input[type="file"]:focus, input[type="text"]:focus, input[type="password"]:focus {
            border-color: #667eea;
            outline: none;
        }
        input[type="submit"] { 
            background: linear-gradient(45deg, #667eea, #764ba2);
            color: white; 
            padding: 15px 20px; 
            border: none; 
            border-radius: 8px; 
            cursor: pointer; 
            font-size: 16px; 
            width: 100%;
            font-weight: bold;
            transition: transform 0.2s ease;
        }
        input[type="submit"]:hover { 
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.3);
        }
        input[type="submit"]:disabled {
            background: #ccc;
            cursor: not-allowed;
            transform: none;
        }
        #progress { 
            margin-top: 20px; 
            display: none;
            background: #f8f9fa;
            padding: 20px;
            border-radius: 10px;
            border: 1px solid #e9ecef;
        }
        progress { 
            width: 100%; 
            height: 25px;
            border-radius: 12px;
        }
        #percentage { 
            text-align: center; 
            font-weight: bold; 
            margin-top: 10px;
            font-size: 18px;
            color: #667eea;
        }
        #currentItem {
            text-align: center;
            margin-top: 10px;
            color: #666;
            font-style: italic;
            min-height: 20px;
        }
        .error-message { 
            color: #dc3545; 
            margin-top: 10px; 
            padding: 15px; 
            background-color: #f8d7da; 
            border: 1px solid #f5c6cb;
            border-radius: 8px; 
            display: none;
        }
        .success-message {
            color: #155724;
            margin-top: 10px;
            padding: 15px;
            background-color: #d4edda;
            border: 1px solid #c3e6cb;
            border-radius: 8px;
            display: none;
        }
        .info-section { 
            margin-top: 30px; 
            padding: 20px; 
            background: linear-gradient(135deg, #e8f4f8 0%, #f0f8e8 100%);
            border-radius: 10px;
            border-left: 5px solid #667eea;
        }
        .info-section h3 { 
            margin-top: 0;
            color: #333;
        }
        #downloadLink { 
            text-align: center; 
            margin-top: 20px; 
            font-size: 18px;
        }
        .download-item {
            display: inline-block;
            margin: 10px;
            padding: 15px 25px;
            background: linear-gradient(45deg, #28a745, #20c997);
            color: white;
            text-decoration: none;
            border-radius: 25px;
            font-weight: bold;
            transition: all 0.3s ease;
        }
        .download-item:hover {
            transform: scale(1.05);
            text-decoration: none;
            color: white;
        }
        .translation-settings { 
            padding: 20px; 
            background: #f8f9fa;
            border-radius: 10px; 
            margin-bottom: 20px;
            border: 1px solid #e9ecef;
        }
        .translation-option { 
            margin-bottom: 15px;
            padding: 10px;
            border-radius: 5px;
            transition: background-color 0.3s ease;
        }
        .translation-option:hover {
            background-color: #e9ecef;
        }
        .translation-option input[type="radio"] {
            margin-right: 10px;
            width: auto;
        }
        .translation-option label {
            display: inline;
            margin-left: 5px;
            cursor: pointer;
        }
        .api-key-input, .ollama-settings { 
            display: none; 
            margin-top: 15px;
            padding: 15px;
            background: white;
            border-radius: 8px;
            border: 1px solid #dee2e6;
        }
        .status-indicator {
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            margin-right: 8px;
        }
        .status-ready { background-color: #28a745; }
        .status-working { background-color: #ffc107; }
        .status-error { background-color: #dc3545; }
        
        .file-info {
            background: #e9ecef;
            padding: 10px;
            border-radius: 5px;
            margin-top: 10px;
            font-size: 14px;
            color: #495057;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>게임 로컬라이제이션 번역기</h1>
        <p class="subtitle">파라독스 인터랙티브 게임 등의 로컬라이제이션 파일 (예: l_english.yml)을 다른 언어로 번역합니다.</p>
        
        <form id="uploadForm" enctype="multipart/form-data">
            <label for="file">번역할 파일 선택 (여러 파일 선택 가능):</label>
            <input type="file" name="file" id="fileInput" accept=".yml" multiple required>
            <div id="fileInfo" class="file-info" style="display: none;"></div>
            
            <div class="translation-settings">
                <label>번역 API 선택:</label>
                <div class="translation-option">
                    <input type="radio" id="googleTranslate" name="translationApi" value="google" checked>
                    <label for="googleTranslate">
                        <span class="status-indicator status-ready"></span>
                        구글 클라우드 번역 (빠름, 기본)
                    </label>
                </div>
                
                <div class="translation-option">
                    <input type="radio" id="openaiApi" name="translationApi" value="openai">
                    <label for="openaiApi">
                        <span class="status-indicator status-ready"></span>
                        OpenAI API (ChatGPT/GPT-4) - 고품질
                    </label>
                    <div id="openaiSettings" class="api-key-input">
                        <label for="openaiApiKey">OpenAI API 키:</label>
                        <input type="password" id="openaiApiKey" name="openaiApiKey" placeholder="sk-...">
                        <label for="openaiModel">모델 선택:</label>
                        <select id="openaiModel" name="openaiModel">
                            <option value="gpt-4o">GPT-4o (최신)</option>
                            <option value="gpt-4-turbo">GPT-4 Turbo</option>
                            <option value="gpt-4">GPT-4</option>
                            <option value="gpt-3.5-turbo" selected>GPT-3.5 Turbo (경제적)</option>
                        </select>
                    </div>
                </div>
                
                <div class="translation-option">
                    <input type="radio" id="ollamaApi" name="translationApi" value="ollama">
                    <label for="ollamaApi">
                        <span class="status-indicator status-ready"></span>
                        Ollama (로컬 AI) - 무료
                    </label>
                    <div id="ollamaSettings" class="ollama-settings">
                        <label for="ollamaEndpoint">Ollama 엔드포인트:</label>
                        <input type="text" id="ollamaEndpoint" name="ollamaEndpoint" value="http://localhost:11434" placeholder="http://localhost:11434">
                        <label for="ollamaModel">모델 선택:</label>
                        <select id="ollamaModel" name="ollamaModel">
                            <option value="llama3.1:8b">Llama 3.1 8B (추천)</option>
                            <option value="gemma2:27b">Gemma 2 27B (고품질)</option>
                            <option value="mistral">Mistral 7B</option>
                            <option value="llama2">Llama 2 7B</option>
                        </select>
                        <button type="button" id="testOllama" style="margin-top: 10px; padding: 8px 15px; background: #6c757d; color: white; border: none; border-radius: 5px; cursor: pointer;">연결 테스트</button>
                    </div>
                </div>
            </div>
            
            <label for="language">번역할 언어:</label>
            <select name="language" id="languageSelect">
                <option value="ko">한국어 (Korean)</option>
                <option value="en">영어 (English)</option>
                <option value="ja">일본어 (Japanese)</option>
                <option value="zh">중국어 (Chinese)</option>
                <option value="es">스페인어 (Spanish)</option>
                <option value="fr">프랑스어 (French)</option>
                <option value="de">독일어 (German)</option>
                <option value="ru">러시아어 (Russian)</option>
                <option value="it">이탈리아어 (Italian)</option>
                <option value="pt">포르투갈어 (Portuguese)</option>
                <option value="nl">네덜란드어 (Dutch)</option>
                <option value="sv">스웨덴어 (Swedish)</option>
                <option value="no">노르웨이어 (Norwegian)</option>
                <option value="da">덴마크어 (Danish)</option>
                <option value="fi">핀란드어 (Finnish)</option>
            </select>
            
            <input type="submit" value="번역 시작" id="submitBtn">
        </form>

        <div id="progress">
            <h2>번역 진행률</h2>
            <progress id="progressBar" value="0" max="100"></progress>
            <p id="percentage">0%</p>
            <p id="currentItem"></p>
            <p id="estimatedTime" style="color: #666; font-size: 14px;"></p>
        </div>
        
        <div id="errorMessage" class="error-message"></div>
        <div id="successMessage" class="success-message"></div>
        
        <div id="downloadLink"></div>
        
        <div class="info-section">
            <h3>🎮 사용 안내</h3>
            <p><strong>1단계:</strong> 번역할 YML 파일을 선택합니다 (여러 파일 선택 가능).</p>
            <p><strong>2단계:</strong> 번역 API를 선택합니다.</p>
            <p><strong>3단계:</strong> 번역할 언어를 선택합니다.</p>
            <p><strong>4단계:</strong> '번역 시작' 버튼을 클릭하면 파일들이 순차적으로 번역됩니다.</p>
            <p><strong>5단계:</strong> 번역 완료 후 개별 파일 또는 ZIP 파일로 다운로드할 수 있습니다.</p>
            
            <h3>⚙️ API별 특징</h3>
            <p><strong>구글 클라우드 번역:</strong> 빠른 속도, 환경변수 설정 필요</p>
            <p><strong>OpenAI API:</strong> 최고 품질, 게임 맥락 이해 우수, API 키 필요</p>
            <p><strong>Ollama:</strong> 완전 무료, 로컬 처리, 프라이버시 보장</p>
            
            <h3>🔧 고급 기능</h3>
            <p>• AI 번역 시 들여쓰기는 자동으로 줄바꿈(\\n)으로 변환됩니다</p>
            <p>• 게임 변수 ($VARIABLE$) 는 번역되지 않고 보존됩니다</p>
            <p>• HTML 엔티티(&quot;, &amp; 등)가 자동으로 정상 문자로 변환됩니다</p>
            <p>• 약어와 줄임말을 자동으로 풀어서 번역합니다 (예: NATO → 북대서양 조약 기구)</p>
            <p>• 역사적, 정치적, 군사적 조직명을 해당 언어의 공식 명칭으로 번역합니다</p>
            <p>• 여러 파일 선택 시 자동으로 ZIP 파일로 묶어서 다운로드 제공</p>
            <p>• 실시간 진행률 표시 및 예상 완료 시간 제공</p>
            <p>• 대용량 파일 지원 및 시간 제한 없음</p>
            <p>• 번역 캐시로 중복 텍스트 처리 최적화</p>
        </div>
    </div>

    <script>
        $(document).ready(function(){
            let startTime;
            
            // 파일 선택 시 정보 표시
            $('#fileInput').change(function(){
                const files = this.files;
                if(files.length > 0) {
                    let info = `선택된 파일 ${files.length}개:\\n`;
                    for(let i = 0; i < files.length; i++) {
                        info += `• ${files[i].name} (${(files[i].size / 1024).toFixed(1)} KB)\\n`;
                    }
                    $('#fileInfo').text(info).show();
                } else {
                    $('#fileInfo').hide();
                }
            });
            
            // 라디오 버튼 변경 시 관련 설정 표시/숨김
            $('input[name="translationApi"]').change(function(){
                $('.api-key-input, .ollama-settings').hide();
                
                if($(this).val() === 'openai') {
                    $('#openaiSettings').show();
                } else if($(this).val() === 'ollama') {
                    $('#ollamaSettings').show();
                }
            });
            
            // Ollama 연결 테스트
            $('#testOllama').click(function(){
                const endpoint = $('#ollamaEndpoint').val();
                const btn = $(this);
                btn.text('테스트 중...').prop('disabled', true);
                
                $.get('/ollama/models?endpoint=' + encodeURIComponent(endpoint))
                    .done(function(data) {
                        if(data.models && data.models.length > 0) {
                            btn.text('연결 성공!').css('background', '#28a745');
                            
                            // 모델 선택 옵션 업데이트
                            const modelSelect = $('#ollamaModel');
                            const currentModel = modelSelect.val();
                            modelSelect.empty();
                            
                            data.models.forEach(function(model) {
                                const option = $('<option></option>')
                                    .attr('value', model)
                                    .text(model);
                                if(model === currentModel) {
                                    option.attr('selected', true);
                                }
                                modelSelect.append(option);
                            });
                            
                            // 현재 모델이 사용 가능한 모델에 없으면 첫 번째 모델 선택
                            if(!data.models.includes(currentModel)) {
                                modelSelect.val(data.models[0]);
                            }
                            
                            setTimeout(() => {
                                btn.text('연결 테스트').css('background', '#6c757d').prop('disabled', false);
                            }, 2000);
                        } else {
                            btn.text('모델 없음').css('background', '#ffc107');
                            setTimeout(() => {
                                btn.text('연결 테스트').css('background', '#6c757d').prop('disabled', false);
                            }, 3000);
                        }
                    })
                    .fail(function() {
                        btn.text('연결 실패').css('background', '#dc3545');
                        setTimeout(() => {
                            btn.text('연결 테스트').css('background', '#6c757d').prop('disabled', false);
                        }, 2000);
                    });
            });
            
            // 폼 제출 처리
            $('#uploadForm').submit(function(event){
                event.preventDefault();
                
                // 기본 검증
                const files = $('#fileInput')[0].files;
                if(files.length === 0) {
                    showError('파일을 선택해주세요.');
                    return;
                }
                
                const translationApi = $('input[name="translationApi"]:checked').val();
                if(translationApi === 'openai' && !$('#openaiApiKey').val().trim()) {
                    showError('OpenAI API 키를 입력해주세요.');
                    return;
                }
                
                var formData = new FormData(this);
                
                // UI 상태 변경
                $('#submitBtn').prop('disabled', true).val('번역 중...');
                $('#progress').show();
                $('#errorMessage, #successMessage').hide();
                $('#downloadLink').html('');
                startTime = Date.now();
                
                $.ajax({
                    url: '/upload',
                    type: 'POST',
                    data: formData,
                    contentType: false,
                    processData: false,
                    // 시간 초과 제거 - 대용량 파일도 완료될 때까지 기다림
                    timeout: 0,
                    success: function(response) {
                        if(response.error) {
                            showError('번역 오류: ' + response.error);
                        } else if(response.download_urls) {
                            $('#progressBar').val(100);
                            $('#percentage').text('100% - 번역 완료!');
                            
                            // 다운로드 링크 생성
                            let links = '<h3>✅ 번역 완료!</h3>';
                            
                            // ZIP 다운로드 링크 (파일이 2개 이상일 때)
                            if(response.zip_download_url) {
                                links += `<div style="margin-bottom: 20px;">`;
                                links += `<a href="${response.zip_download_url}" class="download-item" style="background: linear-gradient(45deg, #ff6b6b, #ee5a24); font-size: 18px; padding: 20px 30px;">📦 모든 파일 ZIP 다운로드</a>`;
                                links += `</div>`;
                                links += `<h4>개별 파일 다운로드:</h4>`;
                            }
                            
                            // 개별 파일 다운로드 링크
                            response.download_urls.forEach(function(url, index){
                                const filename = url.split('/').pop();
                                links += `<a href="${url}" class="download-item">📁 ${filename} 다운로드</a>`;
                            });
                            
                            $('#downloadLink').html(links);
                            
                            let successMsg = `총 ${response.download_urls.length}개 파일이 성공적으로 번역되었습니다.`;
                            if(response.zip_download_url) {
                                successMsg += ' ZIP 파일로 한번에 다운로드하거나 개별적으로 다운로드할 수 있습니다.';
                            }
                            showSuccess(successMsg);
                        }
                    },
                    error: function(xhr, status, error) {
                        let errorMsg = '서버 오류가 발생했습니다.';
                        if(xhr.responseJSON && xhr.responseJSON.error) {
                            errorMsg = xhr.responseJSON.error;
                        } else if(status === 'error') {
                            errorMsg = '네트워크 오류가 발생했습니다. 연결을 확인해주세요.';
                        }
                        showError(errorMsg);
                    },
                    complete: function() {
                        $('#submitBtn').prop('disabled', false).val('번역 시작');
                    }
                });
                
                // 진행률 폴링
                startProgressPolling();
            });
            
            function startProgressPolling() {
                const progressInterval = setInterval(function() {
                    $.get('/progress', function(data) {
                        const percent = Math.max(0, Math.min(100, data.progress || 0)); // 0-100 범위 강제
                        $('#progressBar').val(percent);
                        $('#percentage').text(`${Math.round(percent)}% (${data.current_count || 0}/${data.total_count || 0})`);
                        
                        // 현재 번역 중인 항목 정보 표시
                        if(data.current_item) {
                            $('#currentItem').text(`현재 번역 중: ${data.current_item}`);
                        }
                        
                        // 예상 완료 시간 계산 (진행률이 5% 이상일 때만)
                        if(percent > 5 && percent < 100 && startTime) {
                            const elapsed = Date.now() - startTime;
                            const estimated = (elapsed / percent) * (100 - percent);
                            const minutes = Math.ceil(estimated / 60000);
                            const seconds = Math.ceil((estimated % 60000) / 1000);
                            
                            if(minutes > 0) {
                                $('#estimatedTime').text(`예상 완료: 약 ${minutes}분 ${seconds}초 후`);
                            } else {
                                $('#estimatedTime').text(`예상 완료: 약 ${seconds}초 후`);
                            }
                        } else if(percent >= 100) {
                            $('#estimatedTime').text('완료!');
                        }
                        
                        if (percent >= 100) {
                            clearInterval(progressInterval);
                            setTimeout(function() {
                                if($('#downloadLink').html() !== '') {
                                    $('#progress').hide();
                                }
                            }, 3000);
                        }
                    }).fail(function() {
                        // 진행률 조회 실패 시 폴링 중단
                        clearInterval(progressInterval);
                    });
                }, 1000);
            }
            
            function showError(message) {
                $('#errorMessage').text(message).show();
                $('#progress').hide();
                $('#successMessage').hide();
            }
            
            function showSuccess(message) {
                $('#successMessage').text(message).show();
                $('#errorMessage').hide();
            }
        });
    </script>
</body>
</html>"""
    return html_content

@app.route('/ollama/models')
def get_ollama_models():
    """Ollama 사용 가능한 모델 목록 조회 API"""
    endpoint = request.args.get('endpoint', 'http://localhost:11434')
    models = get_available_ollama_models(endpoint)
    return jsonify({"models": models})

@app.route('/health')
def health_check():
    """헬스체크 엔드포인트"""
    services = {
        "google_translate": translate_client is not None,
        "timestamp": datetime.now().isoformat(),
        "status": "healthy"
    }
    return jsonify(services)

@app.route('/upload', methods=['POST'])
def upload_file():
    """파일 업로드 및 번역 처리"""
    global translation_progress
    
    try:
        # 파일 검증
        files = request.files.getlist('file')
        if not files or len(files) == 0:
            return jsonify({"error": "파일이 선택되지 않았습니다."}), 400
        
        # 각 파일 유효성 검사
        for file in files:
            validate_file(file)
        
        target_language = request.form.get('language')
        if not target_language:
            return jsonify({"error": "번역할 언어를 선택해주세요."}), 400
        
        translation_api = request.form.get('translationApi', 'google')
        
        # API 설정 정보 수집 및 검증
        api_settings = {}
        if translation_api == "openai":
            api_key = request.form.get('openaiApiKey', '').strip()
            if not api_key:
                return jsonify({"error": "OpenAI API 키가 필요합니다."}), 400
            api_settings = {
                "openai_api_key": api_key,
                "openai_model": request.form.get('openaiModel', 'gpt-3.5-turbo')
            }
        elif translation_api == "ollama":
            api_settings = {
                "ollama_endpoint": request.form.get('ollamaEndpoint', 'http://localhost:11434'),
                "ollama_model": request.form.get('ollamaModel', 'llama3.1:8b')
            }
            
            # Ollama 연결 및 모델 확인
            endpoint = api_settings["ollama_endpoint"]
            model = api_settings["ollama_model"]
            is_valid, message = validate_ollama_model(endpoint, model)
            if not is_valid:
                available_models = get_available_ollama_models(endpoint)
                if available_models:
                    return jsonify({
                        "error": f"모델 '{model}'을 찾을 수 없습니다. 사용 가능한 모델을 선택해주세요: {', '.join(available_models)}"
                    }), 400
                else:
                    return jsonify({
                        "error": "Ollama 서버에 연결할 수 없거나 설치된 모델이 없습니다. 'ollama pull <model>' 명령으로 모델을 설치해주세요."
                    }), 400
        elif translation_api == "google" and not translate_client:
            return jsonify({"error": "Google Cloud Translate API가 설정되지 않았습니다."}), 500
        
        download_urls = []
        translated_files = []  # 번역된 파일 경로 저장
        
        # 업로드 폴더 생성
        os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
        
        # 파일마다 개별적으로 번역 처리
        for file_index, file in enumerate(files):
            if file.filename == '':
                continue
            
            # 안전한 파일명 생성
            safe_filename = secure_filename(file.filename)
            file_path = os.path.join(config.UPLOAD_FOLDER, f"{int(time.time())}_{safe_filename}")
            file.save(file_path)
            
            # 진행률 초기화
            translation_progress = {
                "current": 0, 
                "total": 100, 
                "current_count": 0, 
                "total_count": 100, 
                "current_item": f"파일 {file_index + 1}/{len(files)}: {file.filename}"
            }
            
            def progress_callback(processed, total, current_key=""):
                global translation_progress
                if total > 0:
                    progress_percentage = int((processed / total) * 100)
                    translation_progress["current"] = progress_percentage
                    translation_progress["current_count"] = processed
                    translation_progress["total_count"] = total
                    translation_progress["current_item"] = f"파일 {file_index + 1}/{len(files)}: {current_key}"
                # 로깅 빈도 줄임 (10% 단위로만 로깅)
                if progress_percentage % 10 == 0 or progress_percentage >= 95:
                    logging.info(f"[{file.filename}] 번역 진행률: {processed}/{total} ({progress_percentage}%)")
            
            try:
                if safe_filename.lower().endswith(('.yml', '.yaml')):
                    translated_data = translate_paradox_file(
                        file_path, 
                        target_language,
                        translation_api,
                        api_settings,
                        progress_callback
                    )
                    output_file_path = save_paradox_localization(translated_data, safe_filename)
                    download_url = f"/download/{os.path.basename(output_file_path)}"
                    download_urls.append(download_url)
                    translated_files.append(output_file_path)  # 파일 경로 저장
                else:
                    logging.error(f"{file.filename}은(는) 지원하지 않는 파일 형식입니다.")
                    
            except Exception as e:
                logging.error(f"{file.filename} 번역 처리 중 오류 발생: {e}")
                return jsonify({"error": f"파일 번역 중 오류: {str(e)}"}), 500
            finally:
                # 업로드된 임시 파일 삭제
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                except Exception as e:
                    logging.warning(f"임시 파일 삭제 실패: {e}")
        
        if not download_urls:
            return jsonify({"error": "번역할 수 있는 파일이 없습니다."}), 400
        
        # ZIP 파일 생성 (파일이 2개 이상일 때)
        zip_download_url = None
        if len(translated_files) > 1:
            zip_filename = f"translated_files_{int(time.time())}.zip"
            zip_path = os.path.join(config.DOWNLOAD_FOLDER, zip_filename)
            
            try:
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for file_path in translated_files:
                        if os.path.exists(file_path):
                            # ZIP 내에서의 파일명 (경로 없이 파일명만)
                            arcname = os.path.basename(file_path)
                            zipf.write(file_path, arcname)
                
                zip_download_url = f"/download/{zip_filename}"
                logging.info(f"ZIP 파일 생성 완료: {zip_filename}")
                
            except Exception as e:
                logging.error(f"ZIP 파일 생성 실패: {e}")
        
        # 최종 완료 상태 설정
        translation_progress["current"] = 100
        translation_progress["current_item"] = "번역 완료"
        
        response_data = {"download_urls": download_urls}
        if zip_download_url:
            response_data["zip_download_url"] = zip_download_url
        
        return jsonify(response_data)
        
    except Exception as e:
        logging.error(f"업로드 처리 중 예상치 못한 오류: {e}")
        return jsonify({"error": f"서버 오류가 발생했습니다: {str(e)}"}), 500

@app.route('/progress')
def get_progress():
    """번역 진행률 조회"""
    global translation_progress
    
    # 진행률이 유효한 범위(0-100)에 있는지 확인
    current_progress = max(0, min(100, translation_progress.get("current", 0)))
    
    return jsonify({
        "progress": current_progress,
        "current_count": translation_progress.get("current_count", 0),
        "total_count": translation_progress.get("total_count", 0),
        "current_item": translation_progress.get("current_item", "")
    })

@app.route('/download/<filename>')
def download_file(filename):
    """번역된 파일 다운로드"""
    try:
        safe_filename = secure_filename(filename)
        output_path = os.path.join(config.DOWNLOAD_FOLDER, safe_filename)
        
        if not os.path.exists(output_path):
            return jsonify({"error": "파일을 찾을 수 없습니다."}), 404
        
        return send_file(output_path, as_attachment=True, download_name=safe_filename)
        
    except Exception as e:
        logging.error(f"파일 다운로드 중 오류: {e}")
        return jsonify({"error": "파일 다운로드 중 오류가 발생했습니다."}), 500

# 임시 파일 정리 등록
atexit.register(clean_temporary_files)

if __name__ == "__main__":
    # 필요한 디렉토리 생성
    for folder in [config.UPLOAD_FOLDER, config.DOWNLOAD_FOLDER]:
        if not os.path.exists(folder):
            os.makedirs(folder)
    
    # 로깅 설정 (성능 최적화)
    log_handlers = [logging.StreamHandler()]
    
    # 파일 로깅은 ERROR 레벨 이상만 (성능 향상)
    if not os.path.exists('logs'):
        os.makedirs('logs')
    
    file_handler = logging.FileHandler('logs/translator_errors.log')
    file_handler.setLevel(logging.ERROR)
    log_handlers.append(file_handler)
    
    logging.basicConfig(
        level=config.LOG_LEVEL,  # WARNING 레벨로 설정
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=log_handlers
    )
    
    logging.warning("게임 로컬라이제이션 번역기 시작 (백그라운드 최적화 모드)")
    
    # Flask 앱 실행 (백그라운드 최적화)
    app.run(
        host='0.0.0.0', 
        port=5000, 
        debug=False,  # 디버그 모드 비활성화
        threaded=True,  # 멀티 스레드 활성화
        use_reloader=False  # 자동 재시작 비활성화
    )
