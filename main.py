from datetime import datetime, timedelta
import json
import os
import re
import time
import urllib.parse
import feedparser
import requests
from bs4 import BeautifulSoup

def parse_rss_date(published_parsed):
    try:
        return time.strftime("%Y-%m-%d", published_parsed)
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")

def get_og_image(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    try:
        res = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        html = res.text
        current_url = res.url

        # 구글 리다이렉트 페이지에 갇힌 경우 (추적 로직 복구)
        if "news.google.com" in current_url or "consent.google.com" in current_url:
            soup = BeautifulSoup(html, 'html.parser')
            real_url = None
            
            # 1. <a> 태그에서 실제 주소 찾기
            a_tag = soup.find('a')
            if a_tag and a_tag.get('href') and a_tag.get('href').startswith('http'):
                real_url = a_tag['href']
            
            # 2. 스크립트 데이터에서 실제 주소 찾기
            if not real_url:
                match = re.search(r'(?:data-n-v|URL)=["\'](http[^"\']+)["\']', html, re.IGNORECASE)
                if match:
                    real_url = match.group(1)
                    
            if real_url:
                res = requests.get(real_url, headers=headers, timeout=10, allow_redirects=True)
                html = res.text
                current_url = res.url

        # 여전히 구글 도메인이면 썸네일 수집 포기
        if "google.com" in current_url:
            return ""

        # 언론사 원문 페이지에서 썸네일 추출
        soup = BeautifulSoup(html, 'html.parser')
        og_tag = soup.find('meta', property=re.compile(r'^og:image', re.I)) or soup.find('meta', attrs={'name': re.compile(r'^og:image', re.I)})
        
        if og_tag and og_tag.get('content'):
            img_url = og_tag['content'].strip()
            
            # 구글 로고 등 차단
            if "gstatic.com" in img_url or "google.com" in img_url or "googleusercontent.com" in img_url:
                return ""
                
            if img_url.startswith('//'):
                return 'https:' + img_url
            elif img_url.startswith('/'):
                return urllib.parse.urljoin(current_url, img_url)
            return img_url
            
    except Exception:
        pass
        
    return ""

def get_and_save_news(category_name, search_keyword, existing_urls, max_limit=30):
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
            
        image_url = get_og_image(link)

        new_articles.append({
            "title": title,
            "link": link,
            "category": category_name,
            "date": article_date,
            "image": image_url
        })
        success_count += 1
        
    return new_articles

def news_bot():
    categories = {
        "1. 자사 관련": '"KS한국고용정보" OR "한국고용정보" OR "KS잉그마" OR "CnAI" OR "KS신용정보"',
        "2. 경쟁사 동향": '"효성ITX" OR "트랜스코스모스" OR "메타넷엠플랫폼" OR "유베이스" OR "메타엠" OR "ktcs" OR "ktis" OR "제이앤비컨설팅" OR "아데코"',
        "3. 고객사 동향": '"국민은행" OR "신한은행" OR "우리은행" OR "하나은행" OR "쿠팡" OR "네이버" OR "배달의민족" OR "당근마켓" OR "국민건강보험공단" OR "국민연금공단" OR "지자체 콜센터" OR "정부부처 컨택센터"',
        "4. 관련 법 소식": '"근로기준법" OR "근로기준법 개정" OR "최저임금" OR "포괄임금" OR "교육생 근로자성 인정" OR "노동조합법" OR "주52시간제 지침" OR "직장 내 괴롭힘 지침" OR "감정노동자 보호법"',
        "5. 지원 정책": '"컨택센터 유치 지원" OR "중견기업 고용창출" OR "중견기업 세제지원" OR "고용 지원금" OR "장애인고용장려금" OR "장려금" OR "고용안정장려금 중견기업" OR "지자체 보조금 콜센터" OR "지방투자촉진보조금" OR "기업 인증제도" OR "중견기업 인증제" OR "기업 인증 신청"',
        "6. 기타 소식": '"화제" OR "꿀팁" OR "스트레칭" OR "영단어" OR "트렌드"'
    }

    existing_news = []
    if os.path.exists("news.json"):
        with open("news.json", "r", encoding="utf-8") as f:
            try:
                existing_news = json.load(f)
            except Exception:
                pass
                
    # 빈칸("") 이미지나 구글 로고 이미지를 가진 기존 데이터 삭제 처리
    cleaned_existing_news = []
    for item in existing_news:
        img = item.get("image", "")
        if img == "" or "googleusercontent.com" in img or "google.com" in img or "gstatic.com" in img:
            continue
        cleaned_existing_news.append(item)
        
    existing_news = cleaned_existing_news
                
    existing_urls = {item["link"] for item in existing_news}
    all_new_articles = []
    
    for category, keyword in categories.items():
        articles = get_and_save_news(category, keyword, existing_urls, max_limit=30)
        all_new_articles.extend(articles)
        
    updated_news = all_new_articles + existing_news
    updated_news.sort(key=lambda x: x["date"], reverse=True)
    updated_news = updated_news[:500]

    with open("news.json", "w", encoding="utf-8") as f:
        json.dump(updated_news, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    news_bot()
