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
geolocator = Nominatim(user_agent="qlean_cpo_dashboard_v6")
st.set_page_config(page_title="Qlean CX Center", layout="wide", page_icon="📈")
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
        "hasText": True, "limit": 400, "sortBy": "date", "orderBy": "desc"
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
        "temperature": 0.2 # Делаем AI максимально точным и фактологическим
    }
    try:
        r = requests.post("https://routerai.ru/api/v1/chat/completions", json=payload, headers=headers, timeout=60)
        response_data = r.json()
        if 'choices' in response_data:
            return response_data['choices'][0]['message']['content']
        else:
            return f"⛔ Ошибка RouterAI: {response_data}"
    except Exception as e:
        return f"🔌 Ошибка связи с API: {e}"

@st.cache_data(ttl=86400)
def get_coords(address):
    try:
        clean = address.replace("Russia, Moskva, ", "").replace("Москва, ", "")
        loc = geolocator.geocode(f"Москва, {clean}", timeout=10)
        return (loc.latitude, loc.longitude) if loc else (None, None)
    except: return None, None

# --- ГЛАВНЫЙ ЭКРАН ---
if check_password():
    st.markdown("<h1 style='text-align: center; color: #3498db;'>📈 Qlean: Управление качеством (Химчистка)</h1>", unsafe_allow_html=True)
    
    with st.sidebar:
        st.header("🎛 Фильтры данных")
        today = datetime.now()
        start = st.date_input("Дата начала", today - timedelta(days=30))
        end = st.date_input("Дата конца", today)
        btn = st.button("🚀 Сформировать отчет", use_container_width=True)

    # 1. Запоминаем нажатие кнопки для работы чата
    if btn:
        st.session_state["report_ready"] = True

    # 2. Если отчет еще не запускали - ждем
    if not st.session_state.get("report_ready", False):
        st.info("👈 Выберите период и нажмите 'Сформировать отчет' для старта.")
        st.stop()

    # 3. Синхронизируем данные и СОЗДАЕМ df (то, что я случайно удалил)
    with st.spinner("Синхронизация с базой Hotmaps..."):
        data = fetch_data(start, end)
        df = pd.DataFrame(data)
        if not df.empty:
            df['date'] = pd.to_datetime(df['date'])
            # Фильтруем нужные группы
            df = df[(df['location_group'] == 'химчистка') | ((df['location_group'] == 'otzovik') & (df['store_code'] == 'otzovik_dry_cleaning'))]

    # 4. Проверяем, не пустая ли таблица после фильтров
    if df.empty:
        st.warning("За выбранные даты данных в Hotmaps не найдено.")
        st.stop()

    with st.spinner("Синхронизация с базой Hotmaps..."):
        # Если мы тут, значит отчет либо только что запросили, либо он уже висит в кэше
        data = fetch_data(start, end)

    if df.empty:
        st.warning("За выбранные даты данных в Hotmaps не найдено.")
        st.stop()

    # --- ПОДГОТОВКА КОНТЕКСТА ДЛЯ AI ---
    ai_df = df[df['text'].notna() & (df['text'].str.strip() != '')].copy()
    reviews_list = [f"[{r['date'].strftime('%d.%m')}] Адрес: {r['location_address']} | Оценка: {r['rating']} | Отзыв: {r['text']}" for _, r in ai_df.iterrows()]
    full_context = "\n".join(reviews_list)
    if len(full_context) > 70000:
        full_context = full_context[:70000] + "\n...[СЛИШКОМ МНОГО ДАННЫХ, ВЗЯТЫ ПОСЛЕДНИЕ]"

    # --- МЕТРИКИ (ОБЩИЕ ДЛЯ ВСЕХ ВКЛАДОК) ---
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Всего отзывов", len(df))
    m2.metric("NPS (Средний рейтинг)", f"{df['rating'].mean():.2f} ⭐")
    m3.metric("Позитив (4-5 ⭐)", len(df[df['rating'] >= 4]))
    m4.metric("Критика (1-2 ⭐)", len(df[df['rating'] <= 2]))
    st.divider()

    # --- ПРОФЕССИОНАЛЬНАЯ СТРУКТУРА: ВКЛАДКИ ---
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Аналитика и Графики", "🤖 AI-Отчет & Чат", "🗺️ Карта Hotspots", "📂 Сырые данные"])

    # --- ВКЛАДКА 1: АНАЛИТИКА ---
    with tab1:
        col_chart1, col_chart2 = st.columns([1, 2])
        
        with col_chart1:
            st.subheader("Климат настроений")
            if 'emotions' in df.columns:
                fig_pie = px.pie(df, names='emotions', hole=0.4, 
                                 color='emotions', 
                                 color_discrete_map={'POSITIVE':'#2ecc71', 'NEGATIVE':'#e74c3c', 'NEUTRAL':'#95a5a6'})
            else:
                fig_pie = px.pie(df, names='rating', hole=0.4)
            fig_pie.update_layout(margin=dict(t=20, b=20, l=0, r=0), showlegend=True)
            st.plotly_chart(fig_pie, use_container_width=True)
        
        with col_chart2:
            st.subheader("Динамика и Объем оценок")
            df['date_only'] = df['date'].dt.date
            trend = df.groupby('date_only').agg(mean_rating=('rating', 'mean'), count_reviews=('id', 'count')).reset_index()
            trend['smooth_rating'] = trend['mean_rating'].rolling(window=3, min_periods=1).mean() # Сглаживание

            fig_trend = go.Figure()
            # Столбики - объем отзывов (Ось Y2 справа)
            fig_trend.add_trace(go.Bar(x=trend['date_only'], y=trend['count_reviews'], name='Кол-во отзывов', marker_color='#34495e', opacity=0.7, yaxis='y2'))
            # Линия - сглаженный рейтинг (Ось Y1 слева)
            fig_trend.add_trace(go.Scatter(x=trend['date_only'], y=trend['smooth_rating'], mode='lines+markers', name='Тренд рейтинга', line=dict(color='#2ecc71', width=4)))

            fig_trend.update_layout(
                yaxis=dict(title="Средний рейтинг", range=[1, 5.2]),
                yaxis2=dict(title="Объем (шт)", overlaying='y', side='right', showgrid=False),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(t=20, b=20, l=0, r=0)
            )
            st.plotly_chart(fig_trend, use_container_width=True)

    # --- ВКЛАДКА 2: AI И ЧАТ ---
    with tab2:
        col_ai_report, col_ai_chat = st.columns([1.2, 1])
        
        with col_ai_report:
            st.subheader("🚀 Стратегический аудит сети")
            report_prompt = """Ты — Chief Product Officer и Head of CX. Твоя задача провести жесткий операционный аудит массива отзывов по химчистке.
            ПРАВИЛА:
            1. Опиши общую картину и тренды качества.
            2. Выяви ВСЕ системные сбои (качество стирки, логистика, саппорт). Не ограничивайся 3 пунктами, покажи реальный масштаб проблем.
            3. Если есть локации/адреса с аномально высоким негативом — ОБЯЗАТЕЛЬНО назови их и опиши, что там происходит.
            4. Найди неочевидные вещи (например, высокие оценки, но с жалобами внутри текста).
            5. Оформляй отчет профессионально: используй markdown-таблицы для проблемных зон, списки и жирный шрифт для ключевых метрик. Без лишней воды."""
            
            with st.spinner("AI проводит глубокий аудит данных..."):
                report_result = ask_ai(report_prompt, f"МАССИВ ОТЗЫВОВ:\n{full_context}")
                st.markdown(report_result)

        with col_ai_chat:
            st.subheader("💬 Оперативный чат по данным")
            st.caption("Спроси ИИ о конкретных курьерах, адресах или жалобах из базы.")
            
            # Чат внутри вкладки
            if "messages" not in st.session_state: 
                st.session_state.messages = [{"role": "assistant", "content": "Привет! Я проанализировал данные. Какой срез тебя интересует?"}]
            
            # Контейнер для истории, чтобы она скроллилась
            chat_container = st.container(height=500)
            with chat_container:
                for msg in st.session_state.messages:
                    with st.chat_message(msg["role"]): st.markdown(msg["content"])

            if user_q := st.chat_input("Например: Что пишут про точку на Базовской?"):
                st.session_state.messages.append({"role": "user", "content": user_q})
                with chat_container:
                    with st.chat_message("user"): st.markdown(user_q)
                    with st.chat_message("assistant"):
                        with st.spinner("Анализирую базу..."):
                            chat_sys_prompt = "Ты Data-ассистент PM-а Qlean. Отвечай на вопросы ТОЛЬКО опираясь на переданный массив данных. Будь краток и точен."
                            ans = ask_ai(chat_sys_prompt, f"МАССИВ ДАННЫХ: {full_context}\n\nВОПРОС: {user_q}")
                            st.markdown(ans)
                    st.session_state.messages.append({"role": "assistant", "content": ans})

    # --- ВКЛАДКА 3: КАРТА ---
    with tab3:
        st.subheader("🗺️ Гео-аналитика и Индикаторы качества")
        st.caption("🔴 - Критичный уровень жалоб | 🟡 - Средний NPS | 🟢 - Отличный сервис. Размер точки зависит от объема оценок.")
        
        map_data = df.groupby('location_address').agg(avg_rating=('rating', 'mean'), count_rev=('id', 'count')).reset_index()
        unique_addresses = map_data['location_address'].tolist()
        
        lats, lons = [], []
        my_bar = st.progress(0, text="📍 Подготовка карты (геокодирование)...")
        
        for i, addr in enumerate(unique_addresses):
            lat, lon = get_coords(addr)
            lats.append(lat)
            lons.append(lon)
            time.sleep(0.3) # Уменьшили паузу для скорости
            my_bar.progress((i + 1) / len(unique_addresses), text=f"Поиск координат: {addr[:25]}...")
            
        my_bar.empty() 
        map_data['lat'] = lats
        map_data['lon'] = lons
        map_data = map_data.dropna(subset=['lat', 'lon'])

        def get_color(r):
            if r < 3.5: return [231, 76, 60, 180] # Красный (теперь всё что ниже 3.5 - тревога)
            if r >= 4.5: return [46, 204, 113, 180] # Зеленый
            return [241, 196, 15, 180] # Желтый
        
        map_data['color'] = map_data['avg_rating'].apply(get_color)

        if not map_data.empty:
            st.pydeck_chart(pdk.Deck(
                map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
                initial_view_state=pdk.ViewState(latitude=55.75, longitude=37.62, zoom=10, pitch=40),
                layers=[
                    pdk.Layer(
                        'ScatterplotLayer',
                        data=map_data,
                        get_position='[lon, lat]',
                        get_color='color',
                        get_radius='count_rev * 60 + 150', # Базовый радиус + рост от количества
                        pickable=True,
                    ),
                ],
                tooltip={"html": "<b>{location_address}</b><br/>Средний рейтинг: <b>{avg_rating:.1f}</b><br/>Кол-во отзывов: <b>{count_rev}</b>"}
            ))
        else:
            st.warning("Не удалось распознать адреса.")

    # --- ВКЛАДКА 4: СЫРЫЕ ДАННЫЕ ---
    with tab4:
        st.subheader("📂 Журнал отзывов")
        st.dataframe(df[['date', 'rating', 'emotions', 'text', 'location_address', 'author_name', 'store_code']], use_container_width=True, height=600)