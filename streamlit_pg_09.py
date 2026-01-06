import streamlit as st
import pandas as pd
from sqlalchemy import create_engine
import io

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
            st.session_state.admin_pass_key += 1
            st.success("Database has been reset.")
            rerun_on_tab("📊 Dashboard")
        else:
            st.error("Incorrect Admin Password")

# -------------------------------------------------
# TABS - FIXED TAB STATE
# -------------------------------------------------
tab_labels = ["📊 Dashboard", "💰 Sales", "🚶 Visitors", "⚙️ Edit Menu"]
tabs = st.tabs(tab_labels)

# -------------------------------------------------
# 1. DASHBOARD
# -------------------------------------------------
with tabs[0]:
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
        "Seq", "Type", "Category", "Admit", "Total_Tickets", "Tickets_Sold",
        "Total_Seats", "Seats_sold", "Total_Visitors", "Balance_Tickets",
        "Balance_Seats", "Balance_Visitors"
    ]

    summary = custom_sort(summary[column_order])
    totals = pd.DataFrame([summary.select_dtypes(include="number").sum()])
    totals["Seq"] = "Total"
    summary_final = pd.concat([summary, totals], ignore_index=True).dropna(how="all")

    st.dataframe(summary_final, hide_index=True, use_container_width=True, height=450)

# -------------------------------------------------
# 2. SALES - FIXED WITH BULK UPLOAD
# -------------------------------------------------
with tabs[1]:
    st.session_state.active_tab = tab_labels[1]
    st.subheader("Sales Management")
    col_in, col_out = st.columns([1, 1.2])

    with col_in:
        sale_action_key = f"sale_action_{st.session_state.get('sale_action_counter', 0)}"
        sale_tab = st.radio(
            "Action", ["Manual", "Bulk Upload", "Reverse Sale"],
            key=sale_action_key, horizontal=True
        )

        # ---------- Manual Sale ----------
        if sale_tab == "Manual":
            sale_type_key = f"sale_type_{st.session_state.get('sale_type_counter', 0)}"
            s_type = st.radio("Type", ["Public", "Guest"], horizontal=True, key=sale_type_key)
            
            sale_cat_key = f"sale_cat_{st.session_state.get('sale_cat_counter', 0)}"
            s_cat = st.selectbox("Category", menu[menu["Type"] == s_type]["Category"], key=sale_cat_key)

            avail = tickets[(tickets["Type"] == s_type) & (tickets["Category"] == s_cat) & (~tickets["Sold"])]["TicketID"].tolist()

            if avail:
                with st.form("sale_form", clear_on_submit=True):
                    tid = st.selectbox("Ticket ID", avail)
                    cust = st.text_input("Customer Name")
                    if st.form_submit_button("Confirm Sale"):
                        idx = tickets.index[tickets["TicketID"] == tid][0]
                        tickets.at[idx, "Sold"] = True
                        tickets.at[idx, "Customer"] = cust
                        tickets.at[idx, "Timestamp"] = str(pd.Timestamp.now())
                        save_tickets_df(tickets)
                        st.success(f"Ticket {tid} sold to {cust}.")
                        st.session_state.sale_action_counter = st.session_state.get('sale_action_counter', 0) + 1
                        rerun_on_tab("💰 Sales")
            else:
                st.info("No available tickets in this category.")

        # ---------- BULK UPLOAD ----------
        elif sale_tab == "Bulk Upload":
            st.info("📋 **Upload Excel/CSV with columns: `Ticket_ID`, `Customer`**")
            st.markdown("*Example: `0001,John Doe`, `0002,Jane Smith`*")
            
            uploaded_file = st.file_uploader("Choose Excel/CSV file", type=["csv", "xlsx", "xls"])
            
            if uploaded_file is not None:
                try:
                    if uploaded_file.name.endswith('.csv'):
                        bulk_df = pd.read_csv(uploaded_file)
                    else:
                        bulk_df = pd.read_excel(uploaded_file)
                    
                    st.write("**Preview:**")
                    st.dataframe(bulk_df.head())
                    
                    # Validate columns
                    required_cols = ['Ticket_ID', 'Customer']
                    if not all(col in bulk_df.columns for col in required_cols):
                        st.error(f"❌ File must have columns: {', '.join(required_cols)}")
                    elif st.button("✅ Process Bulk Sale", key="bulk_process"):
                        success_count = 0
                        error_tickets = []
                        
                        for _, row in bulk_df.iterrows():
                            tid = str(row['Ticket_ID']).zfill(4)
                            cust = str(row['Customer']).strip()
                            
                            # Check if ticket exists and is available
                            ticket_match = tickets[tickets['TicketID'] == tid]
                            if not ticket_match.empty and not ticket_match.iloc[0]['Sold']:
                                idx = tickets.index[tickets['TicketID'] == tid][0]
                                tickets.at[idx, 'Sold'] = True
                                tickets.at[idx, 'Customer'] = cust
                                tickets.at[idx, 'Timestamp'] = str(pd.Timestamp.now())
                                success_count += 1
                            else:
                                error_tickets.append(tid)
                        
                        save_tickets_df(tickets)
                        
                        if success_count > 0:
                            st.success(f"✅ **{success_count} tickets processed successfully!**")
                        if error_tickets:
                            st.warning(f"⚠️ **{len(error_tickets)} tickets failed:** {error_tickets[:5]}{'...' if len(error_tickets)>5 else ''}")
                        
                        st.session_state.sale_action_counter = st.session_state.get('sale_action_counter', 0) + 1
                        rerun_on_tab("💰 Sales")
                        
                except Exception as e:
                    st.error(f"❌ File read error: {str(e)}")

        # ---------- Reverse Sale ----------
        elif sale_tab == "Reverse Sale":
            rs_type_key = f"rs_type_{st.session_state.get('rs_type_counter', 0)}"
            r_type = st.radio("Type", ["Public", "Guest"], horizontal=True, key=rs_type_key)
            
            rs_cat_key = f"rs_cat_{st.session_state.get('rs_cat_counter', 0)}"
            r_cat = st.selectbox("Category", menu[menu["Type"] == r_type]["Category"], key=rs_cat_key)

            sold_tickets = tickets[(tickets["Type"] == r_type) & (tickets["Category"] == r_cat) & (tickets["Sold"])]["TicketID"].tolist()

            if sold_tickets:
                with st.form("reverse_sale_form"):
                    tid = st.selectbox("Ticket ID to reverse", sold_tickets)
                    if st.form_submit_button("Reverse Sale"):
                        idx = tickets.index[tickets["TicketID"] == tid][0]
                        tickets.at[idx, "Sold"] = False
                        tickets.at[idx, "Customer"] = ""
                        tickets.at[idx, "Visited"] = False
                        tickets.at[idx, "Visitor_Seats"] = 0
                        tickets.at[idx, "Timestamp"] = None
                        save_tickets_df(tickets)
                        st.success(f"Sale reversed for Ticket {tid}.")
                        st.session_state.sale_action_counter = st.session_state.get('sale_action_counter', 0) + 1
                        rerun_on_tab("💰 Sales")
            else:
                st.info("No sold tickets to reverse in this category.")

    with col_out:
        st.write("**Recent Sales History**")
        recent_sales = tickets[tickets["Sold"]].sort_values("Timestamp", ascending=False).copy()
        if not recent_sales.empty:
            recent_sales.insert(0, "Sno", range(1, len(recent_sales) + 1))
            st.dataframe(recent_sales[["Sno", "TicketID", "Category", "Customer", "Timestamp"]], 
                        hide_index=True, use_container_width=True)
        else:
            st.info("No sales recorded yet.")

# -------------------------------------------------
# 3. VISITORS - FIXED TAB STATE
# -------------------------------------------------
with tabs[2]:
    st.session_state.active_tab = tab_labels[2]
    st.subheader("Visitor Entry Management")
    v_in, v_out = st.columns([1, 1.2])

    with v_in:
        v_action_key = f"v_action_{st.session_state.get('v_action_counter', 0)}"
        v_action = st.radio("Action", ["Entry", "Reverse Entry"], horizontal=True, key=v_action_key)

        if v_action == "Entry":
            v_type_key = f"v_type_{st.session_state.get('v_type_counter', 0)}"
            v_type = st.radio("Entry Type", ["Public", "Guest"], horizontal=True, key=v_type_key)
            
            v_cat_key = f"v_cat_{st.session_state.get('v_cat_counter', 0)}"
            v_cat = st.selectbox("Entry Category", menu[menu["Type"] == v_type]["Category"], key=v_cat_key)

            elig = tickets[(tickets["Type"] == v_type) & (tickets["Category"] == v_cat) & 
                          (tickets["Sold"]) & (~tickets["Visited"])]["TicketID"].tolist()

            if elig:
                with st.form("checkin"):
                    tid = st.selectbox("Select Ticket ID", elig)
                    max_v = int(tickets[tickets["TicketID"] == tid]["Admit"].values[0])
                    v_count = st.number_input("Confirmed Visitors", min_value=1, max_value=max_v, value=max_v)
                    if st.form_submit_button("Confirm Entry"):
                        idx = tickets.index[tickets["TicketID"] == tid][0]
                        tickets.at[idx, "Visited"] = True
                        tickets.at[idx, "Visitor_Seats"] = v_count
                        tickets.at[idx, "Timestamp"] = str(pd.Timestamp.now())
                        save_tickets_df(tickets)
                        st.success(f"Entry confirmed for Ticket {tid}.")
                        st.session_state.v_action_counter = st.session_state.get('v_action_counter', 0) + 1
                        rerun_on_tab("🚶 Visitors")
            else:
                st.info("No eligible tickets for entry.")

        else:  # Reverse Entry
            rv_type_key = f"rv_type_{st.session_state.get('rv_type_counter', 0)}"
            rv_type = st.radio("Entry Type", ["Public", "Guest"], horizontal=True, key=rv_type_key)
            
            rv_cat_key = f"rv_cat_{st.session_state.get('rv_cat_counter', 0)}"
            rv_cat = st.selectbox("Entry Category", menu[menu["Type"] == rv_type]["Category"], key=rv_cat_key)

            visited_tickets = tickets[(tickets["Type"] == rv_type) & (tickets["Category"] == rv_cat) & 
                                    (tickets["Visited"])]["TicketID"].tolist()

            if visited_tickets:
                with st.form("reverse_entry"):
                    tid = st.selectbox("Ticket ID to modify", visited_tickets)
                    
                    editable_cats = {"FAMILY SILVER", "FAMILY BRONZE"}
                    allow_edit = str(rv_cat).strip().upper() in editable_cats

                    if allow_edit:
                        max_admit = int(tickets[tickets["TicketID"] == tid]["Admit"].values[0])
                        current_seats = int(tickets[tickets["TicketID"] == tid]["Visitor_Seats"].values[0])
                        if current_seats < 1:
                            current_seats = max_admit
                        new_seats = st.number_input("Confirmed Visitors (can be < Admit)", 
                                                  min_value=0, max_value=max_admit, value=current_seats)
                        if st.form_submit_button("Update Entry"):
                            idx = tickets.index[tickets["TicketID"] == tid][0]
                            if new_seats == 0:
                                tickets.at[idx, "Visited"] = False
                                tickets.at[idx, "Visitor_Seats"] = 0
                                tickets.at[idx, "Timestamp"] = None
                                st.success(f"Entry removed for Ticket {tid}.")
                            else:
                                tickets.at[idx, "Visited"] = True
                                tickets.at[idx, "Visitor_Seats"] = new_seats
                                tickets.at[idx, "Timestamp"] = str(pd.Timestamp.now())
                                st.success(f"Entry updated for Ticket {tid} with {new_seats} visitors.")
                            save_tickets_df(tickets)
                            st.session_state.v_action_counter = st.session_state.get('v_action_counter', 0) + 1
                            rerun_on_tab("🚶 Visitors")
                    else:
                        st.info("This category will fully reverse the entry.")
                        if st.form_submit_button("Reverse Entry"):
                            idx = tickets.index[tickets["TicketID"] == tid][0]
                            tickets.at[idx, "Visited"] = False
                            tickets.at[idx, "Visitor_Seats"] = 0
                            tickets.at[idx, "Timestamp"] = None
                            save_tickets_df(tickets)
                            st.success(f"Entry reversed for Ticket {tid}.")
                            st.session_state.v_action_counter = st.session_state.get('v_action_counter', 0) + 1
                            rerun_on_tab("🚶 Visitors")
            else:
                st.info("No visitor entries to reverse.")

    with v_out:
        st.write("**Recent Visitors**")
        recent_visitors = tickets[tickets["Visited"]].sort_values("Timestamp", ascending=False).copy()
        if not recent_visitors.empty:
            recent_visitors.insert(0, "Sno", range(1, len(recent_visitors) + 1))
            st.dataframe(recent_visitors[["Sno", "TicketID", "Category", "Customer", "Visitor_Seats", "Timestamp"]], 
                        hide_index=True, use_container_width=True)
        else:
            st.info("No visitors recorded yet.")

# -------------------------------------------------
# 4. EDIT MENU
# -------------------------------------------------
with tabs[3]:
    st.session_state.active_tab = tab_labels[3]
    st.subheader("Menu & Series Configuration")
    menu_display = custom_sort(menu.copy())

    edited_menu = st.data_editor(menu_display, hide_index=True, use_container_width=True, key="menu_editor")

    for index, row in edited_menu.iterrows():
        try:
            if "-" in str(row["Series"]):
                start, end = map(int, str(row["Series"]).split("-"))
                count = (end - start) + 1
                edited_menu.at[index, "Alloc"] = count
                edited_menu.at[index, "Total_Capacity"] = count * int(row["Admit"])
        except Exception:
            pass

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
                            new_tickets_list.append({
                                "TicketID": tid_str, "Category": m_row["Category"], "Type": m_row["Type"],
                                "Admit": m_row["Admit"], "Seq": m_row["Seq"], "Sold": False, "Visited": False,
                                "Customer": "", "Visitor_Seats": 0, "Timestamp": None
                            })
                except Exception:
                    continue

            final_tickets_df = pd.DataFrame(new_tickets_list)
            save_both(final_tickets_df, edited_menu)
            st.session_state.menu_pass_key += 1
            st.success("Menu and Inventory synchronized.")
            rerun_on_tab("⚙️ Edit Menu")
        else:
            st.error("Incorrect Menu Password")
