from datetime import datetime, timedelta
import json
import os
import re
import time
import urllib.parse
import difflib
import logging
import feedparser

# 로그 설정: 실행 시간·수집 건수·오류를 기록해 장애 원인을 추적할 수 있게 함
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)


def parse_rss_date(published_parsed):
    """RSS의 발행 시각(struct_time)을 'YYYY-MM-DD' 문자열로 변환한다.
    변환에 실패하면(값이 없거나 형식 오류) 오늘 날짜로 대체한다."""
    try:
        return time.strftime("%Y-%m-%d", published_parsed)
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")


def is_safe_link(url):
    """[보안] http/https 로 시작하는 링크만 허용한다.
    javascript:, data: 등 위험한 스킴이 섞여 들어오는 것을 차단한다."""
    try:
        parsed = urllib.parse.urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def clean_title(title):
    """중복 기사 비교를 위해 제목을 단순화한다.
    [속보], (사진) 같은 괄호 내용과 끝의 '- 언론사명'을 지우고,
    한글/영문/숫자만 남긴다."""
    cleaned = re.sub(r'\[.*?\]|\(.*?\)', '', title)      # 대괄호/소괄호와 그 안의 내용 제거
    cleaned = re.sub(r'\s*-\s*[^-]+$', '', cleaned)       # 제목 끝의 " - 언론사" 제거
    return re.sub(r'[^가-힣a-zA-Z0-9]', '', cleaned)       # 특수문자·공백 제거


def get_and_save_news(category_name, search_keyword, existing_urls, max_limit=30):
    """구글 뉴스 RSS에서 키워드로 기사를 검색해, 새 기사 목록을 반환한다.
    - 이미 저장된 URL은 건너뜀
    - http/https 가 아닌 링크는 건너뜀 (보안)
    - 오늘/어제 기사만 수집
    - 카테고리당 최대 max_limit건까지만 수집
    (함수명과 달리 파일 저장은 하지 않고, 저장은 news_bot()에서 처리한다.)
    ※ 기존의 기사 대표 이미지(og:image) 수집은 화면에서 쓰지 않고
      기사마다 외부 사이트에 접속하게 되므로 제거했다."""
    # 검색어를 URL에 넣을 수 있게 인코딩하고, 한국어/한국 지역 설정으로 RSS 주소 구성
    encoded_keyword = urllib.parse.quote(search_keyword)
    rss_url = f"https://news.google.com/rss/search?q={encoded_keyword}&hl=ko&gl=KR&ceid=KR:ko"
    feed = feedparser.parse(rss_url)

    if feed.bozo:
        logging.warning("RSS 파싱 경고 (%s): %s", category_name, feed.get("bozo_exception"))

    # 수집 대상 날짜: 오늘과 어제
    today_str = datetime.now().strftime("%Y-%m-%d")
    yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    new_articles = []
    success_count = 0

    for entry in feed.entries:
        # 수집 한도에 도달하면 중단
        if success_count >= max_limit:
            break

        title = entry.get("title", "")
        link = entry.get("link", "")

        # 제목/링크가 없거나, 이미 저장된 기사이거나, 안전하지 않은 링크면 건너뜀
        if not title or not link or link in existing_urls or not is_safe_link(link):
            continue

        # 오늘/어제 기사가 아니면 건너뜀
        article_date = parse_rss_date(entry.get("published_parsed"))
        if article_date not in [today_str, yesterday_str]:
            continue

        new_articles.append({
            "title": title,
            "link": link,
            "category": category_name,
            "date": article_date
        })
        success_count += 1

    logging.info("%s: 신규 %d건 수집", category_name, len(new_articles))
    return new_articles


def news_bot():
    """전체 흐름을 담당하는 메인 함수.
    카테고리별 뉴스 수집 → 기존 데이터와 병합 → 유사 기사 제거 →
    3일 지난 기사 삭제 → 최신순 정렬 후 news.json 저장"""

    # 카테고리별 구글 뉴스 검색 키워드 (OR 연산자로 여러 키워드를 한 번에 검색)
    categories = {
        "1. 자사 관련": '"KS한국고용정보" OR "한국고용정보" OR "KS잉그마" OR "CnAI" OR "KS신용정보"',
        "2. 경쟁사 동향": '"효성ITX" OR "트랜스코스모스" OR "메타넷엠플랫폼" OR "유베이스" OR "메타엠" OR "ktcs" OR "ktis" OR "제이앤비컨설팅" OR "아데코"',
        "3. 고객사 동향": '"국민은행" OR "신한은행" OR "우리은행" OR "하나은행" OR "쿠팡" OR "카카오페이" OR "배달의민족" OR "카카오뱅크" OR "국민건강보험공단" OR "국민연금공단" OR "지자체 콜센터" OR "정부부처 컨택센터"',
        "4. 관련 법 소식": '"근로기준법" OR "근로기준법 개정" OR "최저임금" OR "포괄임금" OR "교육생 근로자성 인정" OR "노동조합법" OR "주52시간제 지침" OR "직장 내 괴롭힘 지침" OR "감정노동자 보호법"',
        "5. 지원 정책": '"컨택센터 유치 지원" OR "중견기업 고용창출" OR "중견기업 세제지원" OR "고용 지원금" OR "장애인고용장려금" OR "장려금" OR "고용안정장려금 중견기업" OR "지자체 보조금 콜센터" OR "지방투자촉진보조금" OR "기업 인증제도" OR "중견기업 인증제" OR "기업 인증 신청"',
        "6. 기타 소식": '"화제" OR "꿀팁" OR "스트레칭" OR "영단어" OR "트렌드"'
    }

    # 기존에 저장된 news.json 불러오기 (없거나 깨
