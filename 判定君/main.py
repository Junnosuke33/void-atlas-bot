import os
import json
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai

app = Flask(__name__)

# --- 3つの鍵をセット（環境変数から読み込む） ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

# --- セットアップ ---
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
genai.configure(api_key=GEMINI_API_KEY)

# --- AIの設定（ブラック求人判定君の人格） ---
model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    system_instruction="""
    あなたは求人広告の裏を読むプロ「ブラック求人判定君」です。
    ユーザーから送られた求人情報を分析し、以下のJSON形式のみで回答してください。
    口調は少し毒舌で、断定的に話してください。

    {
        "danger_score": 0〜100の数値,
        "verdict": "ホワイト / 微妙 / ブラック / 監獄 のいずれか",
        "red_flags": ["怪しい点1", "怪しい点2", "怪しい点3"],
        "advice": "求職者への辛口アドバイス（ここを確認しろ等）"
    }
    """
)

# --- LINEからの通信を受け取る場所 ---
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# --- メッセージが届いた時の処理 ---
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_input = event.message.text
    
    # ユーザーに「確認中...」と伝える（省略可）
    # line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🔍 求人票をスキャン中..."))

    try:
        # 1. AIに判定させる
        chat = model.start_chat()
        response = chat.send_message(f"以下の求人を判定せよ:\n{user_input}")
        
        # 2. JSONを解析する
        text_resp = response.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(text_resp)
        
        # 3. 返信メッセージを作る
        reply_text = f"💀 危険度: {data['danger_score']}%\n"
        reply_text += f"⚖️ 判定: {data['verdict']}\n\n"
        reply_text += "🚩 【検出された罠】\n"
        for flag in data['red_flags']:
            reply_text += f"・{flag}\n"
        reply_text += f"\n💡 {data['advice']}"

    except Exception as e:
        # エラーが起きたら普通に返す
        reply_text = "💦 うまく判定できませんでした。求人票の文章をそのまま貼り付けてね！\n(エラー: AIがJSONを返しませんでした)"

    # 4. LINEに返信する
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)