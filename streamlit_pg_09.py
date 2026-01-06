import streamlit as st
import pandas as pd
from sqlalchemy import create_engine

# -------------------------------------------------
# BASIC CONFIG
# -------------------------------------------------
st.set_page_config(page_title="🎟️ Event Management System", layout="wide")

# --- CSS: center align table content ---
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
if "admin_pass_key" not in st.session_state:
    st.session_state.admin_pass_key = 0
if "menu_pass_key" not in st.session_state:
    st.session_state.menu_pass_key = 0
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "📊 Dashboard"

def rerun_on_tab(tab_label: str):
    """Helper to rerun while keeping a specific tab active."""
    st.session_state.active_tab = tab_label
    st.rerun()

# -------------------------------------------------
# DB CONNECTION & CACHED LOAD
# -------------------------------------------------
def get_engine():
    db_url = st.secrets["connections"]["postgresql"]["url"]
    return create_engine(db_url)

@st.cache_data(ttl=60)
def load_all_data():
    engine = get_engine()
    tickets_df = pd.read_sql("SELECT * FROM tickets", engine)
    menu_df = pd.read_sql("SELECT * FROM menu", engine)

    tickets_df["Visitor_Seats"] = tickets_df["Visitor_Seats"].fillna(0)
    tickets_df["Sold"] = tickets_df["Sold"].fillna(False).astype(bool)
    tickets_df["Visited"] = tickets_df["Visited"].fillna(False).astype(bool)
    tickets_df["Customer"] = tickets_df["Customer"].fillna("")
    tickets_df["Admit"] = pd.to_numeric(tickets_df["Admit"], errors="coerce").fillna(1)
    tickets_df["Seq"] = pd.to_numeric(tickets_df["Seq"], errors="coerce")
    tickets_df["TicketID"] = tickets_df["TicketID"].astype(str).str.zfill(4)

    return tickets_df, menu_df

def save_tickets_df(tickets_df):
    engine = get_engine()
    tickets_df.to_sql("tickets", engine, if_exists="replace", index=False)
    st.cache_data.clear()

def save_menu_df(menu_df):
    engine = get_engine()
    menu_df.to_sql("menu", engine, if_exists="replace", index=False)
    st.cache_data.clear()

def save_both(tickets_df, menu_df):
    engine = get_engine()
    tickets_df.to_sql("tickets", engine, if_exists="replace", index=False)
    menu_df.to_sql("menu", engine, if_exists="replace", index=False)
    st.cache_data.clear()

def custom_sort(df: pd.DataFrame) -> pd.DataFrame:
    if "Seq" not in df.columns:
        return df
    return (
        df.assign(
            sort_key=df["Seq"].apply(
                lambda x: 10 if x in [0, "0", None] else int(x)
            )
        )
        .sort_values("sort_key")
        .drop(columns="sort_key")
    )

tickets, menu = load_all_data()

# -------------------------------------------------
# SIDEBAR
# -------------------------------------------------
with st.sidebar:
    st.header("Admin Settings")

    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    # Dynamic key for admin password to allow clearing
    admin_pass_input = st.text_input(
        "Reset Database Password",
        type="password",
        key=f"admin_pass_{st.session_state.admin_pass_key}",
    )

    if st.button("🚨 Reset Database", use_container_width=True):
        if admin_pass_input == "admin123":
            tickets["Sold"] = False
            tickets["Visited"] = False
            tickets["Customer"] = ""
            tickets["Visitor_Seats"] = 0
            tickets["Timestamp"] = None
            save_tickets_df(tickets)
            st.session_state.admin_pass_key += 1  # Clear password field
            st.success("Database has been reset.")
            rerun_on_tab("📊 Dashboard")
        else:
            st.error("Incorrect Admin Password")

# -------------------------------------------------
# TABS
# -------------------------------------------------
tab_labels = ["📊 Dashboard", "💰 Sales", "🚶 Visitors", "⚙️ Edit Menu"]

try:
    init_index = tab_labels.index(st.session_state.active_tab)
except ValueError:
    init_index = 0

tabs = st.tabs(tab_labels)

# -------------------------------------------------
# 1. DASHBOARD
# -------------------------------------------------
with tabs[0]:
    if st.session_state.active_tab != tab_labels[0]:
        st.session_state.active_tab = tab_labels[0]

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

    column_order = [
        "Seq",
        "Type",
        "Category",
        "Admit",
        "Total_Tickets",
        "Tickets_Sold",
        "Total_Seats",
        "Seats_sold",
        "Total_Visitors",
        "Balance_Tickets",
        "Balance_Seats",
        "Balance_Visitors",
    ]

    summary = custom_sort(summary[column_order])
    totals = pd.DataFrame([summary.select_dtypes(include="number").sum()])
    totals["Seq"] = "Total"
    summary_final = pd.concat([summary, totals], ignore_index=True).dropna(how="all")

    st.dataframe(
        summary_final,
        hide_index=True,
        use_container_width=True,
        height=450,
    )

# -------------------------------------------------
# 2. SALES
# -------------------------------------------------
with tabs[1]:
    if st.session_state.active_tab != tab_labels[1]:
        st.session_state.active_tab = tab_labels[1]

    st.subheader("Sales Management")
    col_in, col_out = st.columns([1, 1.2])

    with col_in:
        sale_tab = st.radio(
            "Action",
            ["Manual", "Bulk Upload", "Reverse Sale"],
            horizontal=True,
            key="sale_action",
        )

        if sale_tab == "Manual":
            s_type = st.radio("Type", ["Public", "Guest"], horizontal=True, key="sale_type")
            s_cat = st.selectbox(
                "Category",
                menu[menu["Type"] == s_type]["Category"],
                key="sale_cat",
            )

            avail = tickets[
                (tickets["Type"] == s_type)
                & (tickets["Category"] == s_cat)
                & (~tickets["Sold"])
            ]["TicketID"].tolist()

            if avail:
                with st.form("sale_form", clear_on_submit=True):
                    tid = st.selectbox("Ticket ID", avail)
                    cust = st.text_input("Customer Name")
                    confirm = st.form_submit_button("Confirm Sale")

                    if confirm:
                        idx = tickets.index[tickets["TicketID"] == tid][0]
                        tickets.at[idx, "Sold"] = True
                        tickets.at[idx, "Customer"] = cust
                        tickets.at[idx, "Timestamp"] = str(pd.Timestamp.now())
                        save_tickets_df(tickets)
                        st.success(f"Ticket {tid} sold to {cust}.")
                        rerun_on_tab("💰 Sales")
            else:
                st.info("No available tickets in this category.")

        elif sale_tab == "Reverse Sale":
            r_type = st.radio("Type", ["Public", "Guest"], horizontal=True, key="rs_type")
            r_cat = st.selectbox(
                "Category",
                menu[menu["Type"] == r_type]["Category"],
                key="rs_cat",
            )

            sold_tickets = tickets[
                (tickets["Type"] == r_type)
                & (tickets["Category"] == r_cat)
                & (tickets["Sold"])
            ]["TicketID"].tolist()

            if sold_tickets:
                with st.form("reverse_sale_form"):
                    tid = st.selectbox("Ticket ID to reverse", sold_tickets)
                    confirm = st.form_submit_button("Reverse Sale")

                    if confirm:
                        idx = tickets.index[tickets["TicketID"] == tid][0]
                        tickets.at[idx, "Sold"] = False
                        tickets.at[idx, "Customer"] = ""
                        tickets.at[idx, "Visited"] = False
                        tickets.at[idx, "Visitor_Seats"] = 0
                        tickets.at[idx, "Timestamp"] = None
                        save_tickets_df(tickets)
                        st.success(f"Sale reversed for Ticket {tid}.")
                        rerun_on_tab("💰 Sales")
            else:
                st.info("No sold tickets to reverse in this category.")

        else:
            st.info("Bulk Upload not implemented yet.")

    with col_out:
        st.write("**Recent Sales History**")
        recent_sales = tickets[tickets["Sold"]].sort_values(
            "Timestamp", ascending=False
        ).copy()

        if not recent_sales.empty:
            recent_sales.insert(0, "Sno", range(1, len(recent_sales) + 1))
            st.dataframe(
                recent_sales[["Sno", "TicketID", "Category", "Customer", "Timestamp"]],
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info("No sales recorded yet.")

# -------------------------------------------------
# 3. VISITORS
# -------------------------------------------------
with tabs[2]:
    if st.session_state.active_tab != tab_labels[2]:
        st.session_state.active_tab = tab_labels[2]

    st.subheader("Visitor Entry Management")
    v_in, v_out = st.columns([1, 1.2])

    with v_in:
        v_action = st.radio("Action", ["Entry", "Reverse Entry"], horizontal=True, key="v_action")

        if v_action == "Entry":
            v_type = st.radio(
                "Entry Type",
                ["Public", "Guest"],
                horizontal=True,
                key="v_type",
            )
            v_cat = st.selectbox(
                "Entry Category",
                menu[menu["Type"] == v_type]["Category"],
                key="v_cat",
            )

            elig = tickets[
                (tickets["Type"] == v_type)
                & (tickets["Category"] == v_cat)
                & (tickets["Sold"])
                & (~tickets["Visited"])
            ]["TicketID"].tolist()

            if elig:
                with st.form("checkin"):
                    tid = st.selectbox("Select Ticket ID", elig)
                    max_v = int(
                        tickets[tickets["TicketID"] == tid]["Admit"].values[0]
                    )
                    v_count = st.number_input(
                        "Confirmed Visitors",
                        min_value=1,
                        max_value=max_v,
                        value=max_v,
                    )
                    confirm = st.form_submit_button("Confirm Entry")

                    if confirm:
                        idx = tickets.index[tickets["TicketID"] == tid][0]
                        tickets.at[idx, "Visited"] = True
                        tickets.at[idx, "Visitor_Seats"] = v_count
                        tickets.at[idx, "Timestamp"] = str(pd.Timestamp.now())
                        save_tickets_df(tickets)
                        st.success(f"Entry confirmed for Ticket {tid}.")
                        rerun_on_tab("🚶 Visitors")
            else:
                st.info("No eligible tickets for entry.")

        else:  # Reverse Entry
            rv_type = st.radio(
                "Entry Type",
                ["Public", "Guest"],
                horizontal=True,
                key="rv_type",
            )
            rv_cat = st.selectbox(
                "Entry Category",
                menu[menu["Type"] == rv_type]["Category"],
                key="rv_cat",
            )

            visited_tickets = tickets[
                (tickets["Type"] == rv_type)
                & (tickets["Category"] == rv_cat)
                & (tickets["Visited"])
            ]["TicketID"].tolist()

            if visited_tickets:
                with st.form("reverse_entry"):
                    tid = st.selectbox("Ticket ID to modify", visited_tickets)

                    editable_cats = {"FAMILY SILVER", "FAMILY BRONZE"}
                    allow_edit = str(rv_cat).strip().upper() in editable_cats

                    if allow_edit:
                        max_admit = int(
                            tickets[tickets["TicketID"] == tid]["Admit"].values[0]
                        )
                        current_seats = int(
                            tickets[tickets["TicketID"] == tid]["Visitor_Seats"].values[0]
                        )
                        if current_seats < 1:
                            current_seats = max_admit
                        new_seats = st.number_input(
                            "Confirmed Visitors (can be < Admit)",
                            min_value=0,
                            max_value=max_admit,
                            value=current_seats,
                        )
                        confirm = st.form_submit_button("Update Entry")
                    else:
                        st.info("This category will fully reverse the entry.")
                        confirm = st.form_submit_button("Reverse Entry")

                    if confirm:
                        idx = tickets.index[tickets["TicketID"] == tid][0]

                        if allow_edit:
                            if new_seats == 0:
                                tickets.at[idx, "Visited"] = False
                                tickets.at[idx, "Visitor_Seats"] = 0
                                tickets.at[idx, "Timestamp"] = None
                                st.success(f"Entry removed for Ticket {tid}.")
                            else:
                                tickets.at[idx, "Visited"] = True
                                tickets.at[idx, "Visitor_Seats"] = new_seats
                                tickets.at[idx, "Timestamp"] = str(pd.Timestamp.now())
                                st.success(
                                    f"Entry updated for Ticket {tid} with {new_seats} visitors."
                                )
                        else:
                            tickets.at[idx, "Visited"] = False
                            tickets.at[idx, "Visitor_Seats"] = 0
                            tickets.at[idx, "Timestamp"] = None
                            st.success(f"Entry reversed for Ticket {tid}.")

                        save_tickets_df(tickets)
                        rerun_on_tab("🚶 Visitors")
            else:
                st.info("No visitor entries to reverse.")

    with v_out:
        st.write("**Recent Visitors**")
        recent_visitors = tickets[tickets["Visited"]].sort_values(
            "Timestamp", ascending=False
        ).copy()

        if not recent_visitors.empty:
            recent_visitors.insert(0, "Sno", range(1, len(recent_visitors) + 1))
            st.dataframe(
                recent_visitors[
                    ["Sno", "TicketID", "Category", "Customer", "Visitor_Seats", "Timestamp"]
                ],
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info("No visitors recorded yet.")

# -------------------------------------------------
# 4. EDIT MENU
# -------------------------------------------------
with tabs[3]:
    if st.session_state.active_tab != tab_labels[3]:
        st.session_state.active_tab = tab_labels[3]

    st.subheader("Menu & Series Configuration")
    menu_display = custom_sort(menu.copy())

    edited_menu = st.data_editor(
        menu_display,
        hide_index=True,
        use_container_width=True,
        key="menu_editor",
    )

    for index, row in edited_menu.iterrows():
        try:
            if "-" in str(row["Series"]):
                start, end = map(int, str(row["Series"]).split("-"))
                count = (end - start) + 1
                edited_menu.at[index, "Alloc"] = count
                edited_menu.at[index, "Total_Capacity"] = count * int(row["Admit"])
        except Exception:
            pass

    # Dynamic key for menu password to allow clearing
    menu_pass_input = st.text_input(
        "Enter Menu Update Password",
        type="password",
        key=f"menu_pass_{st.session_state.menu_pass_key}",
    )

    if st.button("Update Database Menu"):
        if menu_pass_input == "admin123":
            new_tickets_list = []
            for _, m_row in edited_menu.iterrows():
                try:
                    start, end = map(int, str(m_row["Series"]).split("-"))
                    for tid in range(start, end + 1):
                        tid_str = str(tid).zfill(4)
                        existing = tickets[tickets["TicketID"] == tid_str]
                        if not existing.empty:
                            new_tickets_list.append(existing.iloc[0].to_dict())
                        else:
                            new_tickets_list.append(
                                {
                                    "TicketID": tid_str,
                                    "Category": m_row["Category"],
                                    "Type": m_row["Type"],
                                    "Admit": m_row["Admit"],
                                    "Seq": m_row["Seq"],
                                    "Sold": False,
                                    "Visited": False,
                                    "Customer": "",
                                    "Visitor_Seats": 0,
                                    "Timestamp": None,
                                }
                            )
                except Exception:
                    continue

            final_tickets_df = pd.DataFrame(new_tickets_list)
            save_both(final_tickets_df, edited_menu)
            st.session_state.menu_pass_key += 1  # Clear password field
            st.success("Menu and Inventory synchronized.")
            rerun_on_tab("⚙️ Edit Menu")
        else:
            st.error("Incorrect Menu Password")
