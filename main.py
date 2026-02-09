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

# --- AIモデル設定（Gemini 2.5 Flash） ---
safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
]

model = genai.GenerativeModel(
    model_name="gemini-2.5-flash",
    safety_settings=safety_settings,
    system_instruction="""
    あなたは求人広告の裏を読むプロ「ブラック求人判定君」です。
    ユーザーから送られた求人情報を分析し、以下のJSON形式のデータのみを出力してください。
    
    出力フォーマット:
    {
        "danger_score": 0〜100の数値,
        "verdict": "判定結果（ホワイト / 微妙 / ブラック / 監獄 のいずれか）",
        "red_flags": ["短い箇条書き1", "短い箇条書き2", "短い箇条書き3"],
        "advice": "求職者への辛口アドバイス（100文字以内）"
    }
    """
)

# --- 🎨 ここが新機能！Flex Messageを作る工場 ---
def create_bubble_json(data):
    score = data['danger_score']
    
    # スコアに応じて色を変える（安全=緑、注意=黄、危険=赤）
    if score < 30:
        bar_color = "#00cc00" # 緑
        text_color = "#00aa00"
        icon = "😇"
    elif score < 70:
        bar_color = "#ffcc00" # 黄
        text_color = "#999900"
        icon = "🤔"
    else:
        bar_color = "#ff0000" # 赤
        text_color = "#cc0000"
        icon = "💀"

    # Flex Messageの設計図（JSON）
    bubble = {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "ブラック求人判定レポート", "weight": "bold", "color": "#aaaaaa", "size": "xs"}
            ]
        },
        "hero": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": f"{icon} 危険度", "size": "md", "weight": "bold"},
                {"type": "text", "text": f"{score}%", "size": "5xl", "weight": "bold", "color": text_color, "align": "center"},
                {"type": "text", "text": f"判定：{data['verdict']}", "size": "lg", "weight": "bold", "align": "center", "margin": "md"},
                # ▼ ここがグラフの部分！
                {
                    "type": "box",
                    "layout": "vertical",
                    "margin": "lg",
                    "backgroundColor": "#e0e0e0",
                    "cornerRadius": "md",
                    "height": "10px",
                    "width": "100%",
                    "contents": [
                        {
                            "type": "box",
                            "layout": "vertical",
                            "width": f"{score}%", # ここで長さを決める
                            "backgroundColor": bar_color,
                            "height": "10px",
                            "cornerRadius": "md"
                        }
                    ]
                }
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "separator", "margin": "xl"},
                {"type": "text", "text": "🚩 検出された罠", "weight": "bold", "margin": "xl", "color": "#ff5555"},
                # 罠リストを動的に追加
                {
                    "type": "box",
                    "layout": "vertical",
                    "margin": "sm",
                    "spacing": "sm",
                    "contents": [{"type": "text", "text": f"・{flag}", "size": "sm", "wrap": True} for flag in data['red_flags']]
                },
                {"type": "separator", "margin": "xl"},
                {"type": "text", "text": "💡 アドバイス", "weight": "bold", "margin": "xl", "color": "#5555ff"},
                {"type": "text", "text": data['advice'], "size": "sm", "wrap": True, "margin": "sm", "color": "#666666"}
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
    
    try:
        chat = model.start_chat()
        response = chat.send_message(f"以下の求人テキストを判定せよ:\n\n{user_input}")
        
        json_match = re.search(r"\{.*\}", response.text, re.DOTALL)
        
        if json_match:
            json_str = json_match.group(0)
            data = json.loads(json_str)
            
            # 作った設計図を使って、Flex Messageとして返信する
            flex_content = create_bubble_json(data)
            line_bot_api.reply_message(
                event.reply_token,
                FlexSendMessage(alt_text="判定結果が届きました", contents=flex_content)
            )
        else:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"💦 判定不能でした。\nAIの返答: {response.text}")
            )

    except Exception as e:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"💦 エラーが発生しました。\n({str(e)})")
        )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
