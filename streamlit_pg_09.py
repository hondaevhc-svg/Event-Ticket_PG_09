
import streamlit as st
import pandas as pd
from sqlalchemy import create_engine

# -------------------------------------------------
# BASIC CONFIG
# -------------------------------------------------
st.set_page_config(page_title="🎟️ Event Management System", layout="wide")

# CSS for center alignment
st.markdown("""
    <style>
    [data-testid="stTable"] td, [data-testid="stTable"] th {
        text-align: center !important;
    }
    div[data-testid="stDataFrame"] div[class^="st-"] {
        text-align: center !important;
    }
    .stDataFrame th {
        text-align: center !important;
    }
    </style>
""", unsafe_allow_html=True)

# -------------------------------------------------
# SESSION STATE
# -------------------------------------------------
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "📊 Dashboard"

# -------------------------------------------------
# DB CONNECTION & CACHED LOAD
# -------------------------------------------------
@st.cache_resource
def get_engine():
    db_url = st.secrets["connections"]["postgresql"]["url"]
    return create_engine(db_url)

@st.cache_data(ttl=60)
def load_all_data():
    engine = get_engine()
    tickets_df = pd.read_sql("SELECT * FROM tickets", engine)
    menu_df = pd.read_sql("SELECT * FROM menu", engine)

    # Data cleaning
    tickets_df["Visitor_Seats"] = tickets_df["Visitor_Seats"].fillna(0)
    tickets_df["Sold"] = tickets_df["Sold"].fillna(False).astype(bool)
    tickets_df["Visited"] = tickets_df["Visited"].fillna(False).astype(bool)
    tickets_df["Customer"] = tickets_df["Customer"].fillna("")
    tickets_df["Admit"] = pd.to_numeric(tickets_df["Admit"], errors="coerce").fillna(1)
    tickets_df["Seq"] = pd.to_numeric(tickets_df["Seq"], errors="coerce")
    tickets_df["TicketID"] = tickets_df["TicketID"].astype(str).str.zfill(4)

    return tickets_df, menu_df

tickets, menu = load_all_data()

def save_tickets_df(tickets_df):
    engine = get_engine()
    tickets_df.to_sql("tickets", engine, if_exists="replace", index=False)
    st.cache_data.clear()

def save_menu_df(menu_df):
    engine = get_engine()
    menu_df.to_sql("menu", engine, if_exists="replace", index=False)
    st.cache_data.clear()

def custom_sort(df: pd.DataFrame) -> pd.DataFrame:
    if "Seq" not in df.columns:
        return df
    return df.sort_values(by="Seq", na_position="last")

# -------------------------------------------------
# SIDEBAR
# -------------------------------------------------
with st.sidebar:
    st.header("Admin Settings")

    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.experimental_rerun()

    admin_pass_input = st.text_input("Reset Database Password", type="password")

    if st.button("🚨 Reset Database", use_container_width=True):
        if admin_pass_input == "admin123":
            tickets.update({
                "Sold": False,
                "Visited": False,
                "Customer": "",
                "Visitor_Seats": 0,
                "Timestamp": None
            })
            save_tickets_df(tickets)
            st.success("Database has been reset.")
        else:
            st.error("Incorrect Admin Password")

# -------------------------------------------------
# TABS
# -------------------------------------------------
tab_labels = ["📊 Dashboard", "💰 Sales", "🚶 Visitors", "⚙️ Edit Menu"]
tabs = st.tabs(tab_labels)

# -------------------------------------------------
# DASHBOARD
# -------------------------------------------------
with tabs[0]:
    st.subheader("Inventory & Visitor Analytics")
    df = tickets.copy()

    summary = (
        df.groupby(["Seq", "Type", "Category", "Admit"])
        .agg(
            Total_Tickets=("TicketID", "count"),
            Tickets_Sold=("Sold", "sum"),
            Total_Visitors=("Visitor_Seats", "sum"),
        )
        .reset_index()
    )

    summary["Total_Seats"] = summary["Total_Tickets"] * summary["Admit"]
    summary["Seats_sold"] = summary["Tickets_Sold"] * summary["Admit"]
    summary["Balance_Tickets"] = summary["Total_Tickets"] - summary["Tickets_Sold"]
    summary["Balance_Seats"] = summary["Total_Seats"] - summary["Seats_sold"]
    summary["Balance_Visitors"] = summary["Seats_sold"] - summary["Total_Visitors"]

    summary = custom_sort(summary)
    totals = pd.DataFrame([summary.select_dtypes(include="number").sum()])
    totals["Seq"] = "Total"
    summary_final = pd.concat([summary, totals], ignore_index=True)

    st.dataframe(summary_final, hide_index=True, use_container_width=True, height=450)

# -------------------------------------------------
# SALES
# -------------------------------------------------
with tabs[1]:
    st.subheader("Sales Management")
    col_in, col_out = st.columns([1, 1.2])

    with col_in:
        sale_tab = st.radio("Action", ["Manual", "Bulk Upload", "Reverse Sale"], horizontal=True)

        if sale_tab == "Manual":
            s_type = st.radio("Type", ["Public", "Guest"], horizontal=True)
            s_cat = st.selectbox("Category", menu[menu["Type"] == s_type]["Category"])
            avail = tickets[(tickets["Type"] == s_type) & (tickets["Category"] == s_cat) & (~tickets["Sold"])]["TicketID"].tolist()

            if avail:
                with st.form("sale_form"):
                    tid = st.selectbox("Ticket ID", avail)
                    cust = st.text_input("Customer Name")
                    if st.form_submit_button("Confirm Sale"):
                        idx = tickets.index[tickets["TicketID"] == tid][0]
                        tickets.at[idx, "Sold"] = True
                        tickets.at[idx, "Customer"] = cust
                        tickets.at[idx, "Timestamp"] = str(pd.Timestamp.now())
                        save_tickets_df(tickets)
                        st.success(f"Ticket {tid} sold to {cust}.")
            else:
                st.info("No available tickets in this category.")

        elif sale_tab == "Bulk Upload":
            st.info("Upload Excel/CSV with columns: Ticket_ID, Customer")
            uploaded_file = st.file_uploader("Choose file", type=["csv", "xlsx"])
            if uploaded_file:
                bulk_df = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
                st.dataframe(bulk_df.head())
                if st.button("Process Bulk Sale"):
                    for _, row in bulk_df.iterrows():
                        tid = str(row['Ticket_ID']).zfill(4)
                        cust = str(row['Customer']).strip()
                        idx = tickets.index[tickets["TicketID"] == tid]
                        if not idx.empty and not tickets.at[idx[0], "Sold"]:
                            tickets.at[idx[0], "Sold"] = True
                            tickets.at[idx[0], "Customer"] = cust
                            tickets.at[idx[0], "Timestamp"] = str(pd.Timestamp.now())
                    save_tickets_df(tickets)
                    st.success("Bulk sale processed.")

        elif sale_tab == "Reverse Sale":
            r_type = st.radio("Type", ["Public", "Guest"], horizontal=True)
            r_cat = st.selectbox("Category", menu[menu["Type"] == r_type]["Category"])
            sold_tickets = tickets[(tickets["Type"] == r_type) & (tickets["Category"] == r_cat) & (tickets["Sold"])]["TicketID"].tolist()
            if sold_tickets:
                with st.form("reverse_sale_form"):
                    tid = st.selectbox("Ticket ID to reverse", sold_tickets)
                    if st.form_submit_button("Reverse Sale"):
                        idx = tickets.index[tickets["TicketID"] == tid][0]
                        tickets.at[idx, ["Sold", "Customer", "Visited", "Visitor_Seats", "Timestamp"]] = [False, "", False, 0, None]
                        save_tickets_df(tickets)
                        st.success(f"Sale reversed for Ticket {tid}.")
            else:
                st.info("No sold tickets to reverse.")

    with col_out:
        st.write("Recent Sales History")
        recent_sales = tickets[tickets["Sold"]].sort_values("Timestamp", ascending=False)
        if not recent_sales.empty:
            recent_sales.insert(0, "Sno", range(1, len(recent_sales) + 1))
            st.dataframe(recent_sales[["Sno", "TicketID", "Category", "Customer", "Timestamp"]], hide_index=True)
        else:
            st.info("No sales recorded yet.")

# -------------------------------------------------
# VISITORS & MENU remain similar but optimized similarly
