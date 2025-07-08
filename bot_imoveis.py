import os
import hashlib
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import telegram
import time
import schedule
import json
import sys

# Configuração
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')

# Sites para monitorar - também via variável de ambiente
sites_env = os.environ.get('SITES_IMOBILIARIAS', '')
SITES_IMOBILIARIAS = [site.strip() for site in sites_env.split(',') if site.strip()]

# Se não houver sites definidos no ambiente, use esta lista padrão
if not SITES_IMOBILIARIAS:
    SITES_IMOBILIARIAS = [
        # Adicione suas URLs aqui como fallback
    ]

# Inicializar bot do Telegram
bot = telegram.Bot(token=TELEGRAM_TOKEN) if TELEGRAM_TOKEN else None

# Arquivo para salvar hashes das páginas monitoradas
HASHES_ARQUIVO = 'paginas_hashes.json'
LOGS_ARQUIVO = 'notificacoes.txt'  # Definindo a variável LOGS_ARQUIVO aqui

def salvar_hashes(hashes):
    print(f"Salvando hashes em: {os.path.abspath(HASHES_ARQUIVO)}")
    print(f"Conteúdo dos hashes: {json.dumps(hashes)[:200]}...")  # Mostrar início do conteúdo
    
    with open(HASHES_ARQUIVO, 'w', encoding='utf-8') as f:
        json.dump(hashes, f)
    
    print(f"Arquivo salvo. Tamanho: {os.path.getsize(HASHES_ARQUIVO)} bytes")

# Configurar caminho para arquivos com base no diretório atual
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HASHES_ARQUIVO = os.path.join(BASE_DIR, 'paginas_hashes.json')
LOGS_ARQUIVO = os.path.join(BASE_DIR, 'notificacoes.txt')

print(f"Diretório base: {BASE_DIR}")
print(f"Arquivo de hashes: {HASHES_ARQUIVO}")

# Função para enviar notificação
def enviar_notificacao(mensagem):
    # Salvar em arquivo
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOGS_ARQUIVO, 'a', encoding='utf-8') as f:
        f.write(f"[{timestamp}] {mensagem}\n\n")

    # Enviar para o Telegram se configurado
    if bot:
        try:
            bot.send_message(
                chat_id=CHAT_ID,
                text=mensagem,
                parse_mode="Markdown"
            )
            print(f"Notificação enviada para o Telegram")
        except Exception as e:
            print(f"Erro ao enviar notificação para o Telegram: {str(e)}")
    else:
        print("Telegram não configurado. Mensagem salva apenas no arquivo.")

    print(mensagem)

# Carregar hashes das páginas anteriores
def carregar_hashes():
    if os.path.exists(HASHES_ARQUIVO):
        with open(HASHES_ARQUIVO, 'r') as f:
            return json.load(f)
    return {}

# Salvar hashes atuais
def salvar_hashes(hashes):
    with open(HASHES_ARQUIVO, 'w') as f:
        json.dump(hashes, f)

# Função para limpar o HTML removendo partes não relevantes
def limpar_html(html):
    soup = BeautifulSoup(html, 'html.parser')

    # Remover scripts, estilos e comentários
    for tag in soup(['script', 'style', 'meta', 'link', 'noscript']):
        tag.decompose()

    # Remover comentários HTML
    for comment in soup.find_all(string=lambda text: isinstance(text, str) and '<!--' in text):
        comment.extract()

    return str(soup)

# Extrair seções potenciais de listagens
def extrair_secoes_listagem(html):
    soup = BeautifulSoup(html, 'html.parser')

    # Procurar seções que provavelmente são listagens de imóveis
    # Estratégia 1: Procurar por contêineres com vários elementos similares
    secoes = []

    # Procurar padrões comuns em sites imobiliários
    padrao_classes = ['listing', 'results', 'properties', 'imoveis', 'cards', 'grid', 'lista']
    for classe in padrao_classes:
        containers = soup.select(f"div[class*='{classe}'], ul[class*='{classe}'], section[class*='{classe}']")
        secoes.extend(containers)

    # Se nada for encontrado, procurar divs que contêm múltiplos elementos com estrutura similar
    if not secoes:
        candidatos = soup.select('div, section, ul')
        for candidato in candidatos:
            # Verificar se tem vários filhos similares (potencial listagem)
            filhos = candidato.find_all(['article', 'div', 'li'], recursive=False)
            if len(filhos) >= 3:  # Pelo menos 3 itens similares
                secoes.append(candidato)

    # Se ainda não encontrou nada, procurar por artigos ou cards
    if not secoes:
        secoes = soup.select('article, div.card, div[class*="card"], li[class*="item"]')

    return secoes

# Função principal para verificar mudanças nas seções de listagens
def verificar_mudancas():
    hashes_anteriores = carregar_hashes()
    hashes_atuais = {}
    mudancas_detectadas = False

    for site in SITES_IMOBILIARIAS:
        print(f"Verificando: {site}")

        try:
            # Fazer requisição HTTP com cabeçalhos de navegador
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml",
                "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7"
            }
            response = requests.get(site, headers=headers, timeout=30)

            if response.status_code == 200:
                # Limpar o HTML
                html_limpo = limpar_html(response.text)

                # Extrair seções que parecem ser listagens
                secoes = extrair_secoes_listagem(html_limpo)

                # Se não encontrou seções específicas, usar a página toda
                if not secoes:
                    print(f"Nenhuma seção de listagem identificada em {site}. Usando página completa.")
                    secoes = [BeautifulSoup(html_limpo, 'html.parser')]

                print(f"Encontradas {len(secoes)} possíveis seções de listagem em {site}")

                # Para cada seção, calcular um hash
                hashes_secoes = []
                for i, secao in enumerate(secoes):
                    # Pegar apenas o texto e links, ignorando formatação
                    conteudo = []
                    for elem in secao.find_all(['a', 'h1', 'h2', 'h3', 'h4', 'p', 'span']):
                        if elem.name == 'a' and elem.get('href'):
                            conteudo.append(f"{elem.text.strip()}:{elem.get('href')}")
                        else:
                            conteudo.append(elem.text.strip())

                    # Filtrar strings vazias
                    conteudo = [c for c in conteudo if c]

                    if conteudo:
                        # Calcular hash do conteúdo
                        conteudo_str = '|'.join(conteudo)
                        hash_secao = hashlib.md5(conteudo_str.encode('utf-8')).hexdigest()
                        hashes_secoes.append(hash_secao)

                # Verificar se há mudanças
                site_key = site.split('/')[2]  # Ex: www.imobiliaria1.com.br

                if site_key in hashes_anteriores:
                    # Comparar hashes anteriores com atuais
                    hashes_antigos = set(hashes_anteriores[site_key])
                    hashes_novos = set(hashes_secoes)

                    # Verificar se há novos hashes (novas seções ou seções alteradas)
                    novos = hashes_novos - hashes_antigos

                    if novos:
                        mudancas_detectadas = True
                        num_novos = len(novos)
                        mensagem = f"🏠 NOVOS IMÓVEIS DETECTADOS!\n\n"
                        mensagem += f"Detectei mudanças em {num_novos} seção(ões) em:\n"
                        mensagem += f"{site_key} - {site}\n\n"
                        mensagem += "Acesse o site para ver os novos imóveis!"
                        enviar_notificacao(mensagem)

                # Armazenar hashes atuais para próxima verificação
                hashes_atuais[site_key] = hashes_secoes

            else:
                print(f"Erro ao acessar {site}: Status code {response.status_code}")

        except Exception as e:
            print(f"Erro ao processar {site}: {str(e)}")

    # Salvar os hashes atuais
    salvar_hashes(hashes_atuais)

    return mudancas_detectadas

# 5. BLOCO PRINCIPAL DE EXECUÇÃO
if __name__ == "__main__":
    print(f"Bot de monitoramento iniciando verificação em {datetime.now()}")

    # Verificar configurações
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("AVISO: Token do Telegram ou Chat ID não configurados!")
        print("As notificações serão salvas apenas em arquivo.")

    if not SITES_IMOBILIARIAS:
        print("ERRO: Nenhum site configurado para monitorar!")
        sys.exit(1)

    print(f"Monitorando {len(SITES_IMOBILIARIAS)} sites.")

    # Verificar se o arquivo de hashes já existe
    if not os.path.exists(HASHES_ARQUIVO):
        print(f"Arquivo de hashes não encontrado. Criando arquivo inicial...")
        # Criar um arquivo inicial vazio
        with open(HASHES_ARQUIVO, 'w', encoding='utf-8') as f:
            json.dump({}, f)
        print(f"Arquivo de hashes inicial criado: {HASHES_ARQUIVO}")

    # No GitHub Actions, executamos apenas uma verificação por execução
    verificar_mudancas()

    print(f"Verificação concluída em {datetime.now()}")
