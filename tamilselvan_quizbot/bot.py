import csv
import os
import random
import asyncio
import time
import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, PollAnswerHandler, ContextTypes
)

QUIZ_FOLDER = "quizzes"
user_sessions = {}

# 🌟 Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "வணக்கம்! 🎯\n\n‘Menu’ இல் உள்ள “Quiz தொடங்கவும்” விருப்பத்தை அழுத்தி தொடங்கலாம்!\n\n"
        "அல்லது /quiz என type செய்து தொடங்கலாம்."
    )

# 🧠 /quiz – show subject folders
async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subjects = [f for f in os.listdir(QUIZ_FOLDER) if os.path.isdir(os.path.join(QUIZ_FOLDER, f))]
    topics_root = [f[:-4] for f in os.listdir(QUIZ_FOLDER) if f.endswith(".csv")]

    keyboard = []
    for s in subjects:
        keyboard.append([InlineKeyboardButton(s, callback_data=f"subject_{s}")])
    for t in topics_root:
        keyboard.append([InlineKeyboardButton(t, callback_data=f"play_@root|{t}")])

    if not keyboard:
        await update.message.reply_text("📂 எந்த Subject folders-மும் இல்லை.")
        return

    await update.message.reply_text("📘 ஒரு Subject தேர்வு செய்யவும் 👇", reply_markup=InlineKeyboardMarkup(keyboard))

# 📚 Subject selected
async def subject_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    subject = query.data.replace("subject_", "").strip()
    subject_path = os.path.join(QUIZ_FOLDER, subject)

    if not os.path.exists(subject_path):
        await query.edit_message_text("❌ அந்த Subject folder கிடைக்கவில்லை.")
        return

    files = [f[:-4] for f in os.listdir(subject_path) if f.endswith(".csv")]
    if not files:
        subjects = [f for f in os.listdir(QUIZ_FOLDER) if os.path.isdir(os.path.join(QUIZ_FOLDER, f))]
        keyboard = [[InlineKeyboardButton(s, callback_data=f"subject_{s}")] for s in subjects]
        await query.edit_message_text(
            f"'{subject}' folder-ல் எந்த topics-மும் இல்லை.\n\n📘 ஒரு Subject தேர்வு செய்யவும் 👇",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    context.user_data["selected_subject"] = subject
    keyboard = [[InlineKeyboardButton(name, callback_data=f"play_{subject}|{name}")] for name in files]
    await query.edit_message_text(f"📘 '{subject}' subject-இல் உள்ள Topic தேர்வு செய்யவும் 👇",
                                  reply_markup=InlineKeyboardMarkup(keyboard))

# 🎯 Topic selected → timer ask
async def play_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data.replace("play_", "")
    if "|" in data:
        if data.startswith("@root|"):
            _, topic = data.split("|", 1)
            subject = ""
        else:
            subject, topic = data.split("|", 1)
    else:
        subject = context.user_data.get("selected_subject", "")
        topic = data

    context.user_data["selected_subject"] = subject
    context.user_data["selected_topic"] = topic

    keyboard = [
        [InlineKeyboardButton("30 sec", callback_data="timer_30"),
         InlineKeyboardButton("45 sec", callback_data="timer_45"),
         InlineKeyboardButton("1 min", callback_data="timer_60")]
    ]
    await q.edit_message_text("⏱️ ஒவ்வொரு கேள்விக்கும் எத்தனை நேரம் வேண்டும்?",
                              reply_markup=InlineKeyboardMarkup(keyboard))

# 🎮 Timer selected → start quiz
async def timer_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    subject = context.user_data.get("selected_subject", "")
    topic = context.user_data.get("selected_topic", "")
    timer_value = int(q.data.replace("timer_", ""))

    if not topic:
        await q.edit_message_text("❌ பிழை: topic தேர்வு செய்யப்படவில்லை.")
        return

    file_path = os.path.join(QUIZ_FOLDER, subject, f"{topic}.csv") if subject else os.path.join(QUIZ_FOLDER, f"{topic}.csv")
    if not os.path.exists(file_path):
        await q.edit_message_text("❌ அந்த topic கிடைக்கவில்லை.")
        return

    user_id = q.from_user.id
    user_sessions[user_id] = create_new_session(subject, topic, timer_value, file_path)
    asyncio.create_task(send_questions(context, q.message.chat_id, user_id))
    await q.edit_message_text(f"📘 {topic} quiz ஆரம்பமாகிறது...\n⏱️ ஒவ்வொரு கேள்விக்கும் {timer_value} விநாடி நேரம்!")

# 🧩 Create session
def create_new_session(subject, topic, timer_value, file_path):
    session = {
        "subject": subject,
        "topic": topic,
        "timer": timer_value,
        "score": 0,
        "total": 0,
        "correct_q": [],
        "wrong_q": [],
        "missed_q": [],
        "polls": {},
        "pending_questions": [],
        "start_time": time.time(),
        "stopped": False,
        "active_poll_message_id": None,
        "shown_any": False
    }

    with open(file_path, newline='', encoding='utf-8-sig') as csvfile:
        reader = list(csv.DictReader(csvfile))
        random.shuffle(reader)
        for row in reader:
            question = row.get("question", "").replace("\\n", "\n").strip()
            options = [row.get(f"option{i}", "").strip() for i in range(1, 5)]
            options = [o for o in options if o]
            if not question or len(options) < 2:
                continue

            ans = row.get("answer", "1").strip()
            if ans.isdigit():
                correct_index = int(ans) - 1
            else:
                mapping = {"a": 0, "b": 1, "c": 2, "d": 3}
                correct_index = mapping.get(ans.lower(), 0)

            correct_text = options[correct_index] if correct_index < len(options) else options[0]
            random.shuffle(options)
            correct_option_index = options.index(correct_text)
            session["pending_questions"].append({
                "question": question,
                "options": options,
                "correct": correct_option_index
            })
    return session

# 🧩 Send quiz (fixed scoreboard logic)
async def send_questions(context, chat_id, user_id):
    s = user_sessions.get(user_id)
    if not s:
        return

    total = len(s["pending_questions"])
    s["total"] = total
    q_no = 1

    while s["pending_questions"]:
        if s["stopped"]:
            break

        q = s["pending_questions"].pop(0)
        question, opts, corr = q["question"], q["options"], q["correct"]
        await context.bot.send_message(chat_id, f"📘 (Q{q_no}/{total})\n\n{question}")

        msg = await context.bot.send_poll(
            chat_id,
            "சரியான விடை 👇",
            opts,
            type="quiz",
            correct_option_id=corr,
            is_anonymous=False,
            open_period=s["timer"]
        )

        s["shown_any"] = True
        s["active_poll_message_id"] = msg.message_id
        poll_event = asyncio.Event()
        s["polls"][msg.poll.id] = {"correct": corr, "event": poll_event, "question": question}

        try:
            await asyncio.wait_for(poll_event.wait(), timeout=s["timer"])
        except asyncio.TimeoutError:
            s["missed_q"].append(question)

        s["active_poll_message_id"] = None
        q_no += 1

        # small delay for smooth transition
        await asyncio.sleep(1)

    if not s["stopped"]:
        await show_results(context, chat_id, user_id)

# 🧮 Poll answer
async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    a = update.poll_answer
    uid = a.user.id
    s = user_sessions.get(uid)
    if not s:
        return
    pid = a.poll_id
    if pid not in s["polls"]:
        return
    correct = s["polls"][pid]["correct"]
    question = s["polls"][pid]["question"]
    selected = a.option_ids[0] if a.option_ids else -1
    if selected == correct:
        s["score"] += 1
        s["correct_q"].append(question)
    else:
        s["wrong_q"].append(question)
    s["polls"][pid]["event"].set()

# 🛑 Stop quiz
async def stop_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    s = user_sessions.get(uid)
    if not s:
        await update.message.reply_text("❌ தற்போது எந்த quiz-மும் நடைபெறவில்லை.")
        return

    s["stopped"] = True
    msg_id = s.get("active_poll_message_id")
    if msg_id:
        try:
            await context.bot.stop_poll(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass

    if not s["shown_any"]:
        await update.message.reply_text("⛔ Quiz நிறுத்தப்பட்டது! எந்த கேள்வியும் நடத்தப்படவில்லை.")
        del user_sessions[uid]
        return

    await update.message.reply_text("⛔ Quiz நிறுத்தப்பட்டது!")
    await show_results(context, chat_id, uid)
    del user_sessions[uid]

# 🏁 Results
async def show_results(context, chat_id, uid):
    s = user_sessions.get(uid)
    if not s:
        return
    elapsed = str(datetime.timedelta(seconds=int(time.time() - s["start_time"])))
    total = s["total"]
    correct = len(s["correct_q"])
    wrong = len(s["wrong_q"])
    missed = len(s["missed_q"])
    not_attend = total - (correct + wrong + missed)
    if not_attend < 0:
        not_attend = 0

    summary = (
        f"🏁 **Quiz முடிந்தது!**\n\n"
        f"⏱️ Duration: {elapsed}\n\n"
        f"📊 Total Questions: {total}\n"
        f"✅ Correct: {correct}\n"
        f"❌ Wrong: {wrong}\n"
        f"⚪ Missed: {missed}\n"
        f"🚫 Not Attended: {not_attend}\n\n"
        f"மொத்த மதிப்பெண்: {correct}/{total}"
    )

    subj_token = s['subject'] if s['subject'] else "@root"
    keyboard = [
        [InlineKeyboardButton("🔁 Retest", callback_data=f"retest_{subj_token}|{s['topic']}")],
        [InlineKeyboardButton("🆕 New Test", callback_data="new_test")]
    ]

    await context.bot.send_message(chat_id, summary, parse_mode="Markdown",
                                   reply_markup=InlineKeyboardMarkup(keyboard))

# 🔁 Retest / New Test
async def retest_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "new_test":
        await quiz(q, context)
        return

    payload = data.replace("retest_", "", 1)
    if "|" in payload:
        subject, topic = payload.split("|", 1)
    else:
        subject, topic = "", payload

    if subject == "@root":
        subject = ""

    file_path = (
        os.path.join(QUIZ_FOLDER, subject, f"{topic}.csv")
        if subject else os.path.join(QUIZ_FOLDER, f"{topic}.csv")
    )

    if not os.path.exists(file_path):
        await quiz(q, context)
        return

    context.user_data["selected_subject"] = subject
    context.user_data["selected_topic"] = topic

    keyboard = [
        [InlineKeyboardButton("30 sec", callback_data="timer_30"),
         InlineKeyboardButton("45 sec", callback_data="timer_45"),
         InlineKeyboardButton("1 min", callback_data="timer_60")]
    ]
    await q.edit_message_text(
        f"🔁 Retest: {topic}\n\n⏱️ நேரம் தேர்வு செய்யவும் 👇",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# 🚀 Main
def main():
    TOKEN = "8536407637:AAHeZlZCDEAzcg0LB-Zsi0a9kvwAL8Kxnkg"
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("quiz", quiz))
    app.add_handler(CommandHandler("stop", stop_quiz))
    app.add_handler(CallbackQueryHandler(subject_selected, pattern="^subject_"))
    app.add_handler(CallbackQueryHandler(play_callback, pattern="^play_"))
    app.add_handler(CallbackQueryHandler(timer_selected, pattern="^timer_"))
    app.add_handler(CallbackQueryHandler(retest_callback, pattern="^retest_|^new_test$"))
    app.add_handler(PollAnswerHandler(handle_poll_answer))

    print("✅ Bot Running (Personal Quiz Mode v5.1)")
    app.run_polling()

if __name__ == "__main__":
    main()
