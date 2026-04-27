import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import pydeck as pdk
from datetime import datetime, timedelta
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
import time

# --- ИНИЦИАЛИЗАЦИЯ ГЕОКОДЕРА ---
# Используем Nominatim для перевода адресов в координаты (с кэшированием)
geolocator = Nominatim(user_agent="qlean_analytics_dashboard")

# --- КОНФИГУРАЦИЯ СТРАНИЦЫ ---
st.set_page_config(page_title="Qlean Analytics Dashboard", layout="wide", page_icon="🧵")

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
        st.error("😕 Неверный пароль. Попробуйте еще раз.")
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
        "limit": 100,
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
    """Запрос анализа у AI через RouterAAI"""
    headers = {
        "Authorization": f"Bearer {st.secrets['ROUTER_API_KEY']}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "gemini-pro", # Уточни название модели в своем роутере
        "messages": [
            {"role": "system", "content": "Ты эксперт по CX. Проанализируй негативные отзывы химчистки. Выдели 3 главные системные проблемы и дай рекомендации PM-у."},
            {"role": "user", "content": f"Отзывы для анализа: {reviews_text}"}
        ]
    }
    try:
        url = "https://api.routeraai.com/v1/chat/completions" # Уточни URL роутера
        response = requests.post(url, json=payload, headers=headers)
        return response.json()['choices'][0]['message']['content']
    except:
        return "🤖 AI временно недоступен, но графики ниже помогут во всем разобраться."

@st.cache_data(ttl=86400)
def geocode_address(address):
    """Превращение адреса в координаты"""
    try:
        # Очистка адреса для лучшего поиска в Москве
        clean_addr = address.replace("Russia, Moskva, ", "").replace("Москва, ", "")
        location = geolocator.geocode(f"Москва, {clean_addr}", timeout=10)
        if location:
            return location.latitude, location.longitude
    except:
        return None, None
    return None, None

# --- ЗАПУСК ПРИЛОЖЕНИЯ ---

if check_password():
    st.title("🧵 Qlean: Операционный Дашборд Химчистки")
    
    # Сайдбар с фильтрами
    with st.sidebar:
        st.header("Настройки отчета")
        today = datetime.now()
        start_date = st.date_input("Дата начала", today - timedelta(days=14))
        end_date = st.date_input("Дата конца", today)
        btn_run = st.button("Сформировать отчет", use_container_width=True)

    if btn_run:
        with st.spinner("Собираем данные по всей сети..."):
            raw_data = fetch_hotmaps_data(start_date, end_date)
        
        if raw_data:
            df = pd.DataFrame(raw_data)
            
            # ФИЛЬТРАЦИЯ (Оставляем только химчистку, убираем клининг из отзовика)
            df = df[
                (df['location_group'] == 'химчистка') | 
                ((df['location_group'] == 'otzovik') & (df['store_code'] == 'otzovik_dry_cleaning'))
            ]
            
            # ОСНОВНЫЕ МЕТРИКИ
            m1, m2, m3 = st.columns(3)
            m1.metric("Всего отзывов", len(df))
            m2.metric("Средний рейтинг", f"{df['rating'].mean():.2f} ⭐")
            m3.metric("Критические жалобы", len(df[df['rating'] <= 2]))

            # ГРАФИКИ
            col_chart1, col_chart2 = st.columns(2)
            
            with col_chart1:
                fig_emotions = px.pie(df, names='emotions', title="Настроение клиентов",
                                    color='emotions', 
                                    color_discrete_map={'POSITIVE':'#2ecc71', 'NEGATIVE':'#e74c3c', 'NEUTRAL':'#95a5a6'})
                st.plotly_chart(fig_emotions, use_container_width=True)
            
            with col_chart2:
                df['date_only'] = pd.to_datetime(df['date']).dt.date
                trend = df.groupby('date_only')['rating'].mean().reset_index()
                fig_trend = px.line(trend, x='date_only', y='rating', title="Тренд качества (Rating)")
                st.plotly_chart(fig_trend, use_container_width=True)

            # КАРТА ГОРЯЧИХ ТОЧЕК
            st.subheader("📍 Карта проблемных локаций (Москва)")
            neg_df = df[df['rating'] <= 2].copy()
            
            if not neg_df.empty:
                # Геокодируем негатив для карты
                with st.spinner("Наносим жалобы на карту..."):
                    coords = neg_df['location_address'].apply(geocode_address)
                    neg_df['lat'] = [c[0] for c in coords]
                    neg_df['lon'] = [c[1] for c in coords]
                    neg_df = neg_df.dropna(subset=['lat', 'lon'])
                
                st.pydeck_chart(pdk.Deck(
                    map_style='mapbox://styles/mapbox/dark-v9',
                    initial_view_state=pdk.ViewState(latitude=55.75, longitude=37.61, zoom=10, pitch=45),
                    layers=[
                        pdk.Layer(
                            'ScatterplotLayer',
                            data=neg_df,
                            get_position='[lon, lat]',
                            get_color='[231, 76, 60, 160]', # Красный
                            get_radius=250,
                            pickable=True
                        ),
                    ],
                    tooltip={"text": "{location_address}\nОтзыв: {text}"}
                ))
            else:
                st.success("На карте пусто — за этот период критических жалоб с адресами нет!")

            # AI РЕКОМЕНДАЦИИ (GEMINI)
            st.divider()
            st.subheader("🤖 Стратегический анализ AI")
            all_neg_text = " | ".join(neg_df['text'].dropna().tolist())
            if all_neg_text:
                st.info(get_ai_analysis(all_neg_text))
            else:
                st.write("Недостаточно данных для текстового анализа.")

            # ТАБЛИЦА
            with st.expander("Посмотреть все отзывы"):
                st.dataframe(df[['date', 'rating', 'text', 'location_address']])
        else:
            st.warning("За выбранный период данных не найдено.")