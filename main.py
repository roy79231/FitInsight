from flask import Flask, request, render_template, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import google.generativeai as genai
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = 'supersecretkey'

# ============ 資料庫設定 ============
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///fitinsight.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    mail = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    age = db.Column(db.Integer)
    gender = db.Column(db.String(10))
    height = db.Column(db.Float)
    weight = db.Column(db.Float)

class Schedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Integer, nullable=False)
    end_time = db.Column(db.Integer, nullable=False)
    action = db.Column(db.String(100), nullable=False)
    remark = db.Column(db.String(200))

class GeminiChat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    role = db.Column(db.String(10), nullable=False)  # 'user' or 'gemini'
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    db.create_all()

# ============ Gemini API 初始化 ============
genai.configure(api_key='AIzaSyBNBn7je9hOrk5ny-TjabghvHCXr6ZXHbQ')
model = genai.GenerativeModel('gemini-1.5-flash')

# ============ 路由設計 ============

@app.route('/')
def home():
    user_name = session.get('user_name')
    return render_template('index.html', user_name=user_name)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        mail = request.form['mail']
        password = request.form['password']
        age = request.form['age']
        gender = request.form['gender']
        height = request.form['height']
        weight = request.form['weight']

        if User.query.filter_by(mail=mail).first():
            flash('此信箱已被註冊')
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(password)
        new_user = User(
            name=name,
            mail=mail,
            password=hashed_password,
            age=int(age) if age else None,
            gender=gender,
            height=float(height) if height else None,
            weight=float(weight) if weight else None
        )
        db.session.add(new_user)
        db.session.commit()
        flash('註冊成功，請登入')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        mail = request.form['mail']
        password = request.form['password']
        user = User.query.filter_by(mail=mail).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['user_name'] = user.name
            flash('登入成功')
            return redirect(url_for('home'))
        else:
            flash('帳號或密碼錯誤')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('user_name', None)
    flash('您已成功登出')
    return redirect(url_for('home'))

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session:
        flash('請先登入')
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])

    if request.method == 'POST':
        user.name = request.form['name']
        user.age = int(request.form['age']) if request.form['age'] else None
        user.gender = request.form['gender']
        user.height = float(request.form['height']) if request.form['height'] else None
        user.weight = float(request.form['weight']) if request.form['weight'] else None
        db.session.commit()
        flash('資料已更新')
        return redirect(url_for('profile'))

    return render_template('profile.html', user=user)


@app.route('/analyze', methods=['GET', 'POST'])
def analyze():
    if 'user_id' not in session:
        flash('請先登入')
        return redirect(url_for('login'))

    if request.method == 'POST':
        user_goal = request.form['user_goal']  # 使用者輸入的目標

        # 撈使用者資料
        user = User.query.get(session['user_id'])
        now = datetime.now()  # ✅ 加這行
        current_date = now.strftime("%Y-%m-%d")
        current_time = now.strftime("%H:%M")

        # 撈最近 -7天 ~ +7天行程
        today = datetime.today().date()
        start_day = today - timedelta(days=7)
        end_day = today + timedelta(days=7)
        schedules = Schedule.query.filter(
            Schedule.user_id == session['user_id'],
            Schedule.start_date.between(start_day, end_day)
        ).all()

        # 整理現有行程成文字
        schedule_text = ""
        for sch in schedules:
            schedule_text += f"{sch.start_date} {sch.start_time:02d}:00~{sch.end_time:02d}:00 {sch.action}，{sch.remark or '無備註'}\n"

        # 建 prompt
        prompt = f"""
            你是一位專業私人健身教練。請依照以下使用者資料與近期行程，提供一份針對「{user_goal}」的未來7天運動行程規劃，並給出簡單建議。
            
            【目前時間】
            日期：{current_date}
            時間：{current_time}

            【使用者資料】
            姓名：{user.name}
            年齡：{user.age}
            性別：{user.gender}
            身高：{user.height} cm
            體重：{user.weight} kg

            【現有行程】
            {schedule_text}

            請直接輸出：
            1. 安排好的未來7天詳細運動行程（格式：YYYY-MM-DD 開始時間~結束時間 活動名稱，備註）。
            2. 運動建議（200字以內）。

            只需要以上兩項，請勿增加其他內容。
                    """

        # 呼叫 Gemini
        try:
            response = model.generate_content(prompt)
            result_text = response.text if hasattr(response, 'text') else str(response)
        except Exception as e:
            result_text = f"錯誤：{str(e)}"

        # 把 Gemini 結果暫存到 session，讓按儲存可以抓
        session['gemini_result'] = result_text

        # 新增一筆 user 輸入
        db.session.add(GeminiChat(
            user_id=session['user_id'],
            role='user',
            content=f"目標：{user_goal}"
        ))

        # 新增一筆 gemini 回應
        db.session.add(GeminiChat(
            user_id=session['user_id'],
            role='gemini',
            content=result_text
        ))
        db.session.commit()

        return render_template('analyze_result.html', result=result_text)

    return render_template('analyze_input.html')

@app.route('/apply_gemini_schedule', methods=['POST'])
def apply_gemini_schedule():
    if 'user_id' not in session:
        flash('請先登入')
        return redirect(url_for('login'))

    gemini_result = session.get('gemini_result')
    if not gemini_result:
        flash('找不到建議內容')
        return redirect(url_for('analyze'))

    # ✅ 改成只刪今天 ~ 未來7天的 Gemini 自動行程
    today = datetime.today().date()
    end_day = today + timedelta(days=7)

    # 如果有 source 欄位，就可以加 source='gemini'
    # 但目前沒有，只能直接新增
    lines = gemini_result.splitlines()
    for line in lines:
        line = line.strip()
        if not line or "~" not in line or "-" not in line:
            continue

        try:
            date_part, rest = line.split(' ', 1)
            date_obj = datetime.strptime(date_part, "%Y-%m-%d").date()
            # ✅ 只新增今天~未來7天的行程
            if not (today <= date_obj <= end_day):
                continue

            time_part, rest2 = rest.split(' ', 1)
            start_str, end_str = time_part.split('~')
            action_remark = rest2.split('，', 1)
            action = action_remark[0]
            remark = action_remark[1] if len(action_remark) > 1 else ''

            sch = Schedule(
                user_id=session['user_id'],
                start_date=date_obj,
                start_time=int(start_str.split(':')[0]),
                end_time=int(end_str.split(':')[0]),
                action=action,
                remark=remark
            )
            db.session.add(sch)
        except Exception:
            continue

    db.session.commit()
    flash('已將 Gemini 建議加入行事曆！（不會影響原自訂行程）')
    return redirect(url_for('schedule'))

@app.route('/refine_analyze', methods=['POST'])
def refine_analyze():
    if 'user_id' not in session:
        flash('請先登入')
        return redirect(url_for('login'))

    user_id = session['user_id']
    user_request = request.form.get('user_request')

    # 儲存使用者新要求
    db.session.add(GeminiChat(
        user_id=user_id,
        role='user',
        content=f"新要求：{user_request}"
    ))
    db.session.commit()

    # 抓取最近 3 次 Gemini + 使用者對話
    history = GeminiChat.query.filter_by(user_id=user_id).order_by(GeminiChat.timestamp.desc()).limit(6).all()
    history.reverse()  # 最舊的在前

    conversation = ""
    for chat in history:
        if chat.role == 'user':
            conversation += f"使用者：{chat.content}\n"
        else:
            conversation += f"Gemini：{chat.content}\n"

    prompt = f"""
你是一位專業私人健身教練。以下是我與你的過去對話，請根據最近的「使用者新要求」和之前的紀錄，重新設計出未來7天詳細運動行程並給出簡單建議。

{conversation}

請直接輸出：
1. 安排好的未來7天詳細運動行程（格式：YYYY-MM-DD 開始時間~結束時間 活動名稱，備註）。
2. 運動建議（200字以內）。

只需要以上兩項，請勿增加其他內容。
"""

    try:
        response = model.generate_content(prompt)
        result_text = response.text if hasattr(response, 'text') else str(response)
    except Exception as e:
        result_text = f"錯誤：{str(e)}"

    # 儲存 Gemini 回應
    db.session.add(GeminiChat(
        user_id=user_id,
        role='gemini',
        content=result_text
    ))
    db.session.commit()

    session['gemini_result'] = result_text
    return render_template('analyze_result.html', result=result_text)


@app.route('/schedule')
def schedule():
    if 'user_id' not in session:
        flash('請先登入')
        return redirect(url_for('login'))

    today = datetime.today().date()
    start_day = today - timedelta(days=7)
    end_day = today + timedelta(days=7)

    schedules = Schedule.query.filter(
        Schedule.user_id == session['user_id'],
        Schedule.start_date.between(start_day, end_day)
    ).all()

    # 整理資料以便前端使用
    schedule_map = {}
    for sch in schedules:
        for hour in range(sch.start_time, sch.end_time):
            key = f"{sch.start_date}-{hour}"
            schedule_map[key] = sch


    return render_template('schedule.html', today=today, schedule_map=schedule_map, timedelta=timedelta)

@app.route('/add_schedule', methods=['POST'])
def add_schedule():
    if 'user_id' not in session:
        flash('請先登入')
        return redirect(url_for('login'))

    start_date = request.form['start_date']
    start_time = int(request.form['start_time'])
    end_time = int(request.form['end_time'])
    action = request.form['action']
    remark = request.form.get('remark', '')

    start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()

    # 跨日邏輯
    if end_time <= start_time:
        # 第一天
        db.session.add(Schedule(
            user_id=session['user_id'],
            start_date=start_date_obj,
            start_time=start_time,
            end_time=24,
            action=action,
            remark=remark
        ))
        # 第二天
        next_day = start_date_obj + timedelta(days=1)
        db.session.add(Schedule(
            user_id=session['user_id'],
            start_date=next_day,
            start_time=0,
            end_time=end_time,
            action=action,
            remark=remark
        ))
    else:
        # 同一天
        db.session.add(Schedule(
            user_id=session['user_id'],
            start_date=start_date_obj,
            start_time=start_time,
            end_time=end_time,
            action=action,
            remark=remark
        ))

    db.session.commit()
    return redirect(url_for('schedule'))

@app.route('/edit_schedule/<int:schedule_id>', methods=['POST'])
def edit_schedule(schedule_id):
    schedule = Schedule.query.get(schedule_id)
    if not schedule or schedule.user_id != session['user_id']:
        flash('權限不足或行程不存在')
        return redirect(url_for('schedule'))

    schedule.start_date = datetime.strptime(request.form['start_date'], "%Y-%m-%d").date()
    schedule.start_time = int(request.form['start_time'])
    schedule.end_time = int(request.form['end_time'])
    schedule.action = request.form['action']
    schedule.remark = request.form.get('remark', '')
    db.session.commit()
    return redirect(url_for('schedule'))

@app.route('/delete_schedule/<int:schedule_id>', methods=['POST'])

def delete_schedule(schedule_id):
    schedule = Schedule.query.get(schedule_id)
    if not schedule or schedule.user_id != session['user_id']:
        flash('權限不足或行程不存在')
        return redirect(url_for('schedule'))

    db.session.delete(schedule)
    db.session.commit()
    return redirect(url_for('schedule'))

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

# ============ 主程式 ============

if __name__ == '__main__':
    app.run(debug=True)
