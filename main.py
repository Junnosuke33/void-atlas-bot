import os
import json
import re  # 👈 追加：文字を探すための強力なツール
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai

app = Flask(__name__)

# --- 3つの鍵をセット ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

# --- セットアップ ---
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
genai.configure(api_key=GEMINI_API_KEY)

# --- AIの設定 ---
# JSONだけを返すようにさらに厳しく指示
model = genai.GenerativeModel(
    model_name="gemini-pro",
    system_instruction="""
    あなたは求人広告の裏を読むプロ「ブラック求人判定君」です。
    ユーザーから送られた求人情報を分析し、以下のJSON形式のデータのみを出力してください。
    余計な挨拶やMarkdown記号（```jsonなど）は一切不要です。

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
        response = chat.send_message(f"以下の求人テキストから、不要な装飾を除去して本質を判定せよ:\n\n{user_input}")
        
        # 2. JSONを無理やり探し出す（ここが進化ポイント！）
        # AIが余計なことを喋っても、{ と } の間にあるデータだけを抜き取る
        json_match = re.search(r"\{.*\}", response.text, re.DOTALL)
        
        if json_match:
            json_str = json_match.group(0)
            data = json.loads(json_str)
            
            # 3. 返信メッセージを作る
            reply_text = f"💀 危険度: {data['danger_score']}%\n"
            reply_text += f"⚖️ 判定: {data['verdict']}\n\n"
            reply_text += "🚩 【検出された罠】\n"
            for flag in data['red_flags']:
                reply_text += f"・{flag}\n"
            reply_text += f"\n💡 {data['advice']}"
        else:
            # JSONが見つからなかった場合
            reply_text = "💦 判定不能でした。AIが混乱しているようです。"

    except Exception as e:
        print(f"Error: {e}")
        reply_text = "💦 エラーが発生しました。もう一度試してみてください。"

    # 4. LINEに返信する
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

