from datetime import datetime, timedelta
import json
import os
import re
import time
import urllib.parse
import feedparser
import requests


def parse_rss_date(published_parsed):
  try:
    return time.strftime("%Y-%m-%d", published_parsed)
  except Exception:
    return datetime.now().strftime("%Y-%m-%d")


def get_og_image(url):
  """기사 원문 주소에서 대표 이미지(og:image) URL을 추출하는 함수"""
  try:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
        )
    }
    # 구글 뉴스 리다이렉션 방지를 위해 실제 기사 링크 추적
    response = requests.get(url, headers=headers, timeout=5)
    if response.status_code == 200:
      html = response.text
      # og:image 태그 검색
      match = re.search(
          r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
          html,
          re.IGNORECASE,
      )
      if not match:
        match = re.search(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            html,
            re.IGNORECASE,
        )

      if match:
        image_url = match.group(1)
        if image_url.startswith("//"):
          image_url = "https:" + image_url
        return image_url
  except Exception:
    pass
  return ""


def get_and_save_news(
    category_name, search_keyword, existing_urls, max_limit=30
):
  encoded_keyword = urllib.parse.quote(search_keyword)
  rss_url = f"https://news.google.com/rss/search?q={encoded_keyword}&hl=ko&gl=KR&ceid=KR:ko"
  feed = feedparser.parse(rss_url)
  today_str = datetime.now().strftime("%Y-%m-%d")
  yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

  new_articles = []
  success_count = 0

  for entry in feed.entries:
    if success_count >= max_limit:
      break
    title = entry.title
    link = entry.link
    if link in existing_urls:
      continue

    article_date = parse_rss_date(entry.published_parsed)
    if article_date not in [today_str, yesterday_str]:
      continue

    # 기사 원문에서 썸네일 이미지 추출
    image_url = get_og_image(link)

    new_articles.append({
        "title": title,
        "link": link,
        "category": category_name,
        "date": article_date,
        "image": image_url,  # 썸네일 URL 저장
    })
    success_count += 1

  return new_articles


def news_bot():
  categories = {
      "1. 자사 관련": (
          '"KS한국고용정보" OR "한국고용정보" OR "KS잉그마" OR "CnAI" OR'
          ' "KS신용정보"'
      ),
      "2. 경쟁사 동향": (
          '"효성ITX" OR "트랜스코스모스" OR "메타넷엠플랫폼" OR "유베이스" OR'
          ' "메타엠" OR "ktcs" OR "ktis" OR "제이앤비컨설팅" OR "아데코"'
      ),
      "3. 고객사 동향": (
          '"국민은행" OR "신한은행" OR "우리은행" OR "하나은행" OR "쿠팡" OR'
          ' "네이버" OR "배달의민족" OR "당근마켓" OR "국민건강보험공단" OR'
          ' "국민연금공단" OR "지자체 콜센터" OR "정부부처 컨택센터"'
      ),
      "4. 관련 법 소식": (
          '"근로기준법" OR "근로기준법 개정" OR "최저임금" OR "포괄임금" OR "교육생'
          ' 근로자성 인정" OR "노동조합법" OR "주52시간제 지침" OR "직장 내'
          ' 괴롭힘 지침" OR "감정노동자 보호법"'
      ),
      "5. 지원 정책": (
          '"컨택센터 유치 지원" OR "중견기업 고용창출" OR "중견기업 세제지원" OR'
          ' "고용 지원금" OR "장애인고용장려금" OR "장려금" OR "고용안정장려금'
          ' 중견기업" OR "지자체 보조금 콜센터" OR "지방투자촉진보조금" OR "기업'
          ' 인증제도" OR "중견기업 인증제" OR "기업 인증 신청"'
      ),
      "6. 기타 소식": (
          '"화제" OR "꿀팁" OR "스트레칭" OR "영단어" OR "트렌드"'
      ),
  }

  existing_news = []
  if os.path.exists("news.json"):
    with open("news.json", "r", encoding="utf-8") as f:
      try:
        existing_news = json.load(f)
      except Exception:
        pass

  existing_urls = {item["link"] for item in existing_news}
  all_new_articles = []

  for category, keyword in categories.items():
    articles = get_and_save_news(
        category, keyword, existing_urls, max_limit=30
    )
    all_new_articles.extend(articles)

  updated_news = all_new_articles + existing_news
  updated_news.sort(key=lambda x: x["date"], reverse=True)
  updated_news = updated_news[:500]

  with open("news.json", "w", encoding="utf-8") as f:
    json.dump(updated_news, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
  news_bot()
