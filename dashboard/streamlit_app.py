"""Smart Facility Digital Twin — dashboard entry point.

Four pages over one cached MQTT connection. Top navigation because the skill's
guidance is top nav for 3–7 pages; the sidebar stays free for page controls.
"""
import streamlit as st

st.set_page_config(page_title="Smart Facility Digital Twin",
                   page_icon=":material/hvac:", layout="wide")

if "selected_room" not in st.session_state:
    st.session_state.selected_room = "f1/lab-a"

page = st.navigation(
    [
        # The room console is the landing page: it mirrors Project 1's layout,
        # which reads as one operator console rather than a report.
        st.Page("app_pages/room_console.py", title="Room console",
                icon=":material/dashboard:", default=True),
        st.Page("app_pages/building_overview.py", title="Building",
                icon=":material/apartment:"),
        st.Page("app_pages/predictive_maintenance.py", title="Maintenance",
                icon=":material/build:"),
        st.Page("app_pages/ecosystem.py", title="Ecosystem",
                icon=":material/hub:"),
    ],
    position="top",
)

page.run()
