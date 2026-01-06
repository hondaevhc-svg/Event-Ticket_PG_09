
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
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "📊 Dashboard"

# -------------------------------------------------
# DB CONNECTION & CACHED LOAD
# -------------------------------------------------
@st.cache_resource
def get_engine():
    db_url = st.secrets["connections"]["postgresql"]["url"]
    return create_engine(db_url, pool_pre_ping=True, pool_recycle=1800)

@st.cache_data(ttl=60, show_spinner=False)
def load_all_data():
    engine = get_engine()
    tickets_df = pd.read_sql("SELECT * FROM tickets", engine)
    menu_df = pd.read_sql("SELECT * FROM menu", engine)

    # Normalize / clean
    tickets_df["Visitor_Seats"] = pd.to_numeric(tickets_df.get("Visitor_Seats"), errors="coerce").fillna(0).astype(int)
    tickets_df["Sold"] = tickets_df.get("Sold", False).fillna(False).astype(bool)
    tickets_df["Visited"] = tickets_df.get("Visited", False).fillna(False).astype(bool)
    tickets_df["Customer"] = tickets_df.get("Customer", "").fillna("").astype(str)
    tickets_df["Admit"] = pd.to_numeric(tickets_df.get("Admit"), errors="coerce").fillna(1).astype(int)
    tickets_df["Seq"] = pd.to_numeric(tickets_df.get("Seq"), errors="coerce")
    tickets_df["TicketID"] = tickets_df.get("TicketID").astype(str).str.zfill(4)
    # Timestamp is stored as string; keep it as-is to avoid timezone issues

    return tickets_df, menu_df

def save_tickets_df(tickets_df: pd.DataFrame):
    """Persist all tickets; optimized write."""
    engine = get_engine()
    with engine.begin() as conn:
        tickets_df.to_sql(
            "tickets", con=conn, if_exists="replace", index=False,
            method="multi", chunksize=1000
        )
    # Clear cache so next reload gets fresh DB; local variable already updated so UI stays fresh.
    st.cache_data.clear()

def save_menu_df(menu_df: pd.DataFrame):
    engine = get_engine()
    with engine.begin() as conn:
        menu_df.to_sql(
            "menu", con=conn, if_exists="replace", index=False,
            method="multi", chunksize=1000
        )
    st.cache_data.clear()

def save_both(tickets_df: pd.DataFrame, menu_df: pd.DataFrame):
    engine = get_engine()
    with engine.begin() as conn:
        tickets_df.to_sql("tickets", con=conn, if_exists="replace", index=False, method="multi", chunksize=1000)
        menu_df.to_sql("menu", con=conn, if_exists="replace", index=False, method="multi", chunksize=1000)
    st.cache_data.clear()

def custom_sort(df: pd.DataFrame) -> pd.DataFrame:
    """Sort by Seq with 0/None last."""
    if "Seq" not in df.columns:
        return df
    sort_key = df["Seq"].apply(lambda x: float("inf") if pd.isna(x) or x in [0, "0"] else float(x))
    return df.assign(_k=sort_key).sort_values("_k").drop(columns="_k")

# Load data once at start; keep references updated after actions to avoid reruns
tickets, menu = load_all_data()

# -------------------------------------------------
# SIDEBAR
# -------------------------------------------------
with st.sidebar:
    st.header("Admin Settings")

    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        # Reload in-memory for immediate UI update after refresh
        tickets, menu = load_all_data()
        st.toast("Data refreshed")

    admin_pass_input = st.text_input("Reset Database Password", type="password", key="admin_pass")

    if st.button("🚨 Reset Database", use_container_width=True):
        if admin_pass_input == "admin123":
            # Reset relevant columns
            tickets.loc[:, ["Sold", "Visited"]] = False
            tickets.loc[:, ["Customer"]] = ""
            tickets.loc[:, ["Visitor_Seats"]] = 0
            tickets.loc[:, ["Timestamp"]] = None
            save_tickets_df(tickets)
            st.success("✅ Database has been reset.")
        else:
            st.error("❌ Incorrect Admin Password")

# -------------------------------------------------
# TABS
# -------------------------------------------------
tab_labels = ["📊 Dashboard", "💰 Sales", "🚶 Visitors", "⚙️ Edit Menu"]
tabs = st.tabs(tab_labels)

# -------------------------------------------------
# 1. DASHBOARD
# -------------------------------------------------
with tabs[0]:
    st.subheader("Inventory & Visitor Analytics")

    df = tickets.copy()

    if df.empty:
        st.info("No tickets found.")
    else:
        summary = (
            df.groupby(["Seq", "Type", "Category", "Admit"], dropna=False)
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
            "Seq", "Type", "Category", "Admit", "Total_Tickets", "Tickets_Sold",
            "Total_Seats", "Seats_sold", "Total_Visitors", "Balance_Tickets",
            "Balance_Seats", "Balance_Visitors"
        ]

        summary = custom_sort(summary[column_order])

        totals = pd.DataFrame([summary.select_dtypes(include="number").sum(numeric_only=True)])
        totals["Seq"] = "Total"
        # Fill non-numeric columns where needed
        totals["Type"] = ""
        totals["Category"] = ""
        summary_final = pd.concat([summary, totals], ignore_index=True)

        st.dataframe(summary_final, hide_index=True, use_container_width=True, height=450)

# -------------------------------------------------
# 2. SALES
# -------------------------------------------------
with tabs[1]:
    st.subheader("Sales Management")
    col_in, col_out = st.columns([1, 1.2])

    with col_in:
        sale_tab = st.radio("Action", ["Manual", "Bulk Upload", "Reverse Sale"], horizontal=True, key="sale_action")

        # ---------- Manual Sale ----------
        if sale_tab == "Manual":
            s_type = st.radio("Type", ["Public", "Guest"], horizontal=True, key="sale_type")
            s_cat_options = menu.loc[menu["Type"] == s_type, "Category"].dropna().unique().tolist()
            s_cat = st.selectbox("Category", s_cat_options, key="sale_cat")

            avail = tickets[(tickets["Type"] == s_type) & (tickets["Category"] == s_cat) & (~tickets["Sold"])]["TicketID"].tolist()

            if avail:
                with st.form("sale_form", clear_on_submit=True):
                    tid = st.selectbox("Ticket ID", avail, key="sale_tid")
                    cust = st.text_input("Customer Name", key="sale_customer")
                    confirm = st.form_submit_button("Confirm Sale")
                    if confirm:
                        idx_list = tickets.index[tickets["TicketID"] == tid].tolist()
                        if idx_list:
                            idx = idx_list[0]
                            tickets.at[idx, "Sold"] = True
                            tickets.at[idx, "Customer"] = cust
                            tickets.at[idx, "Timestamp"] = str(pd.Timestamp.now())
                            save_tickets_df(tickets)
                            st.success(f"✅ Ticket {tid} sold to {cust}.")
                        else:
                            st.error("Ticket not found.")
            else:
                st.info("No available tickets in this category.")

        # ---------- BULK UPLOAD ----------
        elif sale_tab == "Bulk Upload":
            st.info("📋 Upload Excel/CSV with columns: `Ticket_ID`, `Customer`")
            uploaded_file = st.file_uploader("Choose Excel/CSV file", type=["csv", "xlsx", "xls"], key="bulk_uploader")

            if uploaded_file is not None:
                try:
                    if uploaded_file.name.lower().endswith(".csv"):
                        bulk_df = pd.read_csv(uploaded_file)
                    else:
                        bulk_df = pd.read_excel(uploaded_file)

                    st.write("**Preview:**")
                    st.dataframe(bulk_df.head(), use_container_width=True)

                    required_cols = ["Ticket_ID", "Customer"]
                    if not all(col in bulk_df.columns for col in required_cols):
                        st.error(f"❌ File must have columns: {', '.join(required_cols)}")
                    else:
                        if st.button("✅ Process Bulk Sale", key="bulk_process"):
                            success_count = 0
                            error_tickets = []

                            # Pre-build a map to accelerate lookup
                            id_to_index = {tid: i for i, tid in enumerate(tickets["TicketID"].tolist())}

                            for _, row in bulk_df.iterrows():
                                tid = str(row["Ticket_ID"]).zfill(4)
                                cust = str(row["Customer"]).strip()
                                idx = id_to_index.get(tid)
                                if idx is not None and not tickets.at[idx, "Sold"]:
                                    tickets.at[idx, "Sold"] = True
                                    tickets.at[idx, "Customer"] = cust
                                    tickets.at[idx, "Timestamp"] = str(pd.Timestamp.now())
                                    success_count += 1
                                else:
                                    error_tickets.append(tid)

                            save_tickets_df(tickets)

                            if success_count > 0:
                                st.success(f"✅ {success_count} tickets processed successfully.")
                            if error_tickets:
                                preview = ", ".join(error_tickets[:10])
                                suffix = "..." if len(error_tickets) > 10 else ""
                                st.warning(f"⚠️ {len(error_tickets)} tickets failed (not found or already sold): {preview}{suffix}")
                except Exception as e:
                    st.error(f"❌ File read error: {str(e)}")

        # ---------- Reverse Sale ----------
        elif sale_tab == "Reverse Sale":
            r_type = st.radio("Type", ["Public", "Guest"], horizontal=True, key="rev_type")
            r_cat_options = menu.loc[menu["Type"] == r_type, "Category"].dropna().unique().tolist()
            r_cat = st.selectbox("Category", r_cat_options, key="rev_cat")

            sold_tickets = tickets[(tickets["Type"] == r_type) & (tickets["Category"] == r_cat) & (tickets["Sold"])]["TicketID"].tolist()

            if sold_tickets:
                with st.form("reverse_sale_form"):
                    tid = st.selectbox("Ticket ID to reverse", sold_tickets, key="rev_tid")
                    confirm = st.form_submit_button("Reverse Sale")
                    if confirm:
                        idx_list = tickets.index[tickets["TicketID"] == tid].tolist()
                        if idx_list:
                            idx = idx_list[0]
                            tickets.at[idx, "Sold"] = False
                            tickets.at[idx, "Customer"] = ""
                            tickets.at[idx, "Visited"] = False
                            tickets.at[idx, "Visitor_Seats"] = 0
                            tickets.at[idx, "Timestamp"] = None
                            save_tickets_df(tickets)
                            st.success(f"✅ Sale reversed for Ticket {tid}.")
                        else:
                            st.error("Ticket not found.")
            else:
                st.info("No sold tickets to reverse in this category.")

    with col_out:
        st.write("**Recent Sales History**")
        recent_sales = tickets[tickets["Sold"]].copy()
        if not recent_sales.empty:
            # Sort by Timestamp (string), robustly handling None
            recent_sales["Timestamp_sort"] = pd.to_datetime(recent_sales["Timestamp"], errors="coerce")
            recent_sales = recent_sales.sort_values("Timestamp_sort", ascending=False).drop(columns="Timestamp_sort")
            recent_sales.insert(0, "Sno", range(1, len(recent_sales) + 1))
            st.dataframe(
                recent_sales[["Sno", "TicketID", "Category", "Customer", "Timestamp"]],
                hide_index=True, use_container_width=True
            )
        else:
            st.info("No sales recorded yet.")

# -------------------------------------------------
# 3. VISITORS
# -------------------------------------------------
with tabs[2]:
    st.subheader("Visitor Entry Management")
    v_in, v_out = st.columns([1, 1.2])

    with v_in:
        v_action = st.radio("Action", ["Entry", "Reverse Entry"], horizontal=True, key="vis_action")

        if v_action == "Entry":
            v_type = st.radio("Entry Type", ["Public", "Guest"], horizontal=True, key="vis_type")
            v_cat_options = menu.loc[menu["Type"] == v_type, "Category"].dropna().unique().tolist()
            v_cat = st.selectbox("Entry Category", v_cat_options, key="vis_cat")

            elig = tickets[(tickets["Type"] == v_type) & (tickets["Category"] == v_cat) &
                           (tickets["Sold"]) & (~tickets["Visited"])]["TicketID"].tolist()

            if elig:
                with st.form("checkin_form"):
                    tid = st.selectbox("Select Ticket ID", elig, key="vis_tid")
                    # Pull current admit for the selected ticket
                    max_v = int(tickets.loc[tickets["TicketID"] == tid, "Admit"].values[0])
                    v_count = st.number_input("Confirmed Visitors", min_value=1, max_value=max_v, value=max_v, step=1, key="vis_count")
                    confirm = st.form_submit_button("Confirm Entry")
                    if confirm:
                        idx_list = tickets.index[tickets["TicketID"] == tid].tolist()
                        if idx_list:
                            idx = idx_list[0]
                            tickets.at[idx, "Visited"] = True
                            tickets.at[idx, "Visitor_Seats"] = int(v_count)
                            tickets.at[idx, "Timestamp"] = str(pd.Timestamp.now())
                            save_tickets_df(tickets)
                            st.success(f"✅ Entry confirmed for Ticket {tid}.")
                        else:
                            st.error("Ticket not found.")
            else:
                st.info("No eligible tickets for entry.")

        else:  # Reverse Entry
            rv_type = st.radio("Entry Type", ["Public", "Guest"], horizontal=True, key="rev_vis_type")
            rv_cat_options = menu.loc[menu["Type"] == rv_type, "Category"].dropna().unique().tolist()
            rv_cat = st.selectbox("Entry Category", rv_cat_options, key="rev_vis_cat")

            visited_tickets = tickets[(tickets["Type"] == rv_type) & (tickets["Category"] == rv_cat) &
                                      (tickets["Visited"])]["TicketID"].tolist()

            if visited_tickets:
                with st.form("reverse_entry_form"):
                    tid = st.selectbox("Ticket ID to modify", visited_tickets, key="rev_vis_tid")

                    editable_cats = {"FAMILY SILVER", "FAMILY BRONZE"}
                    allow_edit = str(rv_cat).strip().upper() in editable_cats

                    if allow_edit:
                        max_admit = int(tickets.loc[tickets["TicketID"] == tid, "Admit"].values[0])
                        current_seats = int(tickets.loc[tickets["TicketID"] == tid, "Visitor_Seats"].fillna(0).values[0])
                        if current_seats < 1:
                            current_seats = max_admit
                        new_seats = st.number_input("Confirmed Visitors (can be < Admit)",
                                                    min_value=0, max_value=max_admit, value=current_seats, step=1,
                                                    key="rev_vis_count")
                        confirm_update = st.form_submit_button("Update Entry")
                        if confirm_update:
                            idx_list = tickets.index[tickets["TicketID"] == tid].tolist()
                            if idx_list:
                                idx = idx_list[0]
                                if new_seats == 0:
                                    tickets.at[idx, "Visited"] = False
                                    tickets.at[idx, "Visitor_Seats"] = 0
                                    tickets.at[idx, "Timestamp"] = None
                                    st.success(f"✅ Entry removed for Ticket {tid}.")
                                else:
                                    tickets.at[idx, "Visited"] = True
                                    tickets.at[idx, "Visitor_Seats"] = int(new_seats)
                                    tickets.at[idx, "Timestamp"] = str(pd.Timestamp.now())
                                    st.success(f"✅ Entry updated for Ticket {tid} with {new_seats} visitors.")
                                save_tickets_df(tickets)
                            else:
                                st.error("Ticket not found.")
                    else:
                        st.info("This category will fully reverse the entry.")
                        confirm_reverse = st.form_submit_button("Reverse Entry")
                        if confirm_reverse:
                            idx_list = tickets.index[tickets["TicketID"] == tid].tolist()
                            if idx_list:
                                idx = idx_list[0]
                                tickets.at[idx, "Visited"] = False
                                tickets.at[idx, "Visitor_Seats"] = 0
                                tickets.at[idx, "Timestamp"] = None
                                save_tickets_df(tickets)
                                st.success(f"✅ Entry reversed for Ticket {tid}.")
                            else:
                                st.error("Ticket not found.")
            else:
                st.info("No visitor entries to reverse.")

    with v_out:
        st.write("**Recent Visitors**")
        recent_visitors = tickets[tickets["Visited"]].copy()
        if not recent_visitors.empty:
            recent_visitors["Timestamp_sort"] = pd.to_datetime(recent_visitors["Timestamp"], errors="coerce")
            recent_visitors = recent_visitors.sort_values("Timestamp_sort", ascending=False).drop(columns="Timestamp_sort")
            recent_visitors.insert(0, "Sno", range(1, len(recent_visitors) + 1))
            st.dataframe(
                recent_visitors[["Sno", "TicketID", "Category", "Customer", "Visitor_Seats", "Timestamp"]],
                hide_index=True, use_container_width=True
            )
        else:
            st.info("No visitors recorded yet.")

# -------------------------------------------------
# 4. EDIT MENU
# -------------------------------------------------
with tabs[3]:
    st.subheader("Menu & Series Configuration")

    menu_display = custom_sort(menu.copy())

    # Auto-calc Alloc and Total_Capacity based on Series (e.g., "1-50")
    def recompute_menu_fields(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        for index, row in df.iterrows():
            try:
                series = str(row.get("Series", "")).strip()
                admit = int(row.get("Admit", 1))
                if "-" in series:
                    start, end = map(int, series.split("-"))
                    count = max((end - start) + 1, 0)
                    df.at[index, "Alloc"] = count
                    df.at[index, "Total_Capacity"] = count * admit
            except Exception:
                # Ignore bad series values silently
                pass
        return df

    menu_display = recompute_menu_fields(menu_display)

    edited_menu = st.data_editor(
        menu_display,
        hide_index=True,
        use_container_width=True,
        key="menu_editor",
        num_rows="dynamic"
    )

    st.divider()
    menu_pass_input = st.text_input("Enter Menu Update Password", type="password", key="menu_pass")

    if st.button("Update Database Menu", key="menu_update_btn"):
        if menu_pass_input == "admin123":
            # Build tickets from edited menu + preserve existing tickets if present
            new_tickets_list = []
            # Pre-map existing tickets for quick reuse
            existing_map = {row["TicketID"]: row for _, row in tickets.iterrows()}

            for _, m_row in edited_menu.iterrows():
                try:
                    series = str(m_row.get("Series", "")).strip()
                    if "-" in series:
                        start, end = map(int, series.split("-"))
                        for tid in range(start, end + 1):
                            tid_str = str(tid).zfill(4)
                            if tid_str in existing_map:
                                new_tickets_list.append(existing_map[tid_str])
                            else:
                                new_tickets_list.append({
                                    "TicketID": tid_str,
                                    "Category": m_row.get("Category", ""),
                                    "Type": m_row.get("Type", ""),
                                    "Admit": int(m_row.get("Admit", 1)),
                                    "Seq": m_row.get("Seq"),
                                    "Sold": False,
                                    "Visited": False,
                                    "Customer": "",
                                    "Visitor_Seats": 0,
                                    "Timestamp": None
                                })
                except Exception:
                    # Skip malformed rows
                    continue

            final_tickets_df = pd.DataFrame(new_tickets_list)
            # Persist both
            edited_menu_clean = recompute_menu_fields(edited_menu)
            save_both(final_tickets_df, edited_menu_clean)

            # Update in-memory references for immediate UI consistency
            tickets = final_tickets_df
            menu = edited_menu_clean

            st.success("✅ Menu and Inventory synchronized.")
        else:
            st.error("❌ Incorrect Menu Password")
``
