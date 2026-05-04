import os

import streamlit as st
import pandas as pd
import math
from datetime import datetime, date, timedelta
from fpdf import FPDF
import unicodedata

# dotenv pode não existir em Streamlit Cloud, então importamos com fallback
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from supabase import create_client

# Carrega variáveis de ambiente do arquivo .env (se existir e se a biblioteca estiver disponível)
if load_dotenv is not None:
    dotenv_path = os.path.join(os.path.dirname(__file__), ".env")
    load_dotenv(dotenv_path)

# ==========================================
# CONFIGURAÇÃO DE ESTÉTICA CLEAN
# ==========================================
st.set_page_config(page_title="Gestão de OS - CRM", layout="wide", initial_sidebar_state="expanded")

def check_success_message():
    if 'sucesso' in st.session_state:
        st.success(st.session_state['sucesso'])
        del st.session_state['sucesso']

# ==========================================
# CONEXÃO COM SUPABASE (PostgreSQL)
# ==========================================
SUPABASE_URL = None
SUPABASE_KEY = None
try:
    SUPABASE_URL = st.secrets.get("SUPABASE_URL")
    SUPABASE_KEY = st.secrets.get("SUPABASE_KEY")
except Exception:
    pass

if not SUPABASE_URL:
    SUPABASE_URL = os.getenv("SUPABASE_URL")
if not SUPABASE_KEY:
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("Defina SUPABASE_URL e SUPABASE_KEY como variáveis de ambiente ou em Streamlit Secrets antes de executar este app.")
    if load_dotenv is not None:
        st.error(f"Caminho .env esperado: {dotenv_path}")
    st.error(f"SUPABASE_URL={SUPABASE_URL!r}, SUPABASE_KEY definida: {bool(SUPABASE_KEY)}")
    st.stop()

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def init_db():
    # Garante que exista uma configuração padrão
    try:
        res = supabase.table("config").select("*").limit(1).execute()
    except Exception as e:
        msg = str(e)
        if "Could not find the table" in msg or "PGRST205" in msg:
            st.error("Tabela necessária não encontrada no Supabase. Crie as tabelas esperadas (config, clientes, ordens_servico, agendamentos).")
            st.error("Use o SQL recomendado no painel Supabase -> SQL Editor.")
        else:
            st.error("Erro ao conectar ao Supabase. Verifique SUPABASE_URL/SUPABASE_KEY e se o serviço está ativo.")
            st.error(f"SUPABASE_URL: {SUPABASE_URL!r}")
            st.error(f"SUPABASE_KEY definida: {bool(SUPABASE_KEY)}")
            st.error(f"Erro original: {type(e).__name__}: {e}")
        st.stop()

    if not getattr(res, 'data', None):
        supabase.table("config").insert({"valor_hora": 150.0, "imposto_perc": 10.0}).execute()

init_db()


def get_agendamento_by_id(ag_id):
    try:
        res = supabase.table("agendamentos").select("*").eq("id", ag_id).single().execute()
    except Exception:
        return None
    return getattr(res, 'data', None)

# ==========================================
# FUNÇÕES AUXILIARES E REGRAS DE NEGÓCIO
# ==========================================
def calcular_minutos_cobrados(minutos_reais):
    """Retorna os minutos faturados.

    O faturamento é feito em blocos de 15 minutos (cobrança mínima de 15m).
    Ex:
      - 1..15m => 15m
      - 16..30m => 30m
      - 31..45m => 45m
      - 46..60m => 60m

    Isso evita cobranças fracionadas e deixa o resultado consistente.
    """
    if minutos_reais <= 0:
        return 0
    return int(math.ceil(minutos_reais / 15.0) * 15)


def calcular_minutos_reais(hora_inicio, hora_fim, pausa=0):
    """Calcula a duração em minutos entre dois horários.

    - Aceita `datetime.time` para início/fim.
    - Se `hora_fim` for anterior a `hora_inicio`, assume que passou da meia-noite.
    - Subtrai o tempo de pausa (em minutos).
    - Garante que o valor retornado não seja negativo.
    """
    start_minutes = hora_inicio.hour * 60 + hora_inicio.minute + hora_inicio.second / 60.0
    end_minutes = hora_fim.hour * 60 + hora_fim.minute + hora_fim.second / 60.0

    diff = end_minutes - start_minutes
    if diff < 0:
        diff += 24 * 60

    diff -= pausa
    return max(diff, 0)


def get_config():
    try:
        res = supabase.table("config").select("*").limit(1).execute()
    except Exception as e:
        st.error("Erro ao carregar configuração do Supabase. Verifique se a tabela 'config' existe.")
        st.error(f"Erro original: {type(e).__name__}: {e}")
        st.stop()

    return res.data[0] if getattr(res, 'data', None) else {"valor_hora": 150.0, "imposto_perc": 10.0}


def get_valor_imposto(config):
    return float(config.get('imposto_valor', config.get('imposto_perc', 0.0)) or 0.0)


def calcular_valor_liquido(valor_bruto, imposto_reais):
    return max(float(valor_bruto) - float(imposto_reais), 0.0)


def formatar_competencia(competencia):
    return datetime.strptime(competencia, '%Y-%m').strftime('%m/%Y')


def get_clientes_df():
    try:
        res = supabase.table("clientes").select("id, nome, empresa_mae_id").order("nome", desc=False).execute()
    except Exception as e:
        st.error("Erro ao carregar clientes do Supabase. Verifique se a tabela 'clientes' existe.")
        st.error(f"Erro original: {type(e).__name__}: {e}")
        st.stop()

    df = pd.DataFrame(getattr(res, 'data', []) or [])
    if not df.empty:
        # Supabase pode retornar números como strings, então garantimos tipos consistentes para merge
        df['id'] = pd.to_numeric(df['id'], errors='coerce').astype('Int64')
        if 'empresa_mae_id' in df.columns:
            df['empresa_mae_id'] = pd.to_numeric(df['empresa_mae_id'], errors='coerce').astype('Int64')
    return df


def get_agendamentos_df(status=None):
    try:
        query = supabase.table("agendamentos").select("*").order("data_agendada", desc=False)
        if status:
            query = query.eq("status", status)
        res = query.execute()
    except Exception as e:
        st.error("Erro ao carregar agendamentos do Supabase. Verifique se a tabela 'agendamentos' existe.")
        st.error(f"Erro original: {type(e).__name__}: {e}")
        st.stop()

    return pd.DataFrame(getattr(res, 'data', []) or [])


def get_ordens_servico_df():
    try:
        res = supabase.table("ordens_servico").select("*").order("data_os", desc=True).order("id", desc=True).execute()
    except Exception as e:
        st.error("Erro ao carregar ordens de serviço do Supabase. Verifique se a tabela 'ordens_servico' existe.")
        st.error(f"Erro original: {type(e).__name__}: {e}")
        st.stop()

    data = getattr(res, 'data', []) or []
    df = pd.DataFrame(data)
    if df.empty:
        # Garante colunas mínimas para evitar KeyError em código que espera essas colunas
        return pd.DataFrame(columns=['id', 'cliente_id', 'solicitante', 'tipo', 'data_os', 'minutos_reais', 'minutos_cobrados', 'historico'])

    # Normaliza tipos para evitar np.int64 em JSON
    for col in ['id', 'cliente_id', 'minutos_reais', 'minutos_cobrados']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')

    clientes = get_clientes_df()
    if not clientes.empty and 'cliente_id' in df.columns:
        df = df.merge(clientes[['id', 'nome']], left_on='cliente_id', right_on='id', how='left', suffixes=('', '_cliente'))
        # Garante coluna usada em vários locais
        df['Cliente'] = df.get('nome', '')

    # Garantir colunas mínimas esperadas pelo restante do app
    if 'nome' not in df.columns:
        df['nome'] = ''
    return df


def get_os_by_id(os_id):
    try:
        res = supabase.table("ordens_servico").select("*").eq("id", os_id).single().execute()
    except Exception:
        return None
    return getattr(res, 'data', None)


def get_cliente_by_id(cliente_id):
    try:
        res = supabase.table("clientes").select("*").eq("id", cliente_id).single().execute()
    except Exception:
        return None
    return getattr(res, 'data', None)

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
    st.title("📊 Visão Geral")

    df_os = get_ordens_servico_df()
    config = get_config()
    imposto_fixo = get_valor_imposto(config)

    if df_os.empty:
        st.info("Nenhuma Ordem de Serviço lançada até o momento.")
    else:
        df_os['data_os'] = pd.to_datetime(df_os['data_os'])
        meses_disponiveis = sorted(df_os['data_os'].dt.strftime('%Y-%m').unique().tolist(), reverse=True)
        mes_atual = datetime.now().strftime('%Y-%m')
        indice_padrao = meses_disponiveis.index(mes_atual) if mes_atual in meses_disponiveis else 0
        mes_selecionado = st.selectbox(
            "Competência",
            options=meses_disponiveis,
            index=indice_padrao,
            format_func=formatar_competencia,
        )

        df_os = df_os[df_os['data_os'].dt.strftime('%Y-%m') == mes_selecionado].copy()
        df_os['data_os'] = df_os['data_os'].dt.strftime('%d/%m/%Y')  # Formatando datas DD/MM/AAAA
        total_minutos = df_os['minutos_cobrados'].sum()
        valor_bruto_total = (total_minutos / 60.0) * config['valor_hora']
        valor_liquido_total = calcular_valor_liquido(valor_bruto_total, imposto_fixo)
        cliente_campeao = df_os.groupby('Cliente')['minutos_cobrados'].sum().idxmax()

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("⏱️ Horas Mês", formatar_horas(total_minutos))
        col2.metric("💰 Bruto", f"R$ {valor_bruto_total:,.2f}")
        col3.metric("💵 Líquido", f"R$ {valor_liquido_total:,.2f}")
        col4.metric("🏆 Top Cliente", cliente_campeao)
        st.caption(f"Imposto fixo (DAS): R$ {imposto_fixo:,.2f}")

        st.write("---")
        aba1, aba2, aba3 = st.tabs(["📋 Resumo por Cliente", "📈 Gráficos", "🔍 Extrato Detalhado Mensal"])

        with aba1:
            df_ag = df_os.groupby('Cliente')['minutos_cobrados'].sum().reset_index()
            df_ag['Horas Totais'] = df_ag['minutos_cobrados'].apply(formatar_horas)
            df_ag['Faturamento Bruto'] = (df_ag['minutos_cobrados'] / 60.0) * config['valor_hora']
            total_bruto_clientes = df_ag['Faturamento Bruto'].sum()
            imposto_rateado = min(imposto_fixo, total_bruto_clientes)
            if total_bruto_clientes > 0 and imposto_rateado > 0:
                df_ag['Imposto Rateado'] = (df_ag['Faturamento Bruto'] / total_bruto_clientes) * imposto_rateado
            else:
                df_ag['Imposto Rateado'] = 0.0
            df_ag['Faturamento Líquido'] = (df_ag['Faturamento Bruto'] - df_ag['Imposto Rateado']).clip(lower=0)
            df_display = df_ag[['Cliente', 'Horas Totais', 'Faturamento Bruto', 'Faturamento Líquido']].copy()
            st.dataframe(df_display.style.format({'Faturamento Bruto': 'R$ {:.2f}', 'Faturamento Líquido': 'R$ {:.2f}'}), use_container_width=True, hide_index=True)
            st.caption("No resumo por cliente, o imposto fixo do mês é rateado proporcionalmente ao faturamento bruto.")

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

    clientes = get_clientes_df()

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
                    cliente_id_val = int(opcoes_clientes[cli_sel])
                    supabase.table("agendamentos").insert({
                        "cliente_id": cliente_id_val,
                        "titulo": titulo,
                        "data_agendada": data_ag.strftime('%Y-%m-%d'),
                        "descricao": desc,
                        "status": "Pendente",
                    }).execute()
                    st.session_state['sucesso'] = "Agendamento salvo com sucesso!"
                    st.rerun()

        with aba_pend:
            df_pend = get_agendamentos_df(status="Pendente")
            if df_pend.empty:
                st.info("Nenhum agendamento pendente.")
            else:
                df_pend = df_pend.merge(
                    clientes[['id', 'nome']],
                    left_on='cliente_id',
                    right_on='id',
                    how='left',
                    suffixes=('', '_cliente'),
                )
                df_pend.rename(columns={'nome': 'Cliente'}, inplace=True)
                df_pend['data_agendada'] = pd.to_datetime(df_pend['data_agendada']).dt.strftime('%d/%m/%Y')
                st.dataframe(df_pend[['data_agendada', 'Cliente', 'titulo', 'descricao']], use_container_width=True, hide_index=True)

                st.markdown("#### 🚀 Transformar Agendamento em OS")
                opcoes_pend = {
                    f"{row['data_agendada']} | {row['Cliente']} - {row['titulo']}": (
                        row.get('id') or row.get('id_x') or row.get('id_y')
                    )
                    for _, row in df_pend.iterrows()
                }
                ag_selecionado = st.selectbox("Selecione o Agendamento para Finalizar", list(opcoes_pend.keys()))

                if ag_selecionado:
                    ag_id = opcoes_pend[ag_selecionado]
                    ag_info = get_agendamento_by_id(ag_id)

                    with st.form("form_gerar_os"):
                        st.info("Informe o tempo total do serviço para gerar a OS (múltiplo de 15 minutos).")
                        duracao = st.number_input("Tempo (min)", min_value=15, value=15, step=15)

                        min_reais_preview = float(duracao)
                        min_cobrados_preview = calcular_minutos_cobrados(min_reais_preview)

                        solicitante = st.text_input("Solicitante")
                        tipo = st.radio("Tipo", ["Home Office", "Presencial"], horizontal=True)
                        hist = st.text_area("Histórico Final da OS", value=f"Ref. Agendamento: {ag_info['titulo']}\n{ag_info['descricao']}")

                        if st.form_submit_button("Gerar OS e Concluir Agendamento", type="primary"):
                            min_reais = float(duracao)
                            if min_reais > 0:
                                min_cobrados = calcular_minutos_cobrados(min_reais)

                                supabase.table("ordens_servico").insert({
                                    "cliente_id": int(ag_info['cliente_id']),
                                    "solicitante": solicitante,
                                    "tipo": tipo,
                                    "data_os": date.today().strftime('%Y-%m-%d'),
                                    "minutos_reais": int(round(min_reais)),
                                    "minutos_cobrados": int(min_cobrados),
                                    "historico": hist,
                                }).execute()
                                supabase.table("agendamentos").update({"status": "Finalizado"}).eq("id", ag_id).execute()
                                st.session_state['sucesso'] = "OS Gerada e Agendamento Finalizado!"
                                st.rerun()
                            else:
                                st.error("A hora final deve ser maior que a inicial (ou a pausa é maior que a duração).")

        with aba_fin:
            df_fin = get_agendamentos_df(status="Finalizado")
            if not df_fin.empty:
                df_fin = df_fin.merge(clientes[['id', 'nome']], left_on='cliente_id', right_on='id', how='left')
                df_fin.rename(columns={'nome': 'Cliente'}, inplace=True)
                df_fin['data_agendada'] = pd.to_datetime(df_fin['data_agendada']).dt.strftime('%d/%m/%Y')
                st.dataframe(df_fin[['data_agendada', 'Cliente', 'titulo']], use_container_width=True, hide_index=True)
            else:
                st.info("Nenhum agendamento finalizado.")

# ==========================================
# PÁGINA 3: ORDENS DE SERVIÇO
# ==========================================
elif menu == "🛠️ Ordens de Serviço":
    st.title("🛠️ Gestão de Ordens de Serviço")
    check_success_message()

    clientes = get_clientes_df()

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
                    duracao = st.number_input("Tempo (min)", min_value=15, value=15, step=15)

                    min_reais_preview = float(duracao)
                    min_cobrados_preview = calcular_minutos_cobrados(min_reais_preview)
                    hist = st.text_area("Descrição")
                    if st.form_submit_button("Lançar OS", type="primary", use_container_width=True):
                        min_reais = float(duracao)
                        if min_reais > 0:
                            min_cobrados = calcular_minutos_cobrados(min_reais)
                            supabase.table("ordens_servico").insert({
                                "cliente_id": int(opcoes_clientes[cli_sel]),
                                "solicitante": solic,
                                "tipo": tipo_at,
                                "data_os": data_os.strftime('%Y-%m-%d'),
                                "minutos_reais": int(round(min_reais)),
                                "minutos_cobrados": int(min_cobrados),
                                "historico": hist,
                            }).execute()
                            st.session_state['sucesso'] = f"OS Lançada! Faturado: {formatar_horas(min_cobrados)}"
                            st.rerun()
                        else:
                            st.error("A hora final deve ser maior que a inicial (ou a pausa é maior que a duração).")

            with col_recentes:
                st.markdown("##### 🕒 Últimas 5 OS")
                df_rec = get_ordens_servico_df().head(5)
                if not df_rec.empty:
                    df_rec['Tempo'] = df_rec['minutos_cobrados'].apply(formatar_horas)
                    df_rec['Data'] = pd.to_datetime(df_rec['data_os']).dt.strftime('%d/%m/%Y')
                    st.dataframe(df_rec[['Data', 'nome', 'Tempo']], use_container_width=True, hide_index=True)
                else:
                    st.info("Nenhuma OS lançada.")

        with aba_historico:
            st.markdown("Selecione uma OS existente para visualizar, gerar PDF, editar ou excluir.")
            todas_os = get_ordens_servico_df()[['id', 'nome', 'data_os']].copy()

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
                        os_info = get_os_by_id(id_os)
                        if os_info:
                            cliente = get_cliente_by_id(os_info['cliente_id'])
                            os_info['cliente_nome'] = cliente['nome'] if cliente else ''

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
                                    # Garantir tipos nativos do Python para serialização JSON
                                    id_novo_cliente = int(clientes[clientes['nome'] == cli_edit]['id'].values[0])
                                    minutos_cobrados = int(min_edit)
                                    os_id = int(os_info['id'])

                                    supabase.table("ordens_servico").update({
                                        "cliente_id": id_novo_cliente,
                                        "solicitante": solic_edit,
                                        "tipo": tipo_edit,
                                        "data_os": data_edit.strftime('%Y-%m-%d'),
                                        "minutos_cobrados": minutos_cobrados,
                                        "historico": hist_edit,
                                    }).eq("id", os_id).execute()
                                    st.session_state['sucesso'] = "OS Atualizada com sucesso!"
                                    st.rerun()
                                    
                                if excluir:
                                    supabase.table("ordens_servico").delete().eq("id", int(os_info['id'])).execute()
                                    st.session_state['sucesso'] = "OS Excluída com sucesso!"
                                    st.rerun()
            else:
                st.info("Nenhuma OS registrada no banco de dados.")

# ==========================================
# PÁGINA 4: CLIENTES
# ==========================================
elif menu == "👥 Meus Clientes":
    st.title("👥 Gestão de Clientes")
    check_success_message()

    clientes_ex = get_clientes_df()

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
                    empresa_mae_id_val = opcoes_mae[empresa_mae]
                    if empresa_mae_id_val is not None:
                        empresa_mae_id_val = int(empresa_mae_id_val)

                    supabase.table("clientes").insert({
                        "nome": nome_cliente,
                        "empresa_mae_id": empresa_mae_id_val,
                    }).execute()
                    st.session_state['sucesso'] = f"Cliente '{nome_cliente}' salvo!"
                    st.rerun()

        with col2:
            if clientes_ex.empty:
                st.info("Nenhum cliente cadastrado ainda.")
            else:
                df_lista_cli = clientes_ex.merge(
                    clientes_ex[['id', 'nome']],
                    left_on='empresa_mae_id',
                    right_on='id',
                    how='left',
                    suffixes=('', '_mae')
                )
                df_lista_cli['Vinculada à'] = df_lista_cli['nome_mae'].fillna('MATRIZ')
                df_lista_cli = df_lista_cli[['nome', 'Vinculada à']].rename(columns={'nome': 'Empresa'})
                st.dataframe(df_lista_cli, use_container_width=True, hide_index=True)

    with aba2:
        if not clientes_ex.empty:
            cli_ids = clientes_ex['id'].tolist()
            cli_nomes = clientes_ex['nome'].tolist()
            sel_id = st.selectbox("Selecione o cliente", cli_ids, format_func=lambda i: cli_nomes[cli_ids.index(i)])
            cli_info = get_cliente_by_id(sel_id)

            if cli_info:
                with st.form("form_edicao_cliente"):
                    n_edit = st.text_input("Nome", value=cli_info['nome'])
                    op_edit = {"Nenhuma (É a Empresa Mãe)": None}
                    for idx, nm in zip(clientes_ex['id'], clientes_ex['nome']):
                        if idx != cli_info['id']:
                            op_edit[nm] = idx

                    m_keys, m_vals = list(op_edit.keys()), list(op_edit.values())
                    idx_default = m_vals.index(cli_info['empresa_mae_id']) if cli_info['empresa_mae_id'] in m_vals else 0
                    mae_edit = st.selectbox("Empresa Mãe", m_keys, index=idx_default)

                    b1, b2 = st.columns(2)
                    if b1.form_submit_button("Atualizar Cliente", type="primary", use_container_width=True):
                        empresa_mae_id_val = op_edit[mae_edit]
                        if empresa_mae_id_val is not None:
                            empresa_mae_id_val = int(empresa_mae_id_val)

                        supabase.table("clientes").update({
                            "nome": n_edit,
                            "empresa_mae_id": empresa_mae_id_val,
                        }).eq("id", cli_info['id']).execute()
                        st.session_state['sucesso'] = "Cliente atualizado!"
                        st.rerun()

                    if b2.form_submit_button("🗑️ Excluir Cliente", use_container_width=True):
                        supabase.table("clientes").update({"empresa_mae_id": None}).eq("empresa_mae_id", cli_info['id']).execute()
                        supabase.table("clientes").delete().eq("id", cli_info['id']).execute()
                        st.session_state['sucesso'] = "Cliente excluído!"
                        st.rerun()

# ==========================================
# PÁGINA 5: CONFIGURAÇÕES
# ==========================================
elif menu == "⚙️ Configurações":
    st.title("⚙️ Configurações do Sistema")
    check_success_message()
    config = get_config()
    imposto_atual = get_valor_imposto(config)
    
    col1, col2 = st.columns([1, 2])
    with col1:
        with st.form("form_config"):
            valor_h = st.number_input("Valor Hora (R$)", min_value=0.0, value=config['valor_hora'], step=10.0)
            imposto = st.number_input("Imposto Fixo (R$)", min_value=0.0, value=imposto_atual, step=10.0)
            if st.form_submit_button("Atualizar Valores", type="primary", use_container_width=True):
                supabase.table("config").update({
                    "valor_hora": valor_h,
                    "imposto_perc": imposto,
                }).eq("id", 1).execute()
                st.session_state['sucesso'] = "Configurações atualizadas!"
                st.rerun()