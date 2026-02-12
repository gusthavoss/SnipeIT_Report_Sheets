#!/usr/bin/env python3
"""
=============================================================================
EXPORTADOR DE ASSETS - SNIPE-IT → GOOGLE SHEETS
=============================================================================

O QUE FAZ:
  Exporta todos os assets do inventário (Snipe-IT) para uma planilha do 
  Google Sheets automaticamente, no mesmo formato do Custom Report.

COMO FUNCIONA:
  1. Busca todos os assets usando a API do Snipe-IT (endpoint /hardware)
  2. Processa cada asset extraindo ~85 campos (básicos + custom fields)
  3. Monta as linhas no formato exato do Custom Report do Snipe-IT
  4. Conecta no Google Sheets usando Service Account
  5. Deleta aba antiga "Report Principal"
  6. Cria nova aba com data atual: "Report Principal - DD/MM/YYYY HH:MM"
  7. Envia todos os dados em batches de 5000 linhas

POR QUE NÃO USA O ENDPOINT DE CUSTOM REPORT?
  A API do Snipe-IT não tem endpoint de custom report. Então:
  - Pegamos os dados brutos do endpoint /hardware
  - Extraímos e organizamos os campos manualmente
  - Resultado final é idêntico ao Custom Report da interface web

REQUISITOS:
  - Token da API do Snipe-IT (configurado no dd_config.py)
  - Service Account do Google Cloud com acesso ao Sheets
  - Arquivo google_credentials.json
  - Planilha compartilhada com o email da Service Account

USO:
  python3 generate_custom_report_gsheets.py

=============================================================================
"""
import json
import sys
import os
from datetime import datetime, timedelta
import schedule
import time
import gspread
import logging

sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from dd_config import DD_CFG
import requests
import urllib3
from google.oauth2.service_account import Credentials

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Credenciais e URLs
SNIPEIT_TOKEN = DD_CFG['dd_itoken']
SNIPEIT_URL = DD_CFG['inv_url']
PLANILHA_URL = "Link da Planilha"
GOOGLE_CREDENTIALS = "google_credentials.json"


def pegar_valor(dicionario, *chaves, padrao=''):
    """Navega em dicts aninhados tipo: asset['model']['name'] sem dar erro"""
    for chave in chaves:
        if dicionario is None:
            return padrao
        if isinstance(dicionario, dict):
            dicionario = dicionario.get(chave)
        else:
            return padrao
    return dicionario if dicionario is not None else padrao


def formatar_data(data):
    """Converte data do Snipe-IT (JSON) em texto"""
    if not data:
        return ''
    if isinstance(data, dict):
        return data.get('formatted', '') or data.get('date', '')
    return str(data)


def pegar_custom_field(campos, nome):
    """Extrai custom fields tipo 'CPU', 'RAM', 'Leasing Date'"""
    if not campos or not isinstance(campos, dict):
        return ''
    campo = campos.get(nome, {})
    if isinstance(campo, dict):
        return campo.get('value', '')
    return str(campo) if campo else ''


def montar_linha_asset(asset):
    """Transforma JSON do asset em lista com 85 colunas (mesma ordem do Snipe-IT)"""
    
    # Info do usuário que está com o asset
    usuario = asset.get('assigned_to', {}) or {}
    username = pegar_valor(usuario, 'username')
    tipo_usuario = pegar_valor(usuario, 'type')
    matricula = pegar_valor(usuario, 'employee_num')
    gestor = pegar_valor(usuario, 'manager', 'name')
    area = pegar_valor(usuario, 'department', 'name')
    
    # Localização atual
    local = asset.get('location', {}) or {}
    local_nome = pegar_valor(local, 'name')
    local_end1 = pegar_valor(local, 'address')
    local_end2 = pegar_valor(local, 'address2')
    local_cidade = pegar_valor(local, 'city')
    local_estado = pegar_valor(local, 'state')
    local_pais = pegar_valor(local, 'country')
    local_cep = pegar_valor(local, 'zip')
    
    # Localização padrão
    local_padrao = asset.get('rtd_location', {}) or {}
    padrao_nome = pegar_valor(local_padrao, 'name')
    padrao_end1 = pegar_valor(local_padrao, 'address')
    padrao_end2 = pegar_valor(local_padrao, 'address2')
    padrao_cidade = pegar_valor(local_padrao, 'city')
    padrao_estado = pegar_valor(local_padrao, 'state')
    padrao_pais = pegar_valor(local_padrao, 'country')
    padrao_cep = pegar_valor(local_padrao, 'zip')
    
    # Campos customizados
    cf = asset.get('custom_fields', {}) or {}
    
    # Monta a linha (mesma ordem do Snipe-IT)
    return [
        asset.get('id', ''),
        pegar_valor(asset, 'company', 'name'),
        asset.get('name', ''),
        asset.get('asset_tag', ''),
        pegar_valor(asset, 'model', 'name'),
        pegar_valor(asset, 'model', 'model_number'),
        pegar_valor(asset, 'category', 'name'),
        pegar_valor(asset, 'manufacturer', 'name'),
        asset.get('serial', ''),
        formatar_data(asset.get('purchase_date')),
        asset.get('purchase_cost', ''),
        asset.get('eol', ''),
        asset.get('warranty_months', ''),
        formatar_data(asset.get('warranty_expires')),
        asset.get('book_value', '0.00'),
        '', '',  # Diff, Fully Depreciated
        asset.get('order_number', ''),
        pegar_valor(asset, 'supplier', 'name'),
        local_nome, local_end1, local_end2, local_cidade, local_estado, local_pais, local_cep,
        padrao_nome, padrao_end1, padrao_end2, padrao_cidade, padrao_estado, padrao_pais, padrao_cep,
        username, tipo_usuario, username, matricula, gestor, area,
        pegar_valor(usuario, 'jobtitle'),
        pegar_valor(usuario, 'phone'),
        '', '', '', pegar_valor(usuario, 'country'), '',
        pegar_valor(asset, 'status_label', 'name'),
        formatar_data(asset.get('last_checkout')),
        formatar_data(asset.get('last_checkin')),
        formatar_data(asset.get('expected_checkin')),
        formatar_data(asset.get('created_at')),
        formatar_data(asset.get('updated_at')),
        'Yes' if asset.get('deleted_at') else '',
        formatar_data(asset.get('last_audit_date')),
        formatar_data(asset.get('next_audit_date')),
        asset.get('notes', ''),
        f"https://Link SnipeIT/hardware/{asset.get('id', '')}",
        pegar_custom_field(cf, 'Nota Fiscal'),
        pegar_custom_field(cf, 'third_party'),
        pegar_custom_field(cf, 'Link NF'),
        pegar_custom_field(cf, 'Leasing Start Date'),
        pegar_custom_field(cf, 'Leasing End Date'),
        pegar_custom_field(cf, 'Validated'),
        pegar_custom_field(cf, 'SIM Card'),
        pegar_custom_field(cf, 'Termo de Responsabilidade Enviado'),
        pegar_custom_field(cf, 'Termo de Responsabilidade Assinado'),
        pegar_custom_field(cf, 'No de Factura'),
        pegar_custom_field(cf, 'Repair Reason'),
        pegar_custom_field(cf, 'Warranty Expiration Date'),
        pegar_custom_field(cf, 'Type'),
        pegar_custom_field(cf, 'Enviroment'),
        pegar_custom_field(cf, 'Nubank Owner'),
        pegar_custom_field(cf, 'OS Name'),
        pegar_custom_field(cf, 'Allocated'),
        pegar_custom_field(cf, 'IP Address'),
        pegar_custom_field(cf, 'MAC Address'),
        pegar_custom_field(cf, 'Leasing Contract'),
        pegar_custom_field(cf, 'Leasing Company'),
        pegar_custom_field(cf, 'substatus'),
        pegar_custom_field(cf, 'CPU'),
        pegar_custom_field(cf, 'RAM'),
        pegar_custom_field(cf, 'Storage'),
        pegar_custom_field(cf, 'Leasing Date of Return'),
        pegar_custom_field(cf, 'Fixed Asset Number'),
        pegar_custom_field(cf, 'ITCLI User Executer'),
        pegar_custom_field(cf, 'Ticket Link'),
        pegar_custom_field(cf, 'Year'),
        pegar_custom_field(cf, 'Display Size'),
        ''
    ]


def buscar_assets_snipeit():
    """Busca todos os assets do Snipe-IT"""
    logger.info("Fetching assets from Snipe-IT...")
    
    headers = {
        'authorization': f"Bearer {SNIPEIT_TOKEN}",
        'accept': "application/json",
        'content-type': "application/json"
    }
    
    todos_assets = []
    limite = 500
    inicio = 0
    
    while True:
        url = f"{SNIPEIT_URL}/hardware?limit={limite}&offset={inicio}"
        
        try:
            resposta = requests.get(url, headers=headers, verify=False, timeout=30)
            
            if resposta.status_code != 200:
                logger.error(f"API error: {resposta.status_code}")
                break
            
            dados = resposta.json()
            assets = dados.get('rows', [])
            total = dados.get('total', 0)
            
            if not assets:
                break
            
            todos_assets.extend(assets)
            print(f"   📦 Coletados: {len(todos_assets)} de {total} assets...")
            
            if len(assets) < limite:
                break
            
            inicio += limite
            
        except Exception as erro:
            logger.error(f"Error fetching assets: {erro}", exc_info=True)
            break
    
    logger.info(f"Total assets fetched: {len(todos_assets)}")
    return todos_assets


def enviar_para_planilha(linhas):
    """Conecta no Google Sheets e envia os dados"""
    logger.info("Connecting to Google Sheets...")
    
    # Headers das colunas
    headers = [
        'ID', 'Company', 'Asset Name', 'Asset Tag', 'Model', 'Model No.', 'Category',
        'Manufacturer', 'Serial', 'Purchased', 'Cost', 'EOL', 'Warranty', 
        'Warranty Expires', 'Current Value', 'Diff', 'Fully Depreciated',
        'Order Number', 'Supplier', 'Location',
        'Address', 'Address', 'City', 'State', 'Country', 'Zip',
        'Default Location',
        'Address', 'Address', 'City', 'State', 'Country', 'Zip',
        'Checked Out', 'Type', 'Username', 'Employee No.', 'Manager', 'Department',
        'Title', 'Phone', 'User Address', 'User City', 'User State', 'User Country',
        'User Zip', 'Status', 'Checkout Date', 'Last Checkin Date',
        'Expected Checkin Date', 'Created At', 'Updated at', 'Deleted',
        'Last Audit', 'Next Audit Date', 'Notes', 'URL', 
        'Nota Fiscal', 'third_party', 'Link NF', 'Leasing Start Date', 
        'Leasing End Date', 'Validated', 'SIM Card', 
        'Termo de Responsabilidade Enviado', 'Termo de Responsabilidade Assinado',
        'No de Factura', 'Repair Reason', 'Warranty Expiration Date', 'Type',
        'Enviroment', 'Nubank Owner', 'OS Name', 'Allocated', 'IP Address',
        'MAC Address', 'Leasing Contract', 'Leasing Company', 'substatus',
        'CPU', 'RAM', 'Storage', 'Leasing Date of Return', 'Fixed Asset Number',
        'ITCLI User Executer', 'Ticket Link', 'Year', 'Display Size', ''
    ]
    
    # Conecta no Google
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    credenciais = Credentials.from_service_account_file(GOOGLE_CREDENTIALS, scopes=scopes)
    client = gspread.authorize(credenciais)
    planilha = client.open_by_url(PLANILHA_URL)
    
    # Nome fixo da aba (para IMPORTRANGE funcionar)
    nome_aba = "Report Principal"
    
  	# Tenta selecionar a aba existente
    try:
        aba = planilha.worksheet(nome_aba)
    	# Se ela existe, apenas limpamos os dados antigos
        aba.clear()
        logger.info(f"Aba '{nome_aba}' encontrada e limpa.")

        # Opcional: Redimensiona se o número de linhas mudou drasticamente
        # aba.resize(rows=len(linhas) + 10, cols=90)
    
    except gspread.exceptions.WorksheetNotFound:
        # Se realmente não existir, aí sim criamos
        aba = planilha.add_worksheet(title=nome_aba, rows=len(linhas) + 10, cols=90)
        logger.info(f"Nova aba '{nome_aba}' criada.")


    # Monta dados: [data] + [headers] + [linhas]
    todos_dados = [headers] + linhas
    
    logger.info(f"Uploading {len(linhas)} rows to Google Sheets...")
    
    # Envia em blocos de 5000
    tamanho_bloco = 5000
    total_blocos = (len(todos_dados) + tamanho_bloco - 1) // tamanho_bloco
    
    for bloco_num, i in enumerate(range(0, len(todos_dados), tamanho_bloco), 1):
        bloco = todos_dados[i:i + tamanho_bloco]
        linha_inicial = i + 1
        print(f"   📤 Enviando bloco {bloco_num}/{total_blocos}...")
        aba.update(values=bloco, range_name=f"A{linha_inicial}", value_input_option='USER_ENTERED')
    
    logger.info("Upload completed successfully")
    
    url_aba = f"{PLANILHA_URL}/edit#gid={aba.id}"
    return url_aba, nome_aba


def is_weekday():
    """Verifica se é dia útil (segunda a sexta)"""
    return datetime.now().weekday() < 5


def exportar_report():
    """Busca assets e envia pra planilha"""
    if not is_weekday():
        logger.info("Weekend - skipping export")
        return
    
    inicio = datetime.now()
    logger.info("="*70)
    logger.info("Starting export process")
    logger.info("="*70)
    
    # 1. Busca assets
    assets = buscar_assets_snipeit()
    if not assets:
        logger.warning("No assets found")
        return
    
    # 2. Processa
    logger.info(f"Processing {len(assets)} assets...")
    linhas = []
    for i, asset in enumerate(assets, 1):
        linhas.append(montar_linha_asset(asset))
        if i % 1000 == 0:
            print(f"   ⚙️  Processados: {i}/{len(assets)} assets...")
    
    logger.info(f"Processed {len(linhas)} rows")
    
    # 3. Envia
    try:
        url, nome = enviar_para_planilha(linhas)
        
        fim = datetime.now()
        duracao = fim - inicio
        minutos = int(duracao.total_seconds() / 60)
        segundos = int(duracao.total_seconds() % 60)
        
        logger.info("="*70)
        logger.info("Export completed successfully")
        logger.info(f"Sheet: {nome}")
        logger.info(f"Total assets: {len(linhas)}")
        logger.info(f"Duration: {minutos}min {segundos}s")
        logger.info(f"URL: {url}")
        logger.info("="*70)
        
    except Exception as e:
        logger.error(f"Export failed: {e}", exc_info=True)


def run_scheduler():
    """Roda automaticamente 2x por dia: 08h e 12h (seg-sex)"""
    schedule.every().day.at("08:00").do(exportar_report)
    schedule.every().day.at("12:00").do(exportar_report)
    
    logger.info("Snipe-IT Export - Scheduler Started")
    logger.info("Daily exports at 08:00 and 12:00 (Mon-Fri)")
    
    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Scheduler stopped by user")
            break
        except Exception as e:
            logger.error(f"Scheduler error: {e}", exc_info=True)
            time.sleep(60)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--schedule', action='store_true')
    args = parser.parse_args()
    
    if args.schedule:
        run_scheduler()
    else:
        exportar_report()
