import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import pydeck as pdk
from datetime import datetime, timedelta
from geopy.geocoders import Nominatim
import time

# --- ИНИЦИАЛИЗАЦИЯ ГЕОКОДЕРА ---
geolocator = Nominatim(user_agent="qlean_analytics_v2")

# --- КОНФИГУРАЦИЯ СТРАНИЦЫ ---
st.set_page_config(page_title="Qlean: Операционный Дашборд v2.0", layout="wide", page_icon="🧵")

# Применяем глобальную темную тему для plotly графиков
px.defaults.template = "plotly_dark"

# --- ФУНКЦИЯ АВТОРИЗАЦИИ ---
def check_password():
    def password_entered():
        if st.session_state["password"] == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.title("🔒 Доступ ограничен")
        st.text_input("Введите пароль доступа", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("Введите пароль доступа", type="password", on_change=password_entered, key="password")
        st.error("😕 Неверный пароль.")
        return False
    return True

# --- ФУНКЦИИ ЗАПРОСОВ ---

@st.cache_data(ttl=3600)
def fetch_hotmaps_data(d_from, d_to):
    """Получение данных из Hotmaps API"""
    headers = {
        "Authorization": st.secrets["HOTMAPS_TOKEN"],
        "Content-Type": "application/json"
    }
    payload = {
        "locationGroupNames": ["химчистка", "otzovik"],
        "dateFrom": str(d_from),
        "dateTo": str(d_to),
        "hasText": True,
        "limit": 200,
        "sortBy": "date",
        "orderBy": "desc"
    }
    try:
        response = requests.post("https://app.hotmaps.pro/external-api/v1/projects/363/reviews", 
                                 json=payload, headers=headers)
        response.raise_for_status()
        return response.json().get('data', [])
    except Exception as e:
        st.error(f"Ошибка Hotmaps API: {e}")
        return []

def get_ai_analysis(reviews_text):
    """Запрос анализа у AI через RouterAI (по твоей документации)"""
    api_key = st.secrets["ROUTER_API_KEY"]
    url = "https://routerai.ru/api/v1/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "openai/gpt-4o", 
        "messages": [
            {
                "role": "system", 
                "content": (
                    "Ты — старший операционный аналитик сервиса Qlean. "
                    "Твоя цель: проанализировать негативные отзывы клиентов по химчистке. "
                    "1. Сгруппируй жалобы по категориям. "
                    "2. Выдели 3 самые критичные точки. "
                    "3. Дай 3 конкретных совета для Product Manager по исправлению ситуации. "
                    "Пиши кратко и в деловом стиле."
                )
            },
            {
                "role": "user", 
                "content": f"Проанализируй следующие отзывы: {reviews_text}"
            }
        ],
        "temperature": 0.7
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json()
        return result['choices'][0]['message']['content']
    except Exception as e:
        return f"🤖 Ошибка AI-анализа: {e}. Проверь баланс и ключ в RouterAI."

@st.cache_data(ttl=86400)
def geocode_address(address):
    """Превращение адреса в координаты"""
    try:
        clean_addr = address.replace("Russia, Moskva, ", "").replace("Москва, ", "")
        location = geolocator.geocode(f"Москва, {clean_addr}", timeout=10)
        if location:
            return location.latitude, location.longitude
    except:
        return None, None
    return None, None

# --- ЗАПУСК ПРИЛОЖЕНИЯ ---

if check_password():
    st.markdown("<h1 style='text-align: center; color: #2ecc71;'>🧵 Qlean: Химчистка / Аналитика</h1>", unsafe_allow_width=True)
    
    with st.sidebar:
        st.header("⚙️ Настройки")
        today = datetime.now()
        start_date = st.date_input("Дата начала", today - timedelta(days=30))
        end_date = st.date_input("Дата конца", today)
        btn_run = st.button("🔄 Обновить дашборд", use_container_width=True)

    if not btn_run:
        st.info("👈 Нажмите 'Обновить дашборд' в меню слева для получения актуальных данных.")
    else:
        with st.spinner("🔍 Загружаем данные из Hotmaps..."):
            raw_data = fetch_hotmaps_data(start_date, end_date)
        
        if raw_data:
            df = pd.DataFrame(raw_data)
            df['date'] = pd.to_datetime(df['date'])
            
            # Фильтрация только химчистки
            df = df[
                (df['location_group'] == 'химчистка') | 
                ((df['location_group'] == 'otzovik') & (df['store_code'] == 'otzovik_dry_cleaning'))
            ]
            
            if df.empty:
                st.warning("В выбранный период по химчистке отзывов нет.")
                st.stop()
            
            # --- AI АНАЛИЗ ---
            st.divider()
            st.subheader("🤖 Стратегический анализ AI Gemini")
            neg_df = df[df['rating'] <= 2].copy()
            all_neg_text = " | ".join(neg_df['text'].dropna().tolist())
            
            if all_neg_text:
                st.info(get_ai_analysis(all_neg_text))
            else:
                st.write("Недостаточно данных для анализа негатива.")
            
            # --- МЕТРИКИ ---
            st.divider()
            avg_rating = df['rating'].mean()
            crit_count = len(neg_df)

            m1, m2, m3, m4 = st.columns([1,1,1,2])
            m1.metric("Всего отзывов", len(df))
            m2.metric("Средний рейтинг", f"{avg_rating:.2f} ⭐")
            m3.metric("Критические жалобы", crit_count)
            
            with m4:
                fig_emotions = px.pie(df, names='emotions', hole=0.5,
                                    color='emotions', 
                                    color_discrete_map={'POSITIVE':'#2ecc71', 'NEGATIVE':'#e74c3c', 'NEUTRAL':'#95a5a6'})
                fig_emotions.update_layout(margin=dict(t=30, b=0, l=0, r=0))
                st.plotly_chart(fig_emotions, use_container_width=True)

            # --- КАРТА + ТРЕНД ---
            st.divider()
            col_map, col_trend = st.columns([2, 2])

            with col_map:
                st.subheader("📍 Карта горячих точек (Москва)")
                if not neg_df.empty:
                    with st.spinner("Геокодируем адреса..."):
                        coords = neg_df['location_address'].apply(geocode_address)
                        neg_df['lat'] = [c[0] for c in coords]
                        neg_df['lon'] = [c[1] for c in coords]
                        map_df = neg_df.dropna(subset=['lat', 'lon'])
                
                    if not map_df.empty:
                        view_state = pdk.ViewState(latitude=55.75, longitude=37.62, zoom=10, pitch=40)
                        
                        layer = pdk.Layer(
                            'ScatterplotLayer',
                            data=map_df,
                            get_position='[lon, lat]',
                            get_color='[255, 30, 0, 200]',
                            get_radius=300,
                            pickable=True,
                        )
                        
                        st.pydeck_chart(pdk.Deck(
                            map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
                            initial_view_state=view_state,
                            layers=[layer],
                            tooltip={"text": "{location_address}\n{text}"}
                        ))
                    else:
                        st.warning("Не удалось определить координаты для карты.")
                else:
                    st.success("Критичных жалоб нет.")

            with col_trend:
                st.subheader("📉 Тренд качества (Rating)")
                df['date_only'] = df['date'].dt.date
                trend = df.groupby('date_only')['rating'].agg(['mean']).reset_index()
                trend['mean_smooth'] = trend['mean'].rolling(window=7, min_periods=1).mean()

                fig_trend = go.Figure()
                fig_trend.add_trace(go.Scatter(x=trend['date_only'], y=trend['mean'], mode='lines', 
                                              name='Дневной', opacity=0.3, line=dict(color='#95a5a6', width=1)))
                fig_trend.add_trace(go.Scatter(x=trend['date_only'], y=trend['mean_smooth'], mode='lines+markers', 
                                              name='Тренд (7дн.)', line=dict(color='#2ecc71', width=3)))

                fig_trend.update_layout(yaxis_range=[1, 5])
                st.plotly_chart(fig_trend, use_container_width=True)

            st.divider()
            with st.expander("Посмотреть сырые данные"):
                st.dataframe(df[['date', 'rating', 'text', 'location_address']].head(20), use_container_width=True)
        else:
            st.warning("За выбранный период данных не найдено.")