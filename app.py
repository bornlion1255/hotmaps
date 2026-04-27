import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import pydeck as pdk
from datetime import datetime, timedelta
from geopy.geocoders import Nominatim

# --- НАСТРОЙКИ ---
geolocator = Nominatim(user_agent="qlean_intelligence_v3")
st.set_page_config(page_title="Qlean Intelligence Center", layout="wide", page_icon="🕵️")
px.defaults.template = "plotly_dark"

# --- ПРОВЕРКА ПАРОЛЯ ---
def check_password():
    def password_entered():
        if st.session_state["password"] == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False
    if "password_correct" not in st.session_state:
        st.text_input("Введите пароль доступа", type="password", on_change=password_entered, key="password")
        return False
    return st.session_state["password_correct"]

# --- API ФУНКЦИИ ---
@st.cache_data(ttl=3600)
def fetch_data(d_from, d_to):
    headers = {"Authorization": st.secrets["HOTMAPS_TOKEN"], "Content-Type": "application/json"}
    payload = {
        "locationGroupNames": ["химчистка", "otzovik"],
        "dateFrom": str(d_from), "dateTo": str(d_to),
        "hasText": True, "limit": 300, "sortBy": "date", "orderBy": "desc"
    }
    try:
        r = requests.post("https://app.hotmaps.pro/external-api/v1/projects/363/reviews", json=payload, headers=headers)
        return r.json().get('data', [])
    except: return []

def ask_ai(system_prompt, user_content):
    headers = {"Authorization": f"Bearer {st.secrets['ROUTER_API_KEY']}", "Content-Type": "application/json"}
    payload = {
        "model": "openai/gpt-4o", # Если ошибка будет про модель, поменяем на просто "gpt-4o"
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.3
    }
    try:
        r = requests.post("https://routerai.ru/api/v1/chat/completions", json=payload, headers=headers, timeout=45)
        response_data = r.json()
        
        # Проверяем, есть ли успешный ответ от нейросети
        if 'choices' in response_data:
            return response_data['choices'][0]['message']['content']
        else:
            # Если 'choices' нет, значит RouterAI прислал ошибку. Выводим её!
            return f"⛔ RouterAI ругается: {response_data}"
            
    except Exception as e:
        return f"🔌 Ошибка связи с API: {e}"

@st.cache_data(ttl=86400)
def get_coords(address):
    try:
        clean = address.replace("Russia, Moskva, ", "").replace("Москва, ", "")
        loc = geolocator.geocode(f"Москва, {clean}", timeout=5)
        return (loc.latitude, loc.longitude) if loc else (None, None)
    except: return None, None

# --- ГЛАВНЫЙ ЭКРАН ---
if check_password():
    st.markdown("<h1 style='text-align: center; color: #2ecc71;'>🕵️ Qlean: Intelligence Center</h1>", unsafe_allow_html=True)
    
    with st.sidebar:
        st.header("🎛 Фильтры")
        today = datetime.now()
        start = st.date_input("С", today - timedelta(days=30))
        end = st.date_input("По", today)
        btn = st.button("🔥 Запустить анализ", use_container_width=True)

    if btn:
        with st.spinner("Синхронизация с базой Hotmaps..."):
            data = fetch_data(start, end)
            df = pd.DataFrame(data)
            df['date'] = pd.to_datetime(df['date'])
            # Фильтр только химчистки
            df = df[(df['location_group'] == 'химчистка') | ((df['location_group'] == 'otzovik') & (df['store_code'] == 'otzovik_dry_cleaning'))]

        if not df.empty:
            # МЕТРИКИ
            m1, m2, m3 = st.columns(3)
            m1.metric("Всего отзывов за период", len(df))
            m2.metric("Средний NPS (Rating)", f"{df['rating'].mean():.2f} ⭐")
            
            # AI АНАЛИЗ (ГЛАВНЫЙ ОТЧЕТ)
            st.divider()
            st.subheader("🚀 Стратегический отчет AI")
            # --- УМНАЯ ПОДГОТОВКА КОНТЕКСТА ДЛЯ AI ---
            # 1. Берем только отзывы с текстом (пустые оценки нейросети не нужны)
            ai_df = df[df['text'].notna() & (df['text'].str.strip() != '')].copy()
            
            # 2. Собираем компактный список без лишних пробелов
            reviews_list = []
            for _, row in ai_df.iterrows():
                # Переводим дату в короткий формат
                date_str = row['date'].strftime('%Y-%m-%d')
                reviews_list.append(f"[{date_str}] Адрес: {row['location_address']} | Оценка: {row['rating']} | Текст: {row['text']}")
            
            # 3. Склеиваем и ставим "предохранитель" длины
            full_context = "\n".join(reviews_list)
            
            # 250 000 символов — это примерно 60-80 тысяч токенов. 
            # Идеально влезет в лимит 128k и оставит место для ответа AI.
            if len(full_context) > 250000:
                full_context = full_context[:250000] + "\n...[ДАННЫЕ ОБРЕЗАНЫ ИЗ-ЗА ЛИМИТА]"
            
            report_prompt = """Ты CPO Qlean. Проанализируй отзывы. 
            1. Выдели ТОП-3 системных проблемы с УКАЗАНИЕМ АДРЕСОВ. 
            2. Найди 'тихие риски' (когда оценка 4-5, но в тексте есть скрытая жалоба).
            3. Дай 3 жестких совета по операционке. Используй таблицы и списки."""
            
            st.info(ask_ai(report_prompt, f"ДАННЫЕ: {full_context}"))

            # КАРТА (ИНДИКАТОР НАСТРОЕНИЯ)
            st.divider()
            st.subheader("🗺️ Карта настроений (Hotspots)")
            
            with st.spinner("Геокодируем точки..."):
                # Группируем по адресу, чтобы точка была одна, но её цвет зависел от среднего
                map_data = df.groupby('location_address').agg({'rating': 'mean', 'id': 'count'}).reset_index()
                coords = map_data['location_address'].apply(get_coords)
                map_data['lat'] = [c[0] for c in coords]
                map_data['lon'] = [c[1] for c in coords]
                map_data = map_data.dropna(subset=['lat', 'lon'])

                # Логика цвета: если рейтинг < 3 - красный, > 4 - зеленый, иначе желтый
                def get_color(r):
                    if r <= 2.5: return [255, 0, 0, 160] # Красный
                    if r >= 4.0: return [46, 204, 113, 160] # Зеленый
                    return [241, 196, 15, 160] # Желтый
                
                map_data['color'] = map_data['rating'].apply(get_color)

                st.pydeck_chart(pdk.Deck(
                    map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
                    initial_view_state=pdk.ViewState(latitude=55.75, longitude=37.62, zoom=10, pitch=45),
                    layers=[
                        pdk.Layer(
                            'ScatterplotLayer',
                            data=map_data,
                            get_position='[lon, lat]',
                            get_color='color',
                            get_radius='id * 50', # Чем больше отзывов, тем больше точка
                            pickable=True,
                        ),
                    ],
                    tooltip={"text": "Адрес: {location_address}\nСредний рейтинг: {rating:.1f}\nОтзывов: {id}"}
                ))
            st.caption("🔴 - Критично, 🟡 - Средне, 🟢 - Хорошо. Размер точки = объем отзывов.")

            # ОНЛАЙН-ЧАТ
            st.divider()
            st.subheader("💬 Чат с AI-аналитиком")
            if "messages" not in st.session_state: st.session_state.messages = []
            
            for msg in st.session_state.messages:
                with st.chat_message(msg["role"]): st.markdown(msg["content"])

            if user_q := st.chat_input("На какой точке чаще всего портят вещи?"):
                st.session_state.messages.append({"role": "user", "content": user_q})
                with st.chat_message("user"): st.markdown(user_q)
                
                with st.chat_message("assistant"):
                    chat_context = f"Ты эксперт Qlean. Отвечай на основе этих данных: {full_context}. Вопрос: {user_q}"
                    ans = ask_ai("Отвечай кратко и только по фактам из данных.", chat_context)
                    st.markdown(ans)
                st.session_state.messages.append({"role": "assistant", "content": ans})

            # СЫРЫЕ ДАННЫЕ
            st.divider()
            with st.expander("📂 Посмотреть все данные за период"):
                st.dataframe(df[['date', 'rating', 'text', 'location_address', 'author_name']], use_container_width=True)
        else:
            st.warning("За выбранные даты данных в Hotmaps не найдено.")