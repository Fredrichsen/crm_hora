import streamlit as st
import sqlite3
import pandas as pd
import math
from datetime import datetime, date, timedelta
from fpdf import FPDF
import unicodedata

# ==========================================
# CONFIGURAÇÃO DE ESTÉTICA CLEAN
# ==========================================
st.set_page_config(page_title="Gestão de OS - CRM", layout="wide", initial_sidebar_state="expanded")

def check_success_message():
    if 'sucesso' in st.session_state:
        st.success(st.session_state['sucesso'])
        del st.session_state['sucesso']

# ==========================================
# CONEXÃO E BANCO DE DADOS (COM AGENDAMENTOS)
# ==========================================
def get_db_connection():
    conn = sqlite3.connect('crm_horas.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS config (id INTEGER PRIMARY KEY, valor_hora REAL, imposto_perc REAL)''')
    c.execute("SELECT COUNT(*) FROM config")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO config (valor_hora, imposto_perc) VALUES (150.0, 10.0)")
        
    c.execute('''CREATE TABLE IF NOT EXISTS clientes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, empresa_mae_id INTEGER,
                    FOREIGN KEY(empresa_mae_id) REFERENCES clientes(id))''')
                    
    c.execute('''CREATE TABLE IF NOT EXISTS ordens_servico (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, cliente_id INTEGER, solicitante TEXT,
                    tipo TEXT, data_os DATE, minutos_reais INTEGER, minutos_cobrados INTEGER, historico TEXT,
                    FOREIGN KEY(cliente_id) REFERENCES clientes(id))''')
                    
    c.execute('''CREATE TABLE IF NOT EXISTS agendamentos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, cliente_id INTEGER, titulo TEXT,
                    data_agendada DATE, descricao TEXT, status TEXT DEFAULT 'Pendente',
                    FOREIGN KEY(cliente_id) REFERENCES clientes(id))''')
    conn.commit()
    conn.close()

init_db()

# ==========================================
# FUNÇÕES AUXILIARES E REGRAS DE NEGÓCIO
# ==========================================
def calcular_minutos_cobrados(minutos_reais):
    if minutos_reais <= 0: return 0
    return math.ceil(minutos_reais / 15.0) * 15

def get_config():
    conn = get_db_connection()
    config = conn.execute("SELECT * FROM config LIMIT 1").fetchone()
    conn.close()
    return config

def formatar_horas(minutos):
    return f"{int(minutos // 60)}h {int(minutos % 60):02d}m"

def remover_acentos(txt):
    if not txt: return ""
    return ''.join(c for c in unicodedata.normalize('NFD', txt) if unicodedata.category(c) != 'Mn')

def gerar_pdf_os(os_id, cliente_nome, data_os, solicitante, tipo, horas, historico, valor_hora):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, remover_acentos(f"ORDEM DE SERVICO #{os_id}"), ln=True, align='C')
    pdf.ln(5)
    
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(30, 8, "Cliente:", border=0)
    pdf.set_font("Arial", '', 11)
    pdf.cell(0, 8, remover_acentos(cliente_nome), ln=True)
    
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(30, 8, "Data:", border=0)
    pdf.set_font("Arial", '', 11)
    pdf.cell(0, 8, remover_acentos(data_os), ln=True)

    pdf.set_font("Arial", 'B', 11)
    pdf.cell(30, 8, "Solicitante:", border=0)
    pdf.set_font("Arial", '', 11)
    pdf.cell(0, 8, remover_acentos(solicitante), ln=True)
    
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(30, 8, "Modalidade:", border=0)
    pdf.set_font("Arial", '', 11)
    pdf.cell(0, 8, remover_acentos(tipo), ln=True)

    pdf.set_font("Arial", 'B', 11)
    pdf.cell(30, 8, "Tempo:", border=0)
    pdf.set_font("Arial", '', 11)
    pdf.cell(0, 8, remover_acentos(horas), ln=True)
    
    pdf.ln(10)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 8, remover_acentos("Historico / Descricao do Atendimento:"), ln=True, border='B')
    pdf.ln(2)
    pdf.set_font("Arial", '', 11)
    pdf.multi_cell(0, 6, remover_acentos(historico))
    
    return bytes(pdf.output(dest='S'), encoding='latin-1')

# ==========================================
# NAVEGAÇÃO LATERAL (MENU)
# ==========================================
st.sidebar.title("🏢 Menu Principal")
menu = st.sidebar.radio("Navegação",[
    "Visão Geral (Dashboard)", 
    "📅 Agendamentos", 
    "🛠️ Ordens de Serviço", 
    "👥 Meus Clientes", 
    "⚙️ Configurações"
])

# ==========================================
# PÁGINA 1: DASHBOARD
# ==========================================
if menu == "Visão Geral (Dashboard)":
    st.title("📊 Visão Geral do Mês Atual")
    mes_atual = datetime.now().strftime('%Y-%m')
    
    conn = get_db_connection()
    query = f"""
        SELECT o.id, c.nome as Cliente, o.data_os, o.tipo, o.minutos_cobrados, o.historico 
        FROM ordens_servico o
        JOIN clientes c ON o.cliente_id = c.id
        WHERE strftime('%Y-%m', o.data_os) = '{mes_atual}'
        ORDER BY o.data_os DESC, o.id DESC
    """
    df_os = pd.read_sql_query(query, conn)
    config = get_config()
    conn.close()
    
    if df_os.empty:
        st.info("Nenhuma Ordem de Serviço lançada neste mês.")
    else:
        df_os['data_os'] = pd.to_datetime(df_os['data_os']).dt.strftime('%d/%m/%Y') # Formatando datas DD/MM/AAAA
        total_minutos = df_os['minutos_cobrados'].sum()
        valor_bruto_total = (total_minutos / 60.0) * config['valor_hora']
        valor_liquido_total = valor_bruto_total - (valor_bruto_total * (config['imposto_perc'] / 100))
        cliente_campeao = df_os.groupby('Cliente')['minutos_cobrados'].sum().idxmax()
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("⏱️ Horas Mês", formatar_horas(total_minutos))
        col2.metric("💰 Bruto", f"R$ {valor_bruto_total:,.2f}")
        col3.metric("💵 Líquido", f"R$ {valor_liquido_total:,.2f}")
        col4.metric("🏆 Top Cliente", cliente_campeao)
        
        st.write("---")
        aba1, aba2, aba3 = st.tabs(["📋 Resumo por Cliente", "📈 Gráficos", "🔍 Extrato Detalhado Mensal"])
        
        with aba1:
            df_ag = df_os.groupby('Cliente')['minutos_cobrados'].sum().reset_index()
            df_ag['Horas Totais'] = df_ag['minutos_cobrados'].apply(formatar_horas)
            df_ag['Faturamento Bruto'] = (df_ag['minutos_cobrados'] / 60.0) * config['valor_hora']
            df_ag['Faturamento Líquido'] = df_ag['Faturamento Bruto'] * (1 - (config['imposto_perc']/100))
            df_display = df_ag[['Cliente', 'Horas Totais', 'Faturamento Bruto', 'Faturamento Líquido']].copy()
            st.dataframe(df_display.style.format({'Faturamento Bruto': 'R$ {:.2f}', 'Faturamento Líquido': 'R$ {:.2f}'}), use_container_width=True, hide_index=True)
            
        with aba2:
            st.bar_chart(data=df_ag, x='Cliente', y='Faturamento Bruto', use_container_width=True)

        with aba3:
            df_extrato = df_os.copy()
            df_extrato['Horas Faturadas'] = df_extrato['minutos_cobrados'].apply(formatar_horas)
            st.dataframe(df_extrato[['id', 'data_os', 'Cliente', 'tipo', 'Horas Faturadas', 'historico']], use_container_width=True, hide_index=True)

# ==========================================
# PÁGINA 2: AGENDAMENTOS
# ==========================================
elif menu == "📅 Agendamentos":
    st.title("📅 Gestão de Agendamentos e Projetos")
    check_success_message()
    conn = get_db_connection()
    clientes = pd.read_sql_query("SELECT id, nome FROM clientes ORDER BY nome", conn)
    
    if clientes.empty:
        st.warning("Cadastre um cliente primeiro.")
    else:
        aba_novo, aba_pend, aba_fin = st.tabs(["➕ Novo Agendamento", "⏳ Pendentes (Gerar OS)", "✅ Finalizados"])
        opcoes_clientes = dict(zip(clientes.nome, clientes.id))
        
        with aba_novo:
            with st.form("form_agendamento", clear_on_submit=True):
                c1, c2 = st.columns(2)
                cli_sel = c1.selectbox("Cliente", list(opcoes_clientes.keys()), key="ag_cli")
                titulo = c2.text_input("Título / Assunto da Tarefa")
                data_ag = st.date_input("Data do Agendamento", date.today(), format="DD/MM/YYYY")
                desc = st.text_area("Descrição detalhada")
                
                if st.form_submit_button("Salvar Agendamento", type="primary"):
                    conn.execute("INSERT INTO agendamentos (cliente_id, titulo, data_agendada, descricao) VALUES (?, ?, ?, ?)",
                                 (opcoes_clientes[cli_sel], titulo, data_ag.strftime('%Y-%m-%d'), desc))
                    conn.commit()
                    st.session_state['sucesso'] = "Agendamento salvo com sucesso!"
                    st.rerun()
                    
        with aba_pend:
            df_pend = pd.read_sql_query("SELECT a.id, c.nome as Cliente, a.titulo, a.data_agendada, a.descricao FROM agendamentos a JOIN clientes c ON a.cliente_id = c.id WHERE a.status = 'Pendente' ORDER BY a.data_agendada ASC", conn)
            if df_pend.empty:
                st.info("Nenhum agendamento pendente.")
            else:
                df_pend['data_agendada'] = pd.to_datetime(df_pend['data_agendada']).dt.strftime('%d/%m/%Y')
                st.dataframe(df_pend[['data_agendada', 'Cliente', 'titulo', 'descricao']], use_container_width=True, hide_index=True)
                
                st.markdown("#### 🚀 Transformar Agendamento em OS")
                opcoes_pend = {f"{row['data_agendada']} | {row['Cliente']} - {row['titulo']}": row['id'] for _, row in df_pend.iterrows()}
                ag_selecionado = st.selectbox("Selecione o Agendamento para Finalizar", list(opcoes_pend.keys()))
                
                if ag_selecionado:
                    ag_id = opcoes_pend[ag_selecionado]
                    ag_info = conn.execute("SELECT * FROM agendamentos WHERE id = ?", (ag_id,)).fetchone()
                    
                    with st.form("form_gerar_os"):
                        st.info("Preencha os dados reais de tempo para gerar a OS e finalizar o agendamento.")
                        c_h1, c_h2, c_p = st.columns(3)
                        hora_inicio = c_h1.time_input("Hora de Início", step=900)
                        hora_fim = c_h2.time_input("Hora de Fim", step=900)
                        pausa = c_p.number_input("Pausa (min)", min_value=0, step=15)
                        
                        solicitante = st.text_input("Solicitante")
                        tipo = st.radio("Tipo", ["Home Office", "Presencial"], horizontal=True)
                        hist = st.text_area("Histórico Final da OS", value=f"Ref. Agendamento: {ag_info['titulo']}\n{ag_info['descricao']}")
                        
                        if st.form_submit_button("Gerar OS e Concluir Agendamento", type="primary"):
                            t_inicio = datetime.combine(date.today(), hora_inicio)
                            t_fim = datetime.combine(date.today(), hora_fim)
                            if t_fim > t_inicio:
                                min_reais = ((t_fim - t_inicio).total_seconds() / 60) - pausa
                                min_cobrados = calcular_minutos_cobrados(min_reais)
                                
                                conn.execute("""INSERT INTO ordens_servico (cliente_id, solicitante, tipo, data_os, minutos_reais, minutos_cobrados, historico)
                                                VALUES (?, ?, ?, ?, ?, ?, ?)""", 
                                             (ag_info['cliente_id'], solicitante, tipo, date.today().strftime('%Y-%m-%d'), min_reais, min_cobrados, hist))
                                conn.execute("UPDATE agendamentos SET status = 'Finalizado' WHERE id = ?", (ag_id,))
                                conn.commit()
                                st.session_state['sucesso'] = "OS Gerada e Agendamento Finalizado!"
                                st.rerun()
                            else:
                                st.error("A hora final deve ser maior que a inicial.")
                                
        with aba_fin:
            df_fin = pd.read_sql_query("SELECT a.id, c.nome as Cliente, a.titulo, a.data_agendada FROM agendamentos a JOIN clientes c ON a.cliente_id = c.id WHERE a.status = 'Finalizado' ORDER BY a.data_agendada DESC", conn)
            if not df_fin.empty:
                df_fin['data_agendada'] = pd.to_datetime(df_fin['data_agendada']).dt.strftime('%d/%m/%Y')
                st.dataframe(df_fin[['data_agendada', 'Cliente', 'titulo']], use_container_width=True, hide_index=True)
            else:
                st.info("Nenhum agendamento finalizado.")
    conn.close()

# ==========================================
# PÁGINA 3: ORDENS DE SERVIÇO
# ==========================================
elif menu == "🛠️ Ordens de Serviço":
    st.title("🛠️ Gestão de Ordens de Serviço")
    check_success_message()
    
    conn = get_db_connection()
    clientes = pd.read_sql_query("SELECT id, nome FROM clientes ORDER BY nome", conn)
    
    if clientes.empty:
        st.warning("Cadastre um cliente primeiro.")
    else:
        aba_lancar, aba_historico = st.tabs(["📝 Lançar Nova OS", "🔍 Histórico, Edição e PDF"])
        
        with aba_lancar:
            col_form, col_recentes = st.columns([1.5, 1])
            with col_form:
                with st.form("form_os", clear_on_submit=True):
                    opcoes_clientes = dict(zip(clientes.nome, clientes.id))
                    c1, c2 = st.columns(2)
                    cli_sel = c1.selectbox("Cliente / Empresa", list(opcoes_clientes.keys()))
                    solic = c2.text_input("Solicitante")
                    
                    c3, c4 = st.columns(2)
                    tipo_at = c3.radio("Tipo", ["Home Office", "Presencial"], horizontal=True)
                    data_os = c4.date_input("Data", date.today(), format="DD/MM/YYYY")
                    
                    st.markdown("##### Tempo")
                    c_h1, c_h2, c_p = st.columns(3)
                    agora = datetime.now()
                    min_base = (agora.minute // 15) * 15
                    h_in = agora.replace(minute=min_base, second=0).time()
                    h_out = (agora.replace(minute=min_base, second=0) + timedelta(minutes=15)).time()

                    hora_inicio = c_h1.time_input("Início", value=h_in, step=900)
                    hora_fim = c_h2.time_input("Fim", value=h_out, step=900)
                    pausa = c_p.number_input("Pausa (min)", min_value=0, value=0, step=15)

                    hist = st.text_area("Descrição")
                    if st.form_submit_button("Lançar OS", type="primary", use_container_width=True):
                        t_in = datetime.combine(data_os, hora_inicio)
                        t_out = datetime.combine(data_os, hora_fim)
                        if t_out > t_in:
                            min_reais = ((t_out - t_in).total_seconds() / 60) - pausa
                            if min_reais > 0:
                                min_cobrados = calcular_minutos_cobrados(min_reais)
                                conn.execute("""INSERT INTO ordens_servico (cliente_id, solicitante, tipo, data_os, minutos_reais, minutos_cobrados, historico)
                                                VALUES (?, ?, ?, ?, ?, ?, ?)""", 
                                             (opcoes_clientes[cli_sel], solic, tipo_at, data_os.strftime('%Y-%m-%d'), min_reais, min_cobrados, hist))
                                conn.commit()
                                st.session_state['sucesso'] = f"OS Lançada! Faturado: {formatar_horas(min_cobrados)}"
                                st.rerun()
                            else:
                                st.error("Tempo de pausa excede o período trabalhado.")
                        else:
                            st.error("A hora de fim deve ser maior que a inicial.")

            with col_recentes:
                st.markdown("##### 🕒 Últimas 5 OS")
                df_rec = pd.read_sql_query("SELECT c.nome, o.data_os, o.minutos_cobrados FROM ordens_servico o JOIN clientes c ON o.cliente_id = c.id ORDER BY o.id DESC LIMIT 5", conn)
                if not df_rec.empty:
                    df_rec['Tempo'] = df_rec['minutos_cobrados'].apply(formatar_horas)
                    df_rec['Data'] = pd.to_datetime(df_rec['data_os']).dt.strftime('%d/%m/%Y')
                    st.dataframe(df_rec[['Data', 'nome', 'Tempo']], use_container_width=True, hide_index=True)
                else:
                    st.info("Nenhuma OS lançada.")
                    
        with aba_historico:
            st.markdown("Selecione uma OS existente para visualizar, gerar PDF, editar ou excluir.")
            todas_os = pd.read_sql_query("SELECT o.id, c.nome, o.data_os FROM ordens_servico o JOIN clientes c ON o.cliente_id = c.id ORDER BY o.data_os DESC, o.id DESC", conn)

            if 'os_selecionada' not in st.session_state:
                st.session_state['os_selecionada'] = None

            if not todas_os.empty:
                # --- filtros de cliente + intervalo de datas ---
                todas_os['data_os_dt'] = pd.to_datetime(todas_os['data_os'])
                min_date = todas_os['data_os_dt'].dt.date.min()
                max_date = todas_os['data_os_dt'].dt.date.max()

                c1, c2, c3 = st.columns([1, 1, 1])
                clientes_filtragem = ["Todos"] + sorted(todas_os['nome'].unique().tolist())
                cliente_filtro = c1.selectbox("Filtrar por cliente", clientes_filtragem)
                inicio_filtro = c2.date_input("Início", min_value=min_date, max_value=max_date, value=min_date, format="DD/MM/YYYY")
                fim_filtro = c3.date_input("Fim", min_value=min_date, max_value=max_date, value=max_date, format="DD/MM/YYYY")

                df_filtrada = todas_os.copy()
                if cliente_filtro != "Todos":
                    df_filtrada = df_filtrada[df_filtrada['nome'] == cliente_filtro]
                df_filtrada = df_filtrada[
                    (df_filtrada['data_os_dt'].dt.date >= inicio_filtro) &
                    (df_filtrada['data_os_dt'].dt.date <= fim_filtro)
                ]

                if df_filtrada.empty:
                    st.warning("Nenhuma OS encontrada com esses filtros.")
                else:
                    # garante que seleção atual exista nos resultados filtrados
                    if st.session_state['os_selecionada'] not in df_filtrada['id'].tolist():
                        st.session_state['os_selecionada'] = None

                    st.markdown("#### 🔎 Lista de OS (clique para ver detalhes)")
                    for _, row in df_filtrada.head(50).iterrows():
                        cols = st.columns([1, 2, 3, 1])
                        cols[0].markdown(f"**#{row['id']}**")
                        cols[1].markdown(row['data_os_dt'].strftime('%d/%m/%Y'))
                        cols[2].markdown(row['nome'])
                        if cols[3].button("Ver", key=f"os_ver_{row['id']}"):
                            st.session_state['os_selecionada'] = int(row['id'])

                    st.markdown("---")

                    # dropdown com base no filtro aplicado
                    opcoes_os = {
                        f"OS #{row['id']} | {row['data_os_dt'].strftime('%d/%m/%Y')} - {row['nome']}": row['id']
                        for _, row in df_filtrada.iterrows()
                    }
                    st.write(f"**OS selecionada:** #{st.session_state['os_selecionada']}  ")
                    if st.button("Limpar seleção", key="limpar_os_selecao"):
                        st.session_state['os_selecionada'] = None

                    if st.session_state['os_selecionada'] is None:
                        os_selecionada = st.selectbox("Buscar Ordem de Serviço", list(opcoes_os.keys()))
                        if os_selecionada:
                            st.session_state['os_selecionada'] = int(opcoes_os[os_selecionada])

                    if st.session_state['os_selecionada']:
                        id_os = int(st.session_state['os_selecionada'])
                        os_info = conn.execute("SELECT o.*, c.nome as cliente_nome FROM ordens_servico o JOIN clientes c ON o.cliente_id = c.id WHERE o.id = ?", (id_os,)).fetchone()

                        if not os_info:
                            st.warning("A OS selecionada não foi encontrada (já pode ter sido excluída). Selecione outra OS.")
                            st.session_state['os_selecionada'] = None
                            st.stop()

                        data_formatada_br = pd.to_datetime(os_info['data_os']).strftime('%d/%m/%Y')
                        horas_faturadas_str = formatar_horas(os_info['minutos_cobrados'])
                        config = get_config()

                        # Botão de Gerar PDF
                        pdf_bytes = gerar_pdf_os(os_info['id'], os_info['cliente_nome'], data_formatada_br, 
                                                 os_info['solicitante'], os_info['tipo'], horas_faturadas_str, 
                                                 os_info['historico'], config['valor_hora'])
                        
                        st.download_button(label="📄 Baixar PDF desta OS", data=pdf_bytes, file_name=f"OS_{os_info['id']}_{os_info['cliente_nome']}.pdf", mime="application/pdf", type="primary")
                        st.divider()

                        if os_info is not None:
                            with st.expander("📝 Resumo Rápido da OS", expanded=True):
                                colA, colB, colC = st.columns(3)
                                colA.metric("Cliente", os_info['cliente_nome'])
                                colB.metric("Data", data_formatada_br)
                                colC.metric("Tipo", os_info['tipo'])
                                st.markdown(f"**Tempo faturado:** {horas_faturadas_str}")
                                st.markdown(f"**Histórico:** {os_info['historico']}")

                            with st.form("form_edicao_os"):
                                st.markdown("#### 🔧 Editar OS")
                                e_c1, e_c2 = st.columns(2)
                                match_idx = clientes[clientes['id'] == os_info['cliente_id']].index
                                default_cli_index = int(match_idx[0]) if len(match_idx) else 0
                                cli_edit = e_c1.selectbox(
                                    "Cliente",
                                    options=list(clientes.nome),
                                    index=default_cli_index,
                                )
                                solic_edit = e_c2.text_input("Solicitante", value=os_info['solicitante'])
                                
                                e_c3, e_c4 = st.columns(2)
                                tipo_edit = e_c3.radio("Tipo",["Home Office", "Presencial"], index=0 if os_info['tipo'] == "Home Office" else 1, horizontal=True)
                                data_edit = e_c4.date_input("Data", datetime.strptime(os_info['data_os'], '%Y-%m-%d').date(), format="DD/MM/YYYY")
                                
                                min_edit = st.number_input("Minutos Faturados (Múltiplo de 15 recomendável)", value=os_info['minutos_cobrados'], step=15)
                                hist_edit = st.text_area("Histórico", value=os_info['historico'], height=150)
                                
                                btn_c1, btn_c2 = st.columns(2)
                                atualizar = btn_c1.form_submit_button("💾 Salvar Alterações", use_container_width=True)
                                excluir = btn_c2.form_submit_button("🗑️ Excluir OS", use_container_width=True)
                                
                                if atualizar:
                                    id_novo_cliente = clientes[clientes['nome'] == cli_edit]['id'].values[0]
                                    conn.execute("""UPDATE ordens_servico SET cliente_id=?, solicitante=?, tipo=?, data_os=?, minutos_cobrados=?, historico=? WHERE id=?""",
                                                 (id_novo_cliente, solic_edit, tipo_edit, data_edit.strftime('%Y-%m-%d'), min_edit, hist_edit, os_info['id']))
                                    conn.commit()
                                    st.session_state['sucesso'] = "OS Atualizada com sucesso!"
                                    st.rerun()
                                    
                                if excluir:
                                    conn.execute("DELETE FROM ordens_servico WHERE id=?", (os_info['id'],))
                                    # Se a tabela ficar vazia, resetar o contador AUTOINCREMENT (sqlite_sequence)
                                    total_os = conn.execute("SELECT COUNT(*) FROM ordens_servico").fetchone()[0]
                                    if total_os == 0:
                                        conn.execute("DELETE FROM sqlite_sequence WHERE name = 'ordens_servico'")
                                    conn.commit()
                                    st.session_state['sucesso'] = "OS Excluída com sucesso!"
                                    st.rerun()
            else:
                st.info("Nenhuma OS registrada no banco de dados.")
    conn.close()

# ==========================================
# PÁGINA 4: CLIENTES
# ==========================================
elif menu == "👥 Meus Clientes":
    st.title("👥 Gestão de Clientes")
    check_success_message()
    conn = get_db_connection()
    clientes_ex = pd.read_sql_query("SELECT id, nome FROM clientes ORDER BY nome", conn)
    
    aba1, aba2 = st.tabs(["📋 Cadastrar / Listar", "✏️ Editar / Excluir"])
    
    with aba1:
        col1, col2 = st.columns([1, 1.5])
        with col1:
            with st.form("form_cliente", clear_on_submit=True):
                nome_cliente = st.text_input("Nome da Empresa")
                opcoes_mae = {"Nenhuma (É a Empresa Mãe)": None}
                if not clientes_ex.empty:
                    opcoes_mae.update(dict(zip(clientes_ex.nome, clientes_ex.id)))
                empresa_mae = st.selectbox("Pertence ao grupo de?", list(opcoes_mae.keys()))
                
                if st.form_submit_button("Salvar Cliente", type="primary", use_container_width=True) and nome_cliente:
                    conn.execute("INSERT INTO clientes (nome, empresa_mae_id) VALUES (?, ?)", (nome_cliente, opcoes_mae[empresa_mae]))
                    conn.commit()
                    st.session_state['sucesso'] = f"Cliente '{nome_cliente}' salvo!"
                    st.rerun()
                    
        with col2:
            df_lista_cli = pd.read_sql_query("SELECT c1.nome as Empresa, IFNULL(c2.nome, 'MATRIZ') as 'Vinculada à' FROM clientes c1 LEFT JOIN clientes c2 ON c1.empresa_mae_id = c2.id ORDER BY c1.nome", conn)
            st.dataframe(df_lista_cli, use_container_width=True, hide_index=True)

    with aba2:
        if not clientes_ex.empty:
            cli_ids = clientes_ex['id'].tolist()
            cli_nomes = clientes_ex['nome'].tolist()
            sel_id = st.selectbox("Selecione o cliente", cli_ids, format_func=lambda i: cli_nomes[cli_ids.index(i)])
            cli_info = conn.execute("SELECT * FROM clientes WHERE id = ?", (sel_id,)).fetchone()

            if cli_info:
                with st.form("form_edicao_cliente"):
                    n_edit = st.text_input("Nome", value=cli_info['nome'])
                    op_edit = {"Nenhuma (É a Empresa Mãe)": None}
                    for idx, nm in zip(clientes_ex['id'], clientes_ex['nome']):
                        if idx != cli_info['id']: op_edit[nm] = idx

                    m_keys, m_vals = list(op_edit.keys()), list(op_edit.values())
                    idx_default = m_vals.index(cli_info['empresa_mae_id']) if cli_info['empresa_mae_id'] in m_vals else 0
                    mae_edit = st.selectbox("Empresa Mãe", m_keys, index=idx_default)

                    b1, b2 = st.columns(2)
                    if b1.form_submit_button("Atualizar Cliente", type="primary", use_container_width=True):
                        conn.execute("UPDATE clientes SET nome=?, empresa_mae_id=? WHERE id=?", (n_edit, op_edit[mae_edit], cli_info['id']))
                        conn.commit()
                        st.session_state['sucesso'] = "Cliente atualizado!"
                        st.rerun()

                    if b2.form_submit_button("🗑️ Excluir Cliente", use_container_width=True):
                        conn.execute("UPDATE clientes SET empresa_mae_id = NULL WHERE empresa_mae_id = ?", (cli_info['id'],))
                        conn.execute("DELETE FROM clientes WHERE id = ?", (cli_info['id'],))
                        conn.commit()
                        st.session_state['sucesso'] = "Cliente excluído!"
                        st.rerun()
    conn.close()

# ==========================================
# PÁGINA 5: CONFIGURAÇÕES
# ==========================================
elif menu == "⚙️ Configurações":
    st.title("⚙️ Configurações do Sistema")
    check_success_message()
    config = get_config()
    
    col1, col2 = st.columns([1, 2])
    with col1:
        with st.form("form_config"):
            valor_h = st.number_input("Valor Hora (R$)", min_value=0.0, value=config['valor_hora'], step=10.0)
            imposto = st.number_input("Imposto (%)", min_value=0.0, max_value=100.0, value=config['imposto_perc'], step=1.0)
            if st.form_submit_button("Atualizar Valores", type="primary", use_container_width=True):
                conn = get_db_connection()
                conn.execute("UPDATE config SET valor_hora = ?, imposto_perc = ? WHERE id = 1", (valor_h, imposto))
                conn.commit()
                conn.close()
                st.session_state['sucesso'] = "Configurações atualizadas!"
                st.rerun()