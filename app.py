import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import pydeck as pdk
from datetime import datetime, timedelta
from geopy.geocoders import Nominatim
import time

# --- НАСТРОЙКИ ---
geolocator = Nominatim(user_agent="qlean_intel_dashboard_v5")
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
        "model": "openai/gpt-4o", 
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.3
    }
    try:
        r = requests.post("https://routerai.ru/api/v1/chat/completions", json=payload, headers=headers, timeout=45)
        response_data = r.json()
        if 'choices' in response_data:
            return response_data['choices'][0]['message']['content']
        else:
            return f"⛔ Ошибка API: {response_data}"
    except Exception as e:
        return f"🔌 Ошибка связи: {e}"

@st.cache_data(ttl=86400)
def get_coords(address):
    """Геокодирование с кэшированием"""
    try:
        clean = address.replace("Russia, Moskva, ", "").replace("Москва, ", "")
        loc = geolocator.geocode(f"Москва, {clean}", timeout=10)
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
            df = df[(df['location_group'] == 'химчистка') | ((df['location_group'] == 'otzovik') & (df['store_code'] == 'otzovik_dry_cleaning'))]

        if not df.empty:
            # --- БЛОК 1: ОСНОВНЫЕ МЕТРИКИ ---
            m1, m2, m3 = st.columns(3)
            m1.metric("Всего отзывов", len(df))
            m2.metric("Средний NPS", f"{df['rating'].mean():.2f} ⭐")
            m3.metric("Критические жалобы", len(df[df['rating'] <= 2]))
            
            st.divider()

            # --- БЛОК 2: ГРАФИКИ (Которые я случайно удалил в прошлый раз) ---
            st.subheader("📊 Аналитика настроений")
            col_chart1, col_chart2 = st.columns(2)
            
            with col_chart1:
                # Если колонка 'emotions' есть в данных
                if 'emotions' in df.columns:
                    fig_pie = px.pie(df, names='emotions', hole=0.5, title="Настроение клиентов",
                                     color='emotions', 
                                     color_discrete_map={'POSITIVE':'#2ecc71', 'NEGATIVE':'#e74c3c', 'NEUTRAL':'#95a5a6'})
                else:
                    fig_pie = px.pie(df, names='rating', hole=0.5, title="Распределение оценок")
                
                fig_pie.update_layout(margin=dict(t=40, b=0, l=0, r=0))
                st.plotly_chart(fig_pie, use_container_width=True)
            
            with col_chart2:
                df['date_only'] = df['date'].dt.date
                trend = df.groupby('date_only')['rating'].agg(['mean']).reset_index()
                trend['mean_smooth'] = trend['mean'].rolling(window=7, min_periods=1).mean()

                fig_trend = go.Figure()
                fig_trend.add_trace(go.Scatter(x=trend['date_only'], y=trend['mean'], mode='lines', 
                                              name='Дневной', opacity=0.3, line=dict(color='#95a5a6', width=1)))
                fig_trend.add_trace(go.Scatter(x=trend['date_only'], y=trend['mean_smooth'], mode='lines+markers', 
                                              name='Тренд (7дн.)', line=dict(color='#2ecc71', width=3)))

                fig_trend.update_layout(title="Динамика Rating (Сглажено)", yaxis_range=[1, 5], margin=dict(t=40, b=0, l=0, r=0))
                st.plotly_chart(fig_trend, use_container_width=True)

            # --- БЛОК 3: AI АНАЛИЗ С УМНЫМ ЛИМИТОМ КОНТЕКСТА ---
            st.divider()
            st.subheader("🚀 Стратегический отчет AI")
            
            ai_df = df[df['text'].notna() & (df['text'].str.strip() != '')].copy()
            reviews_list = [f"[{r['date'].strftime('%Y-%m-%d')}] Адрес: {r['location_address']} | Оценка: {r['rating']} | Текст: {r['text']}" for _, r in ai_df.iterrows()]
            full_context = "\n".join(reviews_list)
            
            # Лимит 60 000 символов для защиты от ошибки GPT (128k tokens)
            if len(full_context) > 60000:
                full_context = full_context[:60000] + "\n...[ОБРЕЗАНО ИЗ-ЗА ЛИМИТОВ]"
            
            report_prompt = """Ты CPO Qlean. 
            1. Выдели ТОП-3 системных проблемы с УКАЗАНИЕМ АДРЕСОВ. 
            2. Найди 'тихие риски' (оценка высокая, но есть жалобы).
            3. Дай 3 жестких совета по операционке. Используй таблицы и списки."""
            
            with st.spinner("AI анализирует массив..."):
                st.info(ask_ai(report_prompt, f"ДАННЫЕ: {full_context}"))

            # --- БЛОК 4: КАРТА НАСТРОЕНИЙ (HOTSPOTS) ---
            st.divider()
            st.subheader("🗺️ Карта настроений (Hotspots)")
            
            map_data = df.groupby('location_address').agg({'rating': 'mean', 'id': 'count'}).reset_index()
            unique_addresses = map_data['location_address'].tolist()
            
            lats, lons = [], []
            
            progress_text = "📍 Геокодирование адресов (защита от блокировки)..."
            my_bar = st.progress(0, text=progress_text)
            
            for i, addr in enumerate(unique_addresses):
                lat, lon = get_coords(addr)
                lats.append(lat)
                lons.append(lon)
                time.sleep(0.6) 
                my_bar.progress((i + 1) / len(unique_addresses), text=f"Обработка: {addr[:30]}...")
                
            my_bar.empty() 
            
            map_data['lat'] = lats
            map_data['lon'] = lons
            map_data = map_data.dropna(subset=['lat', 'lon'])

            def get_color(r):
                if r <= 2.5: return [255, 0, 0, 160] # Красный
                if r >= 4.0: return [46, 204, 113, 160] # Зеленый
                return [241, 196, 15, 160] # Желтый
            
            map_data['color'] = map_data['rating'].apply(get_color)

            if not map_data.empty:
                st.pydeck_chart(pdk.Deck(
                    map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
                    initial_view_state=pdk.ViewState(latitude=55.75, longitude=37.62, zoom=10, pitch=45),
                    layers=[
                        pdk.Layer(
                            'ScatterplotLayer',
                            data=map_data,
                            get_position='[lon, lat]',
                            get_color='color',
                            get_radius='id * 50', 
                            pickable=True,
                        ),
                    ],
                    tooltip={"text": "{location_address}\nРейтинг: {rating:.1f}\nОтзывов: {id}"}
                ))
                st.caption("🔴 - Критично, 🟡 - Средне, 🟢 - Хорошо. Размер точки = объем отзывов.")
            else:
                st.warning("Не удалось распознать координаты адресов на карте.")

            # --- БЛОК 5: ОНЛАЙН-ЧАТ ---
            st.divider()
            st.subheader("💬 Чат с AI-аналитиком")
            if "messages" not in st.session_state: st.session_state.messages = []
            
            for msg in st.session_state.messages:
                with st.chat_message(msg["role"]): st.markdown(msg["content"])

            if user_q := st.chat_input("Спроси про конкретную точку..."):
                st.session_state.messages.append({"role": "user", "content": user_q})
                with st.chat_message("user"): st.markdown(user_q)
                
                with st.chat_message("assistant"):
                    with st.spinner("Ищу в данных..."):
                        chat_context = f"Ты эксперт Qlean. Отвечай на основе этих данных: {full_context}. Вопрос: {user_q}"
                        ans = ask_ai("Отвечай кратко и по фактам из данных.", chat_context)
                        st.markdown(ans)
                st.session_state.messages.append({"role": "assistant", "content": ans})

            # --- БЛОК 6: СЫРЫЕ ДАННЫЕ ---
            st.divider()
            with st.expander("📂 Посмотреть все данные за период"):
                st.dataframe(df[['date', 'rating', 'text', 'location_address', 'author_name']], use_container_width=True)
        else:
            st.warning("За выбранные даты данных в Hotmaps не найдено.")