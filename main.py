import os
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import re
from urllib.parse import quote, urlparse, parse_qs
from openai import OpenAI
from linebot import LineBotApi
from linebot.models import TextSendMessage
import time
from dotenv import load_dotenv

load_dotenv()

class AINewsBot:
    """AIニュース自動配信システム（GitHub Actions版）"""
    
    def __init__(self):
        """GitHub Secrets から APIキーを取得"""
        print("🚀 AIニュースボット初期化中...")
        
        # GitHub Secretsから環境変数として取得
        self.openai_api_key = os.environ.get('OPENAI_API_KEY')
        self.line_access_token = os.environ.get('LINE_ACCESS_TOKEN')
        
        if not self.openai_api_key or not self.line_access_token:
            raise ValueError("GitHub SecretsでAPIキーを設定してください")
        
        print("OPENAI_API_KEY:", "あり" if self.openai_api_key else "なし")
        print("LINE_ACCESS_TOKEN:", "あり" if self.line_access_token else "なし")
        
        # クライアント初期化
        self.openai_client = OpenAI(api_key=self.openai_api_key)
        self.line_bot_api = LineBotApi(self.line_access_token)
        print("✅ 初期化完了")
    
    def get_japanese_ai_news_google_rss(self):
        """Google News RSSで日本語AIニュースを取得"""
        print("📰 Google News RSSでAIニュース取得開始...")
        
        search_queries = [
            'AI OR ChatGPT OR "生成AI"',
            '"人工知能" OR OpenAI OR Claude',
            '"機械学習" OR "ディープラーニング"'
        ]
        
        all_articles = []
        base_url = "https://news.google.com/rss/search"
        
        for i, query in enumerate(search_queries, 1):
            print(f"🔍 検索中 ({i}/{len(search_queries)}): {query}")
            
            params = {
                'q': query,
                'hl': 'ja',
                'gl': 'JP',
                'ceid': 'JP:ja',
                'when': '1d'
            }
            
            param_string = '&'.join([f"{k}={quote(str(v))}" for k, v in params.items()])
            full_url = f"{base_url}?{param_string}"
            
            try:
                response = requests.get(full_url, timeout=20)
                response.raise_for_status()
                
                root = ET.fromstring(response.content)
                items = root.findall('.//item')
                
                for item in items[:5]:
                    title_elem = item.find('title')
                    link_elem = item.find('link')
                    pub_date_elem = item.find('pubDate')
                    description_elem = item.find('description')
                    source_elem = item.find('source')
                    
                    if title_elem is not None:
                        title = title_elem.text
                        link = link_elem.text if link_elem is not None else ''
                        pub_date = pub_date_elem.text if pub_date_elem is not None else ''
                        description = description_elem.text if description_elem is not None else ''
                        source = source_elem.text if source_elem is not None else 'Google News'
                        
                        if description:
                            description = re.sub(r'<[^>]+>', '', description).strip()
                        
                        if not any(article['title'] == title for article in all_articles):
                            all_articles.append({
                                'title': title,
                                'description': description,
                                'source': source,
                                'url': link,
                                'pub_date': pub_date,
                                'query': query
                            })
                
                print(f"   ✅ {len(items)}件の記事を発見")
                time.sleep(1)
                
            except Exception as e:
                print(f"   ❌ {query}の取得エラー: {e}")
                continue
        
        return all_articles[:6]
    
    def generate_news_summary_with_gpt(self, articles):
        """GPT APIでニュース要約を生成"""
        if not articles:
            return "要約するニュース記事がありませんでした。"
        
        print(f"🤖 GPTで要約生成開始 (対象: {len(articles)}件)")
        
        news_text = ""
        for i, article in enumerate(articles, 1):
            formatted_date = self.format_article_date(article['pub_date'])
            clean_url = self.clean_google_news_url(article['url'])
            
            news_text += f"【記事{i}】\n"
            news_text += f"タイトル: {article['title']}\n"
            if article['description'] and len(article['description']) > 20:
                description = article['description'][:150] + '...' if len(article['description']) > 150 else article['description']
                news_text += f"内容: {description}\n"
            news_text += f"配信元: {article['source']}\n"
            news_text += f"日時: {formatted_date}\n"
            news_text += f"リンク: {clean_url}\n\n"
        
        try:
            chat_completion = self.openai_client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": """あなたは日本のAI・テクノロジーニュースの専門要約者です。
                        LINEメッセージ向けに以下の形式で要約を作成してください：
                        
                        【重要な制約事項】
                        - Markdown記法は絶対に使用禁止
                        - 各ニュースは「1️⃣」「2️⃣」などの数字絵文字で番号付け
                        - 強調は【】や絵文字を使用
                        - 各ニュースの要約後に必ず引用元URLを「🔗 URL」の形式で記載
                        - URLは短縮せず完全な形で掲載
                        - 区切り線は「━━━━━━━━━━━━━━━━━━」を使用
                        - 全体で1200文字以内に収める
                        - 重要なニュースを3-5件選んで要約"""
                    },
                    {
                        "role": "user",
                        "content": f"以下のAIニュースをLINE向けに要約してください（リンク必須）：\n\n{news_text}"
                    }
                ],
                model="gpt-4o-mini",
                max_tokens=1500,
                temperature=0.7
            )
            
            summary = chat_completion.choices[0].message.content
            print("✅ GPT要約生成完了")
            return summary
            
        except Exception as e:
            print(f"❌ GPT要約生成エラー: {e}")
            return self.create_fallback_summary_with_links(articles)
    
    def format_article_date(self, pub_date):
        """記事の日付をフォーマット"""
        if not pub_date:
            return "日時不明"
        
        try:
            dt = datetime.strptime(pub_date, '%a, %d %b %Y %H:%M:%S %Z')
            return dt.strftime('%Y年%m月%d日 %H:%M')
        except ValueError:
            try:
                dt = datetime.strptime(pub_date.split(' GMT')[0], '%a, %d %b %Y %H:%M:%S')
                return dt.strftime('%Y年%m月%d日 %H:%M')
            except ValueError:
                return pub_date
    
    def clean_google_news_url(self, url):
        """Google NewsのリダイレクトURLを元記事URLに変換"""
        try:
            if 'news.google.com' in url and 'url=' in url:
                parsed = urlparse(url)
                params = parse_qs(parsed.query)
                if 'url' in params:
                    return params['url'][0]
            return url
        except Exception:
            return url
    
    def create_fallback_summary_with_links(self, articles):
        """GPT失敗時のフォールバック要約"""
        print("📝 フォールバック要約生成中")
        
        summary = "🤖 今日のAIニュースまとめ\n\n"
        number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
        
        for i, article in enumerate(articles[:5]):
            emoji = number_emojis[i] if i < len(number_emojis) else f"{i+1}️⃣"
            title = article['title'][:40] + "..." if len(article['title']) > 40 else article['title']
            source = article['source']
            formatted_date = self.format_article_date(article['pub_date'])
            clean_url = self.clean_google_news_url(article['url'])
            
            summary += f"{emoji}【{title}】\n"
            
            if article['description'] and len(article['description']) > 20:
                desc = article['description'][:80] + "..." if len(article['description']) > 80 else article['description']
                summary += f"{desc}\n"
            
            summary += f"📰 {source}\n"
            summary += f"📅 {formatted_date}\n"
            summary += f"🔗 {clean_url}\n\n"
        
        summary += "━━━━━━━━━━━━━━━━━━\n"
        summary += f"📱 AIニュース自動配信システム\n"
        summary += f"🕐 {datetime.now().strftime('%Y年%m月%d日 %H:%M')}"
        
        return summary
    
    def send_line_notification(self, message):
        """LINE通知を送信"""
        print("📱 LINE通知送信中...")
        
        try:
            if len(message) > 4000:
                message = message[:3950] + "\n\n... (文字数制限により省略)"
            
            url_count = len(re.findall(r'https?://[^\s\n]+', message))
            print(f"📊 送信メッセージ: {len(message)}文字, {url_count}個のリンク")
            
            self.line_bot_api.broadcast(TextSendMessage(text=message))
            print("✅ LINE通知送信完了")
            
        except Exception as e:
            print(f"❌ LINE通知送信エラー: {e}")
            raise e
    
    def run_news_process(self):
        """メインのニュース処理プロセス"""
        print("🚀 AIニュース自動配信システム開始（GitHub Actions）")
        
        try:
            articles = self.get_japanese_ai_news_google_rss()
            
            if not articles:
                print("💡 取得するニュースがありませんでした")
                return False
            
            summary_text = self.generate_news_summary_with_gpt(articles)
            self.send_line_notification(summary_text)
            
            print("🎉 AIニュース配信完了！")
            return True
            
        except Exception as e:
            print(f"❌ 致命的エラー: {e}")
            try:
                self.send_line_notification(f"AIニュース処理中にエラーが発生しました: {str(e)[:100]}")
            except:
                pass
            return False

# 実行部分
if __name__ == "__main__":
    try:
        bot = AINewsBot()
        bot.run_news_process()
    except Exception as e:
        print(f"💥 初期化エラー: {e}")
