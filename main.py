import os
import json
import re
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai

app = Flask(__name__)

# --- 3つの鍵 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
genai.configure(api_key=GEMINI_API_KEY)

# --- 安全フィルター無効化 ---
safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
]

# とりあえず標準の 'gemini-1.5-flash' を指定
model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    safety_settings=safety_settings,
    system_instruction="""
    あなたは求人広告の裏を読むプロ「ブラック求人判定君」です。
    ユーザーから送られた求人情報を分析し、以下のJSON形式のデータのみを出力してください。
    出力フォーマット:
    {
        "danger_score": 0〜100の数値,
        "verdict": "ホワイト / 微妙 / ブラック / 監獄 のいずれか",
        "red_flags": ["怪しい点1", "怪しい点2", "怪しい点3"],
        "advice": "求職者への辛口アドバイス"
    }
    """
)

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
        # 1. AIに判定させる
        chat = model.start_chat()
        response = chat.send_message(f"以下の求人テキストを判定せよ:\n\n{user_input}")
        
        # 2. JSONを探す
        json_match = re.search(r"\{.*\}", response.text, re.DOTALL)
        
        if json_match:
            json_str = json_match.group(0)
            data = json.loads(json_str)
            reply_text = f"💀 危険度: {data['danger_score']}%\n"
            reply_text += f"⚖️ 判定: {data['verdict']}\n\n"
            reply_text += "🚩 【検出された罠】\n"
            for flag in data['red_flags']:
                reply_text += f"・{flag}\n"
            reply_text += f"\n💡 {data['advice']}"
        else:
            reply_text = f"💦 判定不能でした。\nAIの返答: {response.text}"

    except Exception as e:
        # 🕵️‍♂️ ここが名探偵モード！
        # エラーが起きたら、使えるモデル一覧をGoogleに問い合わせてLINEに送る
        try:
            available_models = []
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    available_models.append(m.name)
            
            error_msg = f"👾 モデル名エラー！\nあなたのキーで使えるモデル一覧:\n"
            error_msg += "\n".join(available_models)
            reply_text = error_msg
        except Exception as e2:
            reply_text = f"👾 完全敗北...\nモデル一覧も取得できませんでした。\nKeyの設定を確認してください。\n\n元のエラー: {str(e)}"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
