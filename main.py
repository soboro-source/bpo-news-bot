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

    # 기존에 저장된 news.json 불러오기 (없거나 깨져 있으면 빈 목록으로 시작)
    existing_news = []
    if os.path.exists("news.json"):
        try:
            with open("news.json", "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, list):
                # 필수 항목이 있고 링크가 안전한 기사만 유지
                existing_news = [
                    item for item in loaded
                    if isinstance(item, dict)
                    and item.get("title") and item.get("date")
                    and is_safe_link(item.get("link", ""))
                ]
        except Exception as e:
            logging.error("기존 news.json 읽기 실패: %s", e)

    # 중복 수집 방지를 위한 기존 기사 URL 집합
    existing_urls = {item["link"] for item in existing_news}
    all_new_articles = []

    # 카테고리별로 새 기사 수집 (한 카테고리가 실패해도 나머지는 계속 진행)
    for category, keyword in categories.items():
        try:
            articles = get_and_save_news(category, keyword, existing_urls, max_limit=30)
            all_new_articles.extend(articles)
        except Exception as e:
            logging.error("%s 수집 실패: %s", category, e)

    # 스마트 중복 제거 로직 (제목 유사도 65% 초과 시 같은 기사로 간주)
    # 새 기사를 앞에 두어, 비슷한 기사가 있으면 새 기사가 우선 남도록 함
    combined_news = all_new_articles + existing_news
    unique_news = []
    seen_titles = []

    for item in combined_news:
        simplified_title = clean_title(item["title"])
        # 단순화한 제목이 너무 짧으면(4자 미만) 비교가 무의미하므로 제외
        if len(simplified_title) < 4:
            continue

        # 이미 통과시킨 제목들과 하나씩 유사도 비교
        is_duplicate = False
        for seen in seen_titles:
            similarity = difflib.SequenceMatcher(None, simplified_title, seen).ratio()
            if similarity > 0.65:
                is_duplicate = True
                break

        # 중복이 아닐 때만 최종 목록에 추가
        if not is_duplicate:
            seen_titles.append(simplified_title)
            unique_news.append(item)

    # ★ 3일이 지난 기사 자동 삭제(유통기한) 로직
    cutoff_date_str = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    final_news = [item for item in unique_news if item["date"] >= cutoff_date_str]

    # 최신 날짜순 정렬 후 최대 500건까지만 보관
    final_news.sort(key=lambda x: x["date"], reverse=True)
    final_news = final_news[:500]

    # 결과를 news.json에 저장 (한글이 깨지지 않도록 ensure_ascii=False)
    # 임시 파일에 먼저 쓴 뒤 교체하여, 저장 도중 오류로 파일이 깨지는 것을 방지
    tmp_path = "news.json.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(final_news, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, "news.json")

    logging.info("저장 완료: 총 %d건", len(final_news))


# 이 파일을 직접 실행했을 때만 news_bot() 실행 (import 시에는 실행 안 됨)
if __name__ == "__main__":
    news_bot()
