#!/usr/bin/env python3
"""
Dashboard Ancestral - Script de Atualização Diária
Puxa dados de Meta API + Google Sheets, calcula CAC, gera dados.json
"""

import requests
import json
from datetime import datetime, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import sys

# ========== CONFIGURAÇÕES ==========
META_TOKEN = os.environ.get('META_TOKEN')
ACCOUNT_ID = '2509831302750231'
CAMPAIGN_ID = '120246923151460196'
GOOGLE_SHEETS_ID = '1NZmtve7hTQXRvULldU7C-RQYp2DMX_Kse9kM_zu9Ufk'

# Credenciais Google (armazenadas em GitHub Secrets como JSON)
GOOGLE_CREDS_JSON = os.environ.get('GOOGLE_CREDS_JSON')

# ========== FUNÇÕES UTILITÁRIAS ==========

def get_meta_insights(time_range_start, time_range_end):
    """Puxa dados de performance da campanha Meta"""
    url = f'https://graph.instagram.com/v18.0/act_{ACCOUNT_ID}/campaigns'
    params = {
        'access_token': META_TOKEN,
        'fields': 'name,id,status,insights.time_range({{"start":"{}","end":"{}"}}).time_increment(7){{spend,actions,action_values,impressions,clicks}}'.format(
            time_range_start, time_range_end
        ),
        'limit': 100
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Erro ao buscar insights da Meta: {e}")
        return None

def get_ad_set_breakdown(time_range_start, time_range_end):
    """Puxa breakdown por ad set"""
    url = f'https://graph.instagram.com/v18.0/{CAMPAIGN_ID}/ads'
    params = {
        'access_token': META_TOKEN,
        'fields': 'name,adset_id,insights.time_range({{"start":"{}","end":"{}"}}).time_increment(1){{spend,actions,clicks,impressions}}'.format(
            time_range_start, time_range_end
        ),
        'limit': 100
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Erro ao buscar ad sets: {e}")
        return None

def get_google_sheets_data():
    """Autentica e puxa dados da planilha Google Sheets"""
    try:
        creds_dict = json.loads(GOOGLE_CREDS_JSON)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(
            creds_dict,
            scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
        )
        client = gspread.authorize(creds)
        sheet = client.open_by_key(GOOGLE_SHEETS_ID)
        
        # Abre a aba "Funil de Leads"
        funnel_sheet = sheet.worksheet('Funil de Leads')
        all_records = funnel_sheet.get_all_values()
        
        return {
            'funnel_data': all_records,
            'success': True
        }
    except Exception as e:
        print(f"Erro ao acessar Google Sheets: {e}")
        return {
            'funnel_data': [],
            'success': False
        }

def parse_funnel_data(all_records):
    """Processa dados do funil de leads"""
    if not all_records or len(all_records) < 4:
        return {
            'total_leads': 0,
            'leads_conversando': 0,
            'leads_perdidos': 0,
            'leads_matriculados': 0,
            'gender_breakdown': {'Masculino': 0, 'Feminino': 0},
            'temperature_breakdown': {}
        }
    
    # Encontra o header (row 3 = index 3)
    header = None
    data_start_row = None
    for i, row in enumerate(all_records):
        if i >= 3 and any('data' in str(cell).lower() for cell in row):
            header = row
            data_start_row = i + 1
            break
    
    if not header or data_start_row is None:
        return {
            'total_leads': 0,
            'leads_conversando': 0,
            'leads_perdidos': 0,
            'leads_matriculados': 0,
            'gender_breakdown': {'Masculino': 0, 'Feminino': 0},
            'temperature_breakdown': {}
        }
    
    # Encontra índices das colunas
    try:
        name_idx = next(i for i, h in enumerate(header) if 'nome' in h.lower())
        gender_idx = next(i for i, h in enumerate(header) if 'gênero' in h.lower() or 'genero' in h.lower())
        temp_idx = next(i for i, h in enumerate(header) if 'temperatura' in h.lower())
        status_idx = next(i for i, h in enumerate(header) if 'status' in h.lower() or 'funil' in h.lower())
    except StopIteration:
        return {
            'total_leads': 0,
            'leads_conversando': 0,
            'leads_perdidos': 0,
            'leads_matriculados': 0,
            'gender_breakdown': {'Masculino': 0, 'Feminino': 0},
            'temperature_breakdown': {}
        }
    
    leads = all_records[data_start_row:]
    total = len(leads)
    conversando = sum(1 for row in leads if status_idx < len(row) and 'conversando' in str(row[status_idx]).lower())
    perdidos = sum(1 for row in leads if status_idx < len(row) and 'perdido' in str(row[status_idx]).lower())
    matriculados = sum(1 for row in leads if status_idx < len(row) and ('matricul' in str(row[status_idx]).lower() or 'compareceu' in str(row[status_idx]).lower() or 'agendou' in str(row[status_idx]).lower()))
    
    gender_breakdown = {'Masculino': 0, 'Feminino': 0}
    for row in leads:
        if gender_idx < len(row):
            gender = str(row[gender_idx]).strip().lower()
            if 'masculino' in gender or 'm' == gender:
                gender_breakdown['Masculino'] += 1
            elif 'feminino' in gender or 'f' == gender:
                gender_breakdown['Feminino'] += 1
    
    temperature_breakdown = {}
    for row in leads:
        if temp_idx < len(row):
            temp = str(row[temp_idx]).strip()
            temperature_breakdown[temp] = temperature_breakdown.get(temp, 0) + 1
    
    return {
        'total_leads': total,
        'leads_conversando': conversando,
        'leads_perdidos': perdidos,
        'leads_matriculados': matriculados,
        'gender_breakdown': gender_breakdown,
        'temperature_breakdown': temperature_breakdown
    }

def calculate_cac(total_gasto, leads_conversando, leads_matriculados):
    """Calcula CAC de duas formas"""
    cac_leads_conversando = total_gasto / leads_conversando if leads_conversando > 0 else 0
    cac_matriculados = total_gasto / leads_matriculados if leads_matriculados > 0 else 0
    
    return {
        'cac_leads_conversando': round(cac_leads_conversando, 2),
        'cac_matriculados': round(cac_matriculados, 2)
    }

def get_weekly_data(insights_data):
    """Extrai dados semanais da resposta de insights"""
    weekly_data = []
    
    try:
        if 'data' in insights_data and len(insights_data['data']) > 0:
            campaign = insights_data['data'][0]
            if 'insights' in campaign and 'data' in campaign['insights']:
                for week in campaign['insights']['data']:
                    date_start = week.get('date_start', '')
                    spend = 0
                    conversas = 0
                    
                    for action in week.get('actions', []):
                        if action.get('action_type') == 'onsite_conversion.messaging_conversation_started_7d':
                            conversas = action.get('value', 0)
                    
                    spend = float(week.get('spend', 0))
                    
                    if spend > 0:
                        cpl = spend / conversas if conversas > 0 else 0
                        weekly_data.append({
                            'date': date_start,
                            'spend': round(spend, 2),
                            'conversas': int(conversas),
                            'cpl': round(cpl, 2)
                        })
    except Exception as e:
        print(f"Erro ao processar dados semanais: {e}")
    
    return weekly_data

def main():
    """Execução principal"""
    print("[INFO] Iniciando atualização do dashboard...")
    
    # Data range: último mês
    end_date = datetime.now().date()
    start_date = (end_date - timedelta(days=30)).isoformat()
    end_date_str = end_date.isoformat()
    
    print(f"[INFO] Período: {start_date} a {end_date_str}")
    
    # Puxa dados da Meta
    print("[INFO] Buscando dados da Meta API...")
    meta_data = get_meta_insights(start_date, end_date_str)
    
    # Puxa dados do Google Sheets
    print("[INFO] Buscando dados da Google Sheets...")
    sheets_response = get_google_sheets_data()
    funnel_data = parse_funnel_data(sheets_response['funnel_data'])
    
    # Calcula métricas gerais
    total_spend = 0
    total_conversas = 0
    
    if meta_data and 'data' in meta_data and len(meta_data['data']) > 0:
        campaign = meta_data['data'][0]
        if 'insights' in campaign and 'data' in campaign['insights']:
            for week in campaign['insights']['data']:
                total_spend += float(week.get('spend', 0))
                for action in week.get('actions', []):
                    if action.get('action_type') == 'onsite_conversion.messaging_conversation_started_7d':
                        total_conversas += action.get('value', 0)
    
    # Calcula CAC
    cac_metrics = calculate_cac(total_spend, funnel_data['leads_conversando'], funnel_data['leads_matriculados'])
    
    # Extrai dados semanais
    weekly_data = []
    if meta_data:
        weekly_data = get_weekly_data(meta_data)
    
    # Monta JSON final
    dashboard_data = {
        'generated_at': datetime.now().isoformat(),
        'period': {
            'start': start_date,
            'end': end_date_str
        },
        'meta_metrics': {
            'total_spend': round(total_spend, 2),
            'total_conversas': int(total_conversas),
            'average_cpl': round(total_spend / total_conversas, 2) if total_conversas > 0 else 0,
            'target_cpl': 11.00
        },
        'funnel_metrics': {
            'total_leads': funnel_data['total_leads'],
            'leads_conversando': funnel_data['leads_conversando'],
            'leads_perdidos': funnel_data['leads_perdidos'],
            'leads_matriculados': funnel_data['leads_matriculados'],
            'gender_breakdown': funnel_data['gender_breakdown'],
            'temperature_breakdown': funnel_data['temperature_breakdown']
        },
        'cac_metrics': cac_metrics,
        'weekly_data': weekly_data
    }
    
    # Salva JSON
    output_path = 'dados.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(dashboard_data, f, ensure_ascii=False, indent=2)
    
    print(f"[✓] Dashboard atualizado: {output_path}")
    print(f"    - Gasto total: R${dashboard_data['meta_metrics']['total_spend']}")
    print(f"    - Conversas: {dashboard_data['meta_metrics']['total_conversas']}")
    print(f"    - CPL médio: R${dashboard_data['meta_metrics']['average_cpl']}")
    print(f"    - CAC (Conversando): R${cac_metrics['cac_leads_conversando']}")
    print(f"    - CAC (Matriculados): R${cac_metrics['cac_matriculados']}")

if __name__ == '__main__':
    if not META_TOKEN:
        print("[ERRO] META_TOKEN não configurado em GitHub Secrets")
        sys.exit(1)
    if not GOOGLE_CREDS_JSON:
        print("[ERRO] GOOGLE_CREDS_JSON não configurado em GitHub Secrets")
        sys.exit(1)
    
    main()
