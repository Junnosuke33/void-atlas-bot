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

# --- 🧠 記憶領域（ユーザーごとの会話を一時保存） ---
user_histories = {}

# --- AIの設定 ---
safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
]

# AIへの指示書（会話モードを追加！）
system_prompt = """
あなたは求人広告の裏を読むプロ「ブラック求人判定君」です。毒舌な口調で話します。

【重要：行動ルール】
ユーザーの入力内容によって、以下の2つのモードを自動で切り替えてください。

1. **求人情報の分析モード**
   - ユーザーから「求人票のテキスト」が送られた場合。
   - 以下の**JSONデータのみ**を出力してください。余計な会話は不要です。
   - 出力フォーマット: {"danger_score": 数値, "verdict": "判定", "red_flags": ["罠1", "罠2"], "advice": "アドバイス"}

2. **通常会話モード**
   - ユーザーから「もっと詳しく」「これってどうなの？」「こんにちは」などの「質問・会話」が送られた場合。
   - JSONは使わず、**普通のテキスト**で毒舌に答えてください。
   - 直前の求人情報の内容を踏まえて回答してください。
"""

model = genai.GenerativeModel(
    model_name="gemini-2.5-flash",
    safety_settings=safety_settings,
    system_instruction=system_prompt
)

# --- Flex Message作成工場 ---
def create_bubble_json(data):
    score = data['danger_score']
    if score < 30:
        bar_color, text_color, icon = "#00cc00", "#00aa00", "😇"
    elif score < 70:
        bar_color, text_color, icon = "#ffcc00", "#999900", "🤔"
    else:
        bar_color, text_color, icon = "#ff0000", "#cc0000", "💀"

    bubble = {
        "type": "bubble",
        "header": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "ブラック求人判定レポート", "weight": "bold", "color": "#aaaaaa", "size": "xs"}]},
        "hero": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": f"{icon} 危険度", "size": "md", "weight": "bold"},
                {"type": "text", "text": f"{score}%", "size": "5xl", "weight": "bold", "color": text_color, "align": "center"},
                {"type": "text", "text": f"判定：{data['verdict']}", "size": "lg", "weight": "bold", "align": "center", "margin": "md"},
                {"type": "box", "layout": "vertical", "margin": "lg", "backgroundColor": "#e0e0e0", "cornerRadius": "md", "height": "10px", "width": "100%", "contents": [{"type": "box", "layout": "vertical", "width": f"{score}%", "backgroundColor": bar_color, "height": "10px", "cornerRadius": "md"}]}
            ]
        },
        "body": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "separator", "margin": "xl"},
                {"type": "text", "text": "🚩 検出された罠", "weight": "bold", "margin": "xl", "color": "#ff5555"},
                {"type": "box", "layout": "vertical", "margin": "sm", "spacing": "sm", "contents": [{"type": "text", "text": f"・{flag}", "size": "sm", "wrap": True} for flag in data['red_flags']]},
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
    user_id = event.source.user_id # ユーザーIDを取得

    try:
        # 1. そのユーザーの過去の会話履歴を取り出す（なければ新規作成）
        history = user_histories.get(user_id, [])
        
        # 2. 履歴付きでAIを起動
        chat = model.start_chat(history=history)
        response = chat.send_message(user_input)
        
        # 3. ユーザーの履歴を更新（最新の会話を保存）
        user_histories[user_id] = chat.history

        # 4. 返信タイプを判別（JSONならグラフ表示、それ以外なら会話）
        json_match = re.search(r"\{.*\}", response.text, re.DOTALL)

        if json_match:
            # --- パターンA：求人分析（JSONが見つかった） ---
            json_str = json_match.group(0)
            data = json.loads(json_str)
            
            # JSONに必要なデータ(danger_score)が入っているか確認
            if "danger_score" in data:
                flex_content = create_bubble_json(data)
                line_bot_api.reply_message(
                    event.reply_token,
                    FlexSendMessage(alt_text="判定結果", contents=flex_content)
                )
            else:
                # JSONだけど形式が違う場合は普通にテキストで返す
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=response.text)
                )
        else:
            # --- パターンB：雑談・質問（JSONがない） ---
            # AIの返事をそのままテキストで返す
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=response.text)
            )

    except Exception as e:
        # エラー時はリセット
        user_histories[user_id] = [] 
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"💦 エラーが発生しました。履歴をリセットします。\n({str(e)})")
        )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
