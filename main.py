import os
import json
import re
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage
import google.generativeai as genai

app = Flask(__name__)

# --- 3つの鍵 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
genai.configure(api_key=GEMINI_API_KEY)

# --- 🧠 記憶領域 ---
user_histories = {}

# --- 安全フィルター無効化 ---
safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
]

# --- 👿 AIへの指示書（ツンデレ悪魔Ver.） ---
system_prompt = """
お前は人間界の求人を鑑定してやる、魔界のツンデレ悪魔だ。
一人称は「オレ様」、二人称は「お前」や「人間」。
口調は偉そうでぶっきらぼうだが、結局は人間がブラック企業に騙されないように、しぶしぶ的確な助言をしてやる。

【重要：行動ルール】
ユーザーの入力内容によって、以下の2つのモードを自動で切り替えるんだな。

1. **求人鑑定モード**
   - 人間が「求人票のテキスト」を持ってきた場合だ。全く、手間をかけさせやがって。
   - 以下の**JSONデータのみ**を出力しろ。余計な口上は不要だ。
   - 出力フォーマット:
     {
        "danger_score": 0〜100の数値,
        "verdict": "判定（例：魔界級ブラック、薄汚いグレー、奇跡のホワイト など、悪魔っぽい表現で）",
        "red_flags": ["罠1（悪魔口調で指摘しろ）", "罠2", "罠3"],
        "advice": "しぶしぶ教えてやる辛口アドバイス（120文字以内。感謝しろよ？）"
     }

2. **通常会話モード**
   - 人間が「もっと詳しく」「こんにちは」などと話しかけてきた場合だ。
   - JSONは使うな。**普通のテキスト**で返事をしてやれ。
   - 面倒くさそうにしつつも、直前の求人の話を覚えておいて、ちゃんと相談に乗ってやれ。
"""

# 最新モデルを指定
model = genai.GenerativeModel(
    model_name="gemini-2.5-flash",
    safety_settings=safety_settings,
    system_instruction=system_prompt
)

# --- 🎨 魔界の鑑定書（Flex Message）作成工場 ---
def create_bubble_json(data):
    score = data['danger_score']
    
    # 4段階の色分け（75以上:赤, 50以上:橙, 30以上:黄, それ未満:緑）
    if score >= 75:
        bar_color, text_color, icon = "#ff0000", "#cc0000", "👿"
    elif score >= 50:
        bar_color, text_color, icon = "#ff9900", "#cc6600", "⚠️"
    elif score >= 30:
        bar_color, text_color, icon = "#ffcc00", "#999900", "🤔"
    else:
        bar_color, text_color, icon = "#00cc00", "#00aa00", "😇"

    bubble = {
        "type": "bubble",
        "styles": {"header": {"backgroundColor": "#2b2b2b"}, "body": {"backgroundColor": "#fafafa"}}, # ヘッダーを魔界っぽく黒に
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "📜 魔界の求人鑑定書", "weight": "bold", "color": "#ffdd55", "size": "sm", "align": "center"}
            ]
        },
        "hero": {
            "type": "box", "layout": "vertical", "paddingAll": "lg",
            "contents": [
                {"type": "text", "text": f"{icon} 危険度（魔界基準）", "size": "md", "weight": "bold", "color": "#333333"},
                {"type": "text", "text": f"{score}%", "size": "5xl", "weight": "bold", "color": text_color, "align": "center", "margin": "md"},
                {"type": "text", "text": f"判定：{data['verdict']}", "size": "md", "weight": "bold", "align": "center", "margin": "md", "color": "#555555"},
                {"type": "box", "layout": "vertical", "margin": "xl", "backgroundColor": "#e0e0e0", "cornerRadius": "md", "height": "12px", "width": "100%", "contents": [{"type": "box", "layout": "vertical", "width": f"{score}%", "backgroundColor": bar_color, "height": "12px", "cornerRadius": "md"}]}
            ]
        },
        "body": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "separator", "margin": "lg"},
                {"type": "text", "text": "👁️‍🗨️ 暴かれた魔界の罠", "weight": "bold", "margin": "xl", "color": "#d93025"},
                {"type": "box", "layout": "vertical", "margin": "md", "spacing": "sm", "contents": [{"type": "text", "text": f"💀 {flag}", "size": "sm", "wrap": True, "color": "#444444"} for flag in data['red_flags']]},
                {"type": "separator", "margin": "xl"},
                {"type": "text", "text": "😈 悪魔の囁き（アドバイス）", "weight": "bold", "margin": "xl", "color": "#673ab7"},
                {"type": "text", "text": data['advice'], "size": "sm", "wrap": True, "margin": "md", "color": "#333333"},
                # 免責事項（小さく）
                {"type": "separator", "margin": "xxl"},
                {"type": "box", "layout": "vertical", "margin": "md", "contents": [{"type": "text", "text": "※この判定は魔界のAIによるジョークだ。人間界の法律とは関係ないからな。エンタメとして楽しめよ。", "size": "xxs", "color": "#aaaaaa", "wrap": True, "align": "center"}]}
            ]
        }
    }
    return bubble

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_input = event.message.text
    user_id = event.source.user_id

    # ▼▼▼【即レス設定】ローディングアニメーションを表示 ▼▼▼
    try:
        # 「オレ様が鑑定してやるから、少し待て！」の合図
        line_bot_api.show_loading_animation(chat_id=user_id, loading_seconds=10) # 念のため長めに10秒設定
    except Exception as e:
        print(f"Animation Error: {e}")
    # ▲▲▲ 追加ここまで ▲▲▲

    try:
        history = user_histories.get(user_id, [])
        chat = model.start_chat(history=history)
        response = chat.send_message(user_input)
        user_histories[user_id] = chat.history

        json_match = re.search(r"\{.*\}", response.text, re.DOTALL)

        if json_match:
            json_str = json_match.group(0)
            try:
                data = json.loads(json_str)
                if "danger_score" in data:
                    flex_content = create_bubble_json(data)
                    line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="魔界からの鑑定結果が届いたぞ", contents=flex_content))
                else:
                    # JSONだが中身が足りない時
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
            except json.JSONDecodeError:
                # JSON解析失敗時
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
        else:
            # 通常会話モード
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))

    except Exception as e:
        user_histories[user_id] = []
        # エラー時も悪魔口調で
        error_msg = f"チッ、魔界の回線が混線したようだ…。エラーだと！？\n履歴はリセットしてやったぞ。\n\n(原因: {str(e)})"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=error_msg))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
