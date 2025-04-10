**사용시에 요금이 발생될수 있습니다**
##### ___구글은 기쁘다___

코드는 gpt 를 통해제작되었습니다

4070 슈퍼 기준 gemma2:27b 가 메우메우 오래 걸립니다 올라마 ai 번역은 웬만하면 사용하지 마세요

## 사용법
이 또한 gpt 로 작성하였습니다

---


# 🎮 게임 로컬라이제이션 자동 번역기 (Paradox YML Translator)

Paradox Interactive 스타일의 `l_english.yml` 같은 게임 로컬라이제이션 파일을 쉽게 번역할 수 있는 웹 앱입니다.  
**파일을 업로드하고, 번역 API와 언어만 선택하면 자동 번역!**

---

## 📦 주요 기능

- `.yml` 형식의 로컬라이제이션 파일 자동 파싱
- Google Cloud, OpenAI GPT, Ollama(로컬 AI) 선택 가능
- 웹 UI에서 파일 업로드 및 다운로드 지원
- 번역 진행률 실시간 표시

---

## 🖥️ 설치 방법 (누구나 따라할 수 있어요!)

### 1. Python 설치

먼저 Python이 설치되어 있어야 해요.

- [여기 클릭해서 Python 설치](https://www.python.org/downloads/)  
- 설치할 때 **“Add Python to PATH”** 꼭 체크하세요! (중요!)

---

### 2. 프로젝트 파일 받요
`

2. 폴더 구조는 아래처럼 돼 있어야 해요:

```
프로젝트/
├── ss.py
├── .env          ← 직접 만들게 돼요
├── templates/
│   └── index.html
```

---

### 3. 필수 라이브러리 설치

터미널(cmd, PowerShell, 또는 mac/Linux 터미널)에서 아래 명령어를 복사해서 붙여넣고 실행하세요:

```bash
pip install flask google-cloud-translate python-dotenv requests openai
```

---

### 4. 환경 설정 (.env 파일 만들기)

프로젝트 폴더에 `.env`라는 파일을 새로 만들고 아래처럼 적어주세요:

```
# 구글 번역용 서비스 키 파일 경로
GOOGLE_APPLICATION_CREDENTIALS=구글_키_파일_경로.json

# OpenAI API 키 (사용할 경우)
OPENAI_API_KEY=sk-여기에_키_입력
```

예시:

```
GOOGLE_APPLICATION_CREDENTIALS=C:/Users/내이름/Downloads/google-key.json
OPENAI_API_KEY=sk-abc123...
```

> 💡 구글 키 파일이 없다면 [구글 클라우드 콘솔](https://console.cloud.google.com/)에서 만들 수 있어요.

---

### 5. 웹 서버 실행

아래 명령어를 터미널에 입력하세요:

```bash
python ss.py
```

정상 실행되면 이렇게 나와요:

```
Running on http://127.0.0.1:5000/ (Press CTRL+C to quit)
```

---

### 6. 사용법 (웹에서 진행!)

1. 웹 브라우저에서 주소창에 아래 주소를 입력해요:

```
http://localhost:5000
```

2. 웹페이지가 열리면:

- 번역할 `.yml` 파일 선택
- 번역 API (구글, OpenAI, Ollama 중 택 1)
- 번역 언어 선택 (예: 한국어)
- “번역 시작” 버튼 클릭!

3. 번역이 끝나면 다운로드 링크가 뜹니다. 클릭해서 파일을 저장하면 완료!

---

## 🧠 자주 묻는 질문 (FAQ)

### ❓ 번역이 안 돼요!
- `.yml` 파일 형식을 다시 확인해보세요.
- OpenAI나 Google을 선택했다면 API 키가 `.env`에 제대로 적혀 있는지 확인하세요.
- Ollama 사용 시 로컬 서버가 실행 중이어야 합니다.

### ❓ Ollama는 뭔가요?
로컬에서 AI를 직접 실행하는 도구예요. GPT처럼 작동하지만 인터넷 없이도 돌아갑니다. [Ollama 공식 사이트](https://ollama.com) 참고!

---

## 📌 참고사항

- Google 번역 API는 유료이며 일정 금액 이상 사용하면 과금될 수 있습니다.
- OpenAI 역시 API 사용량에 따라 요금이 청구됩니다.
- 이 도구는 학습, 모드 제작, 개인용 번역에 유용합니다.

---

## 🙏 만든이

개발자: @kskskwi2
문의 및 제안: 이슈 또는 PR 환영합니다!


---

### 📝 추가 팁:

- `.env` 파일은 깃허브에 업로드하지 않도록 `.gitignore`에 포함시키세요.
- 깃허브 Pages와는 달리 이 앱은 Python 백엔드가 필요하므로 **로컬 실행용**입니다.

### 기타문의

kskskwi19 디스코드 dm 으로

## 라이선스
GNU Affero General Public License v3.0 에 따라주세요

요약 (이는 요약이며 이걸로인한 법적 불이익이 발생될수 있습니다)

상업적 이용 금지

만약 배포시 같은 라이선스 유지

